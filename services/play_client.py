"""Google Play Developer API 어댑터 — 구독 구매 조회·확인(acknowledge)·주문 조회 (DATA_MODEL.md 33-3·33-4·35장).

앱이 보낸 `purchaseToken`, RTDN 이 실어 온 토큰은 **조회 키일 뿐이다.** 서버가 서비스 계정으로 받은 OAuth 토큰으로
Google 에 다시 물어보고 그 응답만 믿는다(29장 웹훅·32장 App Store 와 같은 규약).

서비스 계정 키·OAuth 토큰·구매 토큰은 로그에 남기지 않는다 — 실패는 예외 타입명과 HTTP 상태만, 구매 토큰은
앞 8자만 남긴다(`mask_token`).
"""

import base64
import json
import os
from functools import partial
from urllib.parse import quote

import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from log_utils import get_logger

logger = get_logger(__name__)

# 서비스 계정 JSON 을 base64 한 줄로 (apple_client 와 같은 이유 — 배포 rsync 가 키 파일을 지운다).
GOOGLE_PLAY_SERVICE_ACCOUNT_B64 = os.getenv("GOOGLE_PLAY_SERVICE_ACCOUNT_B64", "")
GOOGLE_PLAY_PACKAGE_NAME = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "com.kcalai.kcalairn")

SCOPE = "https://www.googleapis.com/auth/androidpublisher"
BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
PLAY_TIMEOUT_SECONDS = 10
# 몇 번을 물어도 같은 답이 나오는 응답 — 204 는 acknowledge 성공(본문 없음), 404·410 은 토큰 없음·만료가 오래됨이다.
# 그 밖은 판단하지 못한 것. (2026-10-15 실구매에서 acknowledge 가 204 를 줘 503 이 났다.)
SUCCESS_STATUSES = (200, 204)
DECIDED_STATUSES = (*SUCCESS_STATUSES, 404, 410)

UNAVAILABLE_MESSAGE = "구독 정보를 지금 확인할 수 없어요. 잠시 후 다시 시도해주세요."

# 서비스 계정 자격 증명은 프로세스마다 하나 — 액세스 토큰(1시간)을 만료 전까지 재사용한다.
_credentials: service_account.Credentials | None = None


class PlayUnavailableError(Exception):
    """키 미설정·네트워크 실패·Google 장애·권한 없음(401·403) — 아직 판단하지 못했다. api 가 503 으로 바꾼다.

    "구매가 없다"는 이게 아니라 조회 함수의 `None`·`False` 다 — 재시도해도 같은 답이다.
    """


def is_configured() -> bool:
    return bool(GOOGLE_PLAY_SERVICE_ACCOUNT_B64)


def mask_token(purchase_token: str | None) -> str:
    return f"{(purchase_token or '')[:8]}…"


def get_subscription(purchase_token: str) -> dict | None:
    """`purchases.subscriptionsv2.get` — SubscriptionPurchaseV2. 토큰이 없거나 너무 오래 만료됐으면(404·410) None."""
    status_code, body = _call(
        "GET",
        f"/{quote(GOOGLE_PLAY_PACKAGE_NAME, safe='')}/purchases/subscriptionsv2/tokens/"
        f"{quote(purchase_token, safe='')}",
    )

    if status_code != 200:
        logger.info(f"play subscription not found status={status_code} token={mask_token(purchase_token)}")
        return None

    return body


def acknowledge(product_id: str, purchase_token: str) -> bool:
    """`purchases.subscriptions.acknowledge` — 3일 안에 안 하면 Google 이 자동 환불한다. 토큰이 없으면(404·410) False."""
    status_code, _ = _call(
        "POST",
        f"/{quote(GOOGLE_PLAY_PACKAGE_NAME, safe='')}/purchases/subscriptions/{quote(product_id, safe='')}"
        f"/tokens/{quote(purchase_token, safe='')}:acknowledge",
    )

    if status_code not in SUCCESS_STATUSES:
        logger.info(f"play acknowledge not found status={status_code} token={mask_token(purchase_token)}")
        return False

    return True


def get_order(order_id: str) -> dict | None:
    """`orders.get` — 주문 1건(낸 금액·상태·환불 이력). 원장(35장)용. 없으면(404·410) None.

    서비스 계정에 Play Console '재무 데이터 보기' 권한이 있어야 한다 — 없으면 403 → PlayUnavailableError.
    """
    status_code, body = _call(
        "GET", f"/{quote(GOOGLE_PLAY_PACKAGE_NAME, safe='')}/orders/{quote(order_id, safe='')}"
    )

    if status_code != 200:
        logger.error(f"play order not found status={status_code}")
        return None

    return body


def _call(method: str, path: str) -> tuple[int, dict]:
    """200·204·404·410 은 (상태, 본문)으로 돌려준다. 그 밖(401·403 권한·429·5xx)과 네트워크 실패는 PlayUnavailableError."""
    access_token = _access_token()

    try:
        response = requests.request(
            method,
            f"{BASE_URL}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=PLAY_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        logger.error(f"play {method} request fail: {type(error).__name__}")
        # 원인 체인을 끊는다 — 상위가 트레이스백을 찍을 때 URL(구매 토큰)·헤더(OAuth 토큰)가 실릴 여지를 남기지 않는다.
        raise PlayUnavailableError(UNAVAILABLE_MESSAGE) from None

    if response.status_code in DECIDED_STATUSES:
        return response.status_code, _json(response)

    # 403 은 대개 Play Console 권한(재무 데이터 보기·주문 및 구독 관리)이 서비스 계정에 없을 때다 (33-5).
    logger.error(f"play {method} status={response.status_code}")
    raise PlayUnavailableError(UNAVAILABLE_MESSAGE)


def _access_token() -> str:
    """서비스 계정으로 받은 OAuth 액세스 토큰. 설정이 없거나 키가 깨졌거나 토큰 교환이 실패하면 503."""
    global _credentials

    if not is_configured():
        logger.error("play lookup skipped: GOOGLE_PLAY_SERVICE_ACCOUNT_B64 미설정")
        raise PlayUnavailableError(UNAVAILABLE_MESSAGE)

    try:
        if _credentials is None:
            info = json.loads(base64.b64decode(GOOGLE_PLAY_SERVICE_ACCOUNT_B64))
            _credentials = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])

        if not _credentials.valid:
            # google-auth 기본 타임아웃은 120초다 — Pub/Sub push 의 응답 기한을 넘기지 않게 줄인다.
            _credentials.refresh(partial(Request(), timeout=PLAY_TIMEOUT_SECONDS))
    except (ValueError, TypeError, KeyError, GoogleAuthError) as error:
        logger.error(f"play credentials fail: {type(error).__name__}")
        raise PlayUnavailableError(UNAVAILABLE_MESSAGE) from None

    return _credentials.token


def _json(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}

    return payload if isinstance(payload, dict) else {}
