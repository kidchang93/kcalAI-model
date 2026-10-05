"""Sign in with Apple 어댑터 — identity token 검증 · authorization code 교환 · 토큰 폐기.

카카오(서버 주도 OAuth)와 달리 **iOS 가 기기에서** identity token(JWT)과 authorization code 를 받고,
앱이 그 둘을 서버로 보낸다. 서버는:

1. identity token 을 Apple 공개키(JWKS)로 검증해 `sub`(사용자 식별자)를 꺼낸다 — 로그인·가입 둘 다.
2. 가입 때 authorization code 를 refresh token 으로 바꿔 둔다 — **탈퇴 때 폐기(revoke)하려면 이 토큰이
   필요하다**(Apple 계정 삭제 요건). 교환·폐기에는 `.p8` 키로 서명한 client secret 이 든다.

토큰·코드·키는 로그에 남기지 않는다 — 실패는 예외 타입명과 Apple 의 오류 코드만 남긴다.
"""

import base64
import os
import ssl
import time

import certifi
import jwt
import requests

from log_utils import get_logger
from services.errors import BadRequestError

logger = get_logger(__name__)

# identity token 의 aud 이자 토큰 교환의 client_id. 네이티브 앱이라 Services ID 가 아니라 번들 ID 다.
APPLE_BUNDLE_ID = os.getenv("APPLE_BUNDLE_ID", "com.kcalai.kcalairn")
# client secret 서명용. 셋이 없으면 가입은 503 이다 — 교환을 못 하면 탈퇴 때 폐기할 토큰이 없다.
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
APPLE_SIWA_KEY_ID = os.getenv("APPLE_SIWA_KEY_ID", "")
# .p8 파일 내용을 base64 한 줄로. 파일로 두지 않는 이유: 배포가 작업 트리를 rsync --delete 해서
# 서버 디렉토리의 키 파일은 지워지고 .env 만 남는다.
APPLE_SIWA_PRIVATE_KEY_B64 = os.getenv("APPLE_SIWA_PRIVATE_KEY_B64", "")

ISSUER = "https://appleid.apple.com"
KEYS_URL = f"{ISSUER}/auth/keys"
TOKEN_URL = f"{ISSUER}/auth/token"
REVOKE_URL = f"{ISSUER}/auth/revoke"

APPLE_TIMEOUT_SECONDS = 5
# Apple 상한은 6개월이지만 우리는 호출 직전에 만들어 한 번 쓴다.
CLIENT_SECRET_TTL_SECONDS = 300

TOKEN_INVALID_MESSAGE = "Apple 로그인 정보가 만료되었습니다. 다시 시도해주세요."
UNAVAILABLE_MESSAGE = "Apple 로그인을 지금 확인할 수 없어요. 잠시 후 다시 시도해주세요."
NOT_CONFIGURED_MESSAGE = "Apple 로그인을 지금 쓸 수 없어요."

# JWK Set 을 5분 캐시한다(기본값). 모르는 kid 의 강제 갱신은 라이브러리가 30초 쿨다운으로 묶는다 —
# 무인증 라우트라 위조 kid 로 Apple 을 대신 두드리게 만드는 통로가 되면 안 된다.
# 키 단위 LRU(cache_keys)는 켜지 않는다: 만료가 없어 Apple 이 내린 키를 계속 믿게 된다.
# CA 는 requests 와 같은 certifi 묶음을 쓴다 — PyJWKClient 는 urllib 라 OS 의 CA 저장소를 보는데,
# python.org 빌드(macOS)는 그 저장소로 Apple 인증서 검증에 실패했다(2026-10-05 로컬 실측).
_jwks_client = jwt.PyJWKClient(
    KEYS_URL,
    timeout=APPLE_TIMEOUT_SECONDS,
    ssl_context=ssl.create_default_context(cafile=certifi.where()),
)


class AppleUnavailableError(Exception):
    """Apple 공개키를 못 가져왔거나 SIWA 설정이 없다. api 가 503 으로 바꾼다 (메시지는 사용자 문구).

    토큰이 틀린 경우는 이게 아니라 `BadRequestError`(400) 다 — 앱이 Apple 로그인을 다시 띄운다.
    """


def verify_identity_token(identity_token: str) -> str:
    """Apple 이 서명한 identity token 을 검증하고 `sub` 를 돌려준다. 만료(exp)는 라이브러리가 본다."""
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(identity_token)
        claims = jwt.decode(
            identity_token,
            signing_key.key,
            # alg 를 토큰 헤더에서 믿지 않는다 — none·HS256(공개키를 HMAC 비밀로 쓰는 위조)을 막는다.
            algorithms=["RS256"],
            audience=APPLE_BUNDLE_ID,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWKClientConnectionError as error:
        logger.error(f"apple jwks fetch fail: {error!r}")
        raise AppleUnavailableError(UNAVAILABLE_MESSAGE) from error
    except jwt.PyJWTError as error:
        # 메시지는 남기지 않는다 — 무인증 라우트라 공격자가 만든 문자열(kid 등)이 그대로 실린다.
        logger.error(f"apple identity token rejected: {type(error).__name__}")
        raise BadRequestError(TOKEN_INVALID_MESSAGE) from error

    return claims["sub"]


def is_configured() -> bool:
    return bool(APPLE_TEAM_ID and APPLE_SIWA_KEY_ID and APPLE_SIWA_PRIVATE_KEY_B64)


def exchange_code(authorization_code: str) -> str:
    """authorization code → refresh token. 코드는 1회용·5분이라, 실패하면 앱이 Apple 로그인을 다시 띄운다."""
    response = _post(
        TOKEN_URL, {"code": authorization_code, "grant_type": "authorization_code"}, "token exchange"
    )

    if response is None:
        raise BadRequestError(TOKEN_INVALID_MESSAGE)

    if response.status_code >= 400:
        error_code = _error_code(response)
        logger.error(f"apple token exchange rejected status={response.status_code} error={error_code}")

        # 우리 키·팀·kid 가 틀린 것이다. 사용자가 다시 시도해도 풀리지 않으니 400(재시도)이 아니다.
        if error_code == "invalid_client":
            raise AppleUnavailableError(NOT_CONFIGURED_MESSAGE)

        raise BadRequestError(TOKEN_INVALID_MESSAGE)

    refresh_token = _json(response).get("refresh_token")

    if not refresh_token:
        logger.error("apple token exchange returned no refresh_token")
        raise BadRequestError(TOKEN_INVALID_MESSAGE)

    return refresh_token


def revoke_token(refresh_token: str) -> None:
    """회원 탈퇴 시 **의무**(Apple 계정 삭제 요건). 카카오 unlink 와 같은 규칙으로 예외를 올리지 않는다 —
    Apple 장애로 개인정보 파기가 막히면 안 된다. 호출 시점엔 토큰을 이미 파기했으므로 재시도할 수 없고,
    남은 연결은 사용자가 Apple ID 설정에서 끊을 수 있다.
    """
    try:
        response = _post(
            REVOKE_URL, {"token": refresh_token, "token_type_hint": "refresh_token"}, "revoke"
        )
    except AppleUnavailableError:
        logger.error("apple revoke skipped: SIWA 설정 미비")
        return

    if response is not None and response.status_code >= 400:
        logger.error(f"apple revoke fail status={response.status_code} error={_error_code(response)}")


def _post(url: str, data: dict[str, str], label: str) -> requests.Response | None:
    """client_id·client_secret 을 붙여 보낸다. 네트워크 실패면 None (로그는 여기서 남긴다)."""
    form = {"client_id": APPLE_BUNDLE_ID, "client_secret": _client_secret(), **data}

    try:
        return requests.post(url, data=form, timeout=APPLE_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        logger.error(f"apple {label} fail: {type(error).__name__}")
        return None


def _client_secret() -> str:
    """ES256 JWT (kid=키 ID, iss=팀 ID, sub=번들 ID, aud=Apple). 설정이 없거나 키가 깨졌으면 503."""
    if not is_configured():
        raise AppleUnavailableError(NOT_CONFIGURED_MESSAGE)

    now = int(time.time())

    try:
        return jwt.encode(
            {
                "iss": APPLE_TEAM_ID,
                "iat": now,
                "exp": now + CLIENT_SECRET_TTL_SECONDS,
                "aud": ISSUER,
                "sub": APPLE_BUNDLE_ID,
            },
            base64.b64decode(APPLE_SIWA_PRIVATE_KEY_B64),
            algorithm="ES256",
            headers={"kid": APPLE_SIWA_KEY_ID},
        )
    except (ValueError, TypeError, jwt.PyJWTError) as error:
        logger.error(f"apple client secret build fail: {type(error).__name__}")
        # 원인 체인을 끊는다 — 키 파싱 예외가 트레이스백으로 찍히는 경로를 남기지 않는다.
        raise AppleUnavailableError(NOT_CONFIGURED_MESSAGE) from None


def _json(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}

    return payload if isinstance(payload, dict) else {}


def _error_code(response: requests.Response) -> str:
    # Apple 오류 본문은 {"error": "invalid_grant"} 형태다. 우리 토큰·키는 실리지 않는다.
    return str(_json(response).get("error", "unknown"))[:40]
