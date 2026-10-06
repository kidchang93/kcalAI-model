"""App Store Server API 어댑터 — 구독 거래 조회 (DATA_MODEL.md 32-3·32-4).

앱이 보낸 `transactionId`, 알림이 실어 온 `originalTransactionId` 는 **조회 키일 뿐이다.** 서버가 인앱 결제
키(ES256)로 서명한 JWT 로 Apple 에 다시 물어보고 그 응답만 믿는다(29장 웹훅과 같은 규약).

응답 안의 거래 정보는 Apple 이 서명한 JWS 지만 **서명을 검증하지 않고 페이로드만 읽는다** — 우리 키로
인증한 HTTPS 조회의 응답이라 출처가 이미 확인됐고, 앱·알림 본문의 상태를 믿는 경로가 없으므로 x5c 체인
검증 라이브러리를 들일 이유가 없다. (Sign in with Apple identity token 은 다르다 — 그쪽은 앱이 들고 온
토큰 자체가 증거라 `apple_client.verify_identity_token` 이 반드시 서명을 본다.)

키·토큰은 로그에 남기지 않는다 — 실패는 예외 타입명과 Apple 의 상태·오류 코드만 남긴다.
"""

import base64
import os
import time
from dataclasses import dataclass
from urllib.parse import quote

import jwt
import requests

from log_utils import get_logger
from services.apple_client import APPLE_BUNDLE_ID

logger = get_logger(__name__)

# App Store Connect > 사용자 및 액세스 > 통합 > 인앱 결제 키. SIWA 키와 **다른 키**다.
APPLE_IAP_KEY_ID = os.getenv("APPLE_IAP_KEY_ID", "")
APPLE_IAP_ISSUER_ID = os.getenv("APPLE_IAP_ISSUER_ID", "")
# .p8 내용을 base64 한 줄로 (apple_client 와 같은 이유 — 배포 rsync 가 키 파일을 지운다).
APPLE_IAP_PRIVATE_KEY_B64 = os.getenv("APPLE_IAP_PRIVATE_KEY_B64", "")

PRODUCTION = "Production"
SANDBOX = "Sandbox"
BASE_URLS = {
    PRODUCTION: "https://api.storekit.itunes.apple.com",
    SANDBOX: "https://api.storekit-sandbox.itunes.apple.com",
}
# 운영에서 이 코드면 샌드박스 거래일 수 있다 — App Review 는 운영 서버에 샌드박스 구매로 들어온다.
ERROR_TRANSACTION_ID_NOT_FOUND = 4040010

APPSTORE_TIMEOUT_SECONDS = 10
# Apple 상한은 1시간이지만 호출 직전에 만들어 한 번 쓴다.
TOKEN_TTL_SECONDS = 300

UNAVAILABLE_MESSAGE = "구독 정보를 지금 확인할 수 없어요. 잠시 후 다시 시도해주세요."


class AppStoreUnavailableError(Exception):
    """키 미설정·네트워크 실패·Apple 장애 — 아직 판단하지 못했다. api 가 503 으로 바꾼다(메시지는 사용자 문구).

    "거래가 없다"는 이게 아니라 조회 함수의 `None` 이다 — 몇 번을 물어도 같은 답이라 재시도 대상이 아니다.
    """


@dataclass(frozen=True)
class SubscriptionStatus:
    # 1 활성 · 2 만료 · 3 결제 재시도 · 4 유예 · 5 환불·취소 (App Store Server API `status`)
    status: int | None
    # 이 구독의 **최신** 거래(JWSTransactionDecodedPayload)와 갱신 정보(JWSRenewalInfoDecodedPayload).
    transaction: dict
    renewal: dict


def is_configured() -> bool:
    return bool(APPLE_IAP_KEY_ID and APPLE_IAP_ISSUER_ID and APPLE_IAP_PRIVATE_KEY_B64)


def decode_jws(token: object) -> dict:
    """JWS 페이로드를 **검증 없이** 읽는다 (모듈 docstring). 형식이 틀리면 ValueError."""
    if not isinstance(token, str):
        raise ValueError("JWS 가 아니다")

    try:
        payload = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        # 원문을 싣지 않는다 — 알림 경로에서는 공격자가 만든 문자열이다.
        raise ValueError("JWS 를 읽을 수 없다") from None

    return payload


def get_transaction(transaction_id: str) -> tuple[dict, str] | None:
    """거래 정보와 **찾은 환경**. 운영에 없으면(4040010) 샌드박스를 본다. 어디에도 없으면 None."""
    path = f"/inApps/v1/transactions/{quote(transaction_id, safe='')}"

    for environment in (PRODUCTION, SANDBOX):
        status_code, body = _get(environment, path)

        if status_code == 200:
            return _decode_response(body.get("signedTransactionInfo"), environment), environment

        if environment == PRODUCTION and body.get("errorCode") == ERROR_TRANSACTION_ID_NOT_FOUND:
            continue

        logger.info(f"appstore transaction not found env={environment} errorCode={body.get('errorCode')}")
        return None

    return None


def get_subscription_status(
    original_transaction_id: str, environment: str
) -> SubscriptionStatus | None:
    """`/inApps/v1/subscriptions/{id}` — 그 구독의 현재 상태·최신 거래·갱신 정보. 없으면 None."""
    status_code, body = _get(
        environment, f"/inApps/v1/subscriptions/{quote(original_transaction_id, safe='')}"
    )

    if status_code != 200:
        logger.info(f"appstore subscription not found env={environment} errorCode={body.get('errorCode')}")
        return None

    for group in body.get("data") or []:
        for item in group.get("lastTransactions") or []:
            if str(item.get("originalTransactionId")) != original_transaction_id:
                continue

            renewal = item.get("signedRenewalInfo")
            return SubscriptionStatus(
                status=item.get("status"),
                transaction=_decode_response(item.get("signedTransactionInfo"), environment),
                renewal=_decode_response(renewal, environment) if renewal else {},
            )

    return None


def _decode_response(token: object, environment: str) -> dict:
    # 우리가 부른 조회의 응답이 깨져 있으면 Apple 쪽 이상이다 — 판단하지 못한 것이라 503.
    try:
        return decode_jws(token)
    except ValueError:
        logger.error(f"appstore {environment} response JWS unreadable")
        raise AppStoreUnavailableError(UNAVAILABLE_MESSAGE) from None


def _get(environment: str, path: str) -> tuple[int, dict]:
    """200·400·404 는 (상태, 본문)으로 돌려준다 — 답이 정해진 응답이다. 그 밖(401 키 오류·429·5xx)과
    네트워크 실패는 AppStoreUnavailableError.
    """
    token = _token()

    try:
        response = requests.get(
            f"{BASE_URLS[environment]}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=APPSTORE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        logger.error(f"appstore {environment} request fail: {type(error).__name__}")
        # 원인 체인을 끊는다 — 상위가 트레이스백을 찍을 때 요청 헤더(토큰)가 실릴 여지를 남기지 않는다.
        raise AppStoreUnavailableError(UNAVAILABLE_MESSAGE) from None

    body = _json(response)

    if response.status_code in (200, 400, 404):
        return response.status_code, body

    logger.error(
        f"appstore {environment} status={response.status_code} errorCode={body.get('errorCode')}"
    )
    raise AppStoreUnavailableError(UNAVAILABLE_MESSAGE)


def _token() -> str:
    """ES256 JWT (kid=키 ID, iss=발급자 ID, aud=appstoreconnect-v1, bid=번들 ID). 설정이 없거나 키가 깨졌으면 503."""
    if not is_configured():
        logger.error("appstore lookup skipped: APPLE_IAP_* 미설정")
        raise AppStoreUnavailableError(UNAVAILABLE_MESSAGE)

    now = int(time.time())

    try:
        return jwt.encode(
            {
                "iss": APPLE_IAP_ISSUER_ID,
                "iat": now,
                "exp": now + TOKEN_TTL_SECONDS,
                "aud": "appstoreconnect-v1",
                "bid": APPLE_BUNDLE_ID,
            },
            base64.b64decode(APPLE_IAP_PRIVATE_KEY_B64),
            algorithm="ES256",
            headers={"kid": APPLE_IAP_KEY_ID, "typ": "JWT"},
        )
    except (ValueError, TypeError, jwt.PyJWTError) as error:
        logger.error(f"appstore token build fail: {type(error).__name__}")
        raise AppStoreUnavailableError(UNAVAILABLE_MESSAGE) from None


def _json(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}

    return payload if isinstance(payload, dict) else {}
