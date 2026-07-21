"""카카오 OAuth 어댑터 — 인가 URL 생성 · 토큰 교환 · 사용자 조회 · 연결 끊기.

**토큰 교환은 반드시 서버에서 한다.** 신규 REST API 키는 클라이언트 시크릿이 기본 활성이라
`client_secret` 없이는 토큰이 나오지 않는데, 앱 번들(JS·APK·IPA)에 시크릿을 넣으면 누구나
추출해 임의 사용자의 토큰을 발급받을 수 있다. Expo 의 `EXPO_PUBLIC_*`도 평문 노출이라 시크릿
저장소가 아니다. 그래서 앱은 서버 URL 만 열고, 카카오와의 교환은 전부 여기서 일어난다.

**커스텀 스킴(`kcalairn://`)은 카카오 Redirect URI 로 등록할 수 없다** — 카카오는 http/https 만
받는다. 그래서 콜백은 서버(https)가 받고, 서버가 앱으로 딥링크를 되돌려준다.

키·토큰은 로그에 남기지 않는다 — 실패는 상태코드와 예외 타입명만 남긴다.
"""

import logging
import os

import requests

from log_utils import setup_level_logger

error_logger = setup_level_logger(logging.ERROR)

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
# 신규 REST 키는 클라이언트 시크릿이 기본 [ON] 이라 사실상 필수다.
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")
# 연결 끊기(unlink)를 어드민 키로 한다 — 카카오 액세스 토큰을 서버에 보관하지 않기 위해서다.
KAKAO_ADMIN_KEY = os.getenv("KAKAO_ADMIN_KEY", "")
# 카카오 콘솔에 등록한 값과 **문자 단위로 같아야** 한다 (다르면 KOE006).
KAKAO_REDIRECT_URI = os.getenv(
    "KAKAO_REDIRECT_URI", "http://localhost:8000/api/auth/kakao/callback"
)

AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
USER_ME_URL = "https://kapi.kakao.com/v2/user/me"
UNLINK_URL = "https://kapi.kakao.com/v1/user/unlink"

# 일반(기본) 앱이 심사 없이 받을 수 있는 항목. 회원번호(id)는 동의 없이 항상 제공된다.
# 이메일은 비즈 앱 전환(본인인증) 후, 전화번호는 사업자 정보가 등록된 비즈 앱만 신청할 수 있다.
KAKAO_SCOPE = "profile_nickname"

KAKAO_TIMEOUT_SECONDS = float(os.getenv("KAKAO_TIMEOUT_SECONDS", "5"))


class KakaoError(Exception):
    """카카오 연동 실패. api 레이어가 503(일시 장애) 또는 400(잘못된 코드)으로 변환한다."""


class KakaoAuthCodeError(KakaoError):
    """인가 코드가 만료·재사용됐거나 위조됐다 — 사용자에게 재시도를 요구한다 (400)."""


def is_configured() -> bool:
    return bool(KAKAO_REST_API_KEY and KAKAO_CLIENT_SECRET)


def _error_code(response: requests.Response) -> str:
    """카카오 에러 응답에서 식별 코드와 사유를 뽑는다.

    상태코드만으로는 원인이 갈린다 — 401 하나에 토큰 만료, 앱 정보 불일치(KOE101),
    **허용 IP 미등록**(`ip mismatched`)이 전부 `code=-401` 로 섞여 온다. 코드만으로도
    부족해서 카카오가 준 `msg` 를 함께 남긴다(원인이 여기에만 있다). 우리 토큰·키는
    이 본문에 실리지 않으므로 로그에 남겨도 비밀이 새지 않는다.
    """
    try:
        payload = response.json()
    except ValueError:
        return "unparsable"
    code = payload.get("error_code") or payload.get("code") or payload.get("error")
    msg = payload.get("msg") or payload.get("error_description") or ""
    return f"{code if code is not None else 'unknown'} msg={msg[:120]!r}"


def ensure_production_kakao_config() -> None:
    # APP_ENV=production 기동 시 main.py 가 호출한다. 카카오가 유일한 인증 수단이라,
    # 설정이 없으면 아무도 로그인하지 못한다.
    if not KAKAO_REST_API_KEY:
        raise RuntimeError("APP_ENV=production에서는 KAKAO_REST_API_KEY가 필요합니다.")

    if not KAKAO_CLIENT_SECRET:
        raise RuntimeError(
            "APP_ENV=production에서는 KAKAO_CLIENT_SECRET가 필요합니다 "
            "(신규 REST 키는 클라이언트 시크릿이 기본 활성입니다)."
        )

    if not KAKAO_ADMIN_KEY:
        raise RuntimeError(
            "APP_ENV=production에서는 KAKAO_ADMIN_KEY가 필요합니다 "
            "(회원 탈퇴 시 카카오 연결 끊기는 의무입니다)."
        )

    if not KAKAO_REDIRECT_URI.startswith("https://"):
        raise RuntimeError(
            "APP_ENV=production에서는 KAKAO_REDIRECT_URI가 https여야 합니다."
        )


def build_authorize_url(state: str, force_login: bool = False) -> str:
    """`force_login=True` 면 카카오 세션이 있어도 로그인 화면을 다시 띄운다 (`prompt=login`).

    브라우저에 카카오 로그인 세션이 남아 있으면 카카오가 **묻지 않고 같은 계정으로** 인가 코드를
    내준다. 우리 앱에서 로그아웃해도 마찬가지라, 계정을 바꿀 방법이 없어진다 (공용 PC 문제이기도
    하다). '다른 카카오 계정으로 로그인' 경로가 이 플래그를 쓴다.
    """
    from urllib.parse import urlencode

    params = {
        "client_id": KAKAO_REST_API_KEY,
        "redirect_uri": KAKAO_REDIRECT_URI,
        "response_type": "code",
        "scope": KAKAO_SCOPE,
        "state": state,
    }

    if force_login:
        params["prompt"] = "login"

    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(code: str) -> str:
    """인가 코드 → 카카오 액세스 토큰. 코드는 **1회용**이라 재사용하면 실패한다."""
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": KAKAO_REST_API_KEY,
                "client_secret": KAKAO_CLIENT_SECRET,
                "redirect_uri": KAKAO_REDIRECT_URI,
                "code": code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
            timeout=KAKAO_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        error_logger.error(f"kakao token exchange fail: {error!r}")
        raise KakaoError("카카오 로그인에 실패했습니다.") from error

    if response.status_code == 400:
        # 만료·재사용된 코드, redirect_uri 불일치 등. 사용자가 다시 시도하면 풀린다.
        error_logger.error(
            f"kakao token exchange rejected status={response.status_code} "
            f"code={_error_code(response)}"
        )
        raise KakaoAuthCodeError("카카오 로그인이 만료되었습니다. 다시 시도해주세요.")

    if response.status_code >= 400:
        error_logger.error(f"kakao token exchange fail status={response.status_code}")
        raise KakaoError("카카오 로그인에 실패했습니다.")

    access_token = response.json().get("access_token")

    if not access_token:
        error_logger.error("kakao token exchange returned no access_token")
        raise KakaoError("카카오 로그인에 실패했습니다.")

    return access_token


def fetch_profile(access_token: str) -> tuple[str, str]:
    """액세스 토큰 → `(회원번호, 닉네임)`.

    회원번호는 동의 없이 항상 내려오지만 닉네임은 사용자가 거부할 수 있어 빈 값일 수 있다.
    """
    try:
        response = requests.get(
            USER_ME_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=KAKAO_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        error_logger.error(f"kakao user fetch fail: {error!r}")
        raise KakaoError("카카오 사용자 정보를 가져오지 못했습니다.") from error

    if response.status_code >= 400:
        error_logger.error(
            f"kakao user fetch fail status={response.status_code} code={_error_code(response)}"
        )
        raise KakaoError("카카오 사용자 정보를 가져오지 못했습니다.")

    payload = response.json()
    kakao_id = payload.get("id")

    if kakao_id is None:
        error_logger.error("kakao user fetch returned no id")
        raise KakaoError("카카오 사용자 정보를 가져오지 못했습니다.")

    nickname = (
        payload.get("kakao_account", {}).get("profile", {}).get("nickname")
        or payload.get("properties", {}).get("nickname")
        or ""
    )
    return str(kakao_id), nickname.strip()


def unlink(kakao_id: str) -> None:
    """앱과 사용자의 연결을 끊는다 (회원 탈퇴 시 **의무**).

    어드민 키 방식을 쓰는 이유는 카카오 액세스 토큰을 서버에 보관하지 않기 때문이다.
    실패해도 예외를 올리지 않는다 — 카카오 장애로 **우리 쪽 회원 탈퇴(개인정보 파기)가 막히면
    안 된다.** 실패는 로그로 남겨 수동 정리한다.
    """
    if not KAKAO_ADMIN_KEY:
        error_logger.error("kakao unlink skipped: KAKAO_ADMIN_KEY 미설정")
        return

    try:
        response = requests.post(
            UNLINK_URL,
            headers={"Authorization": f"KakaoAK {KAKAO_ADMIN_KEY}"},
            data={"target_id_type": "user_id", "target_id": kakao_id},
            timeout=KAKAO_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        error_logger.error(f"kakao unlink fail kakao_id={kakao_id}: {error!r}")
        return

    if response.status_code >= 400:
        error_logger.error(
            f"kakao unlink fail kakao_id={kakao_id} status={response.status_code}"
        )
