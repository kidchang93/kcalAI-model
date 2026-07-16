"""토스 어댑터(`services/toss_client.py`) 회귀 — 핵심은 **비밀값이 로그로 새지 않는다**이다.

**토스 API 는 호출하지 않는다.** 연결 실패 경로는 닫힌 로컬 포트(127.0.0.1:9)로 만들고, 그 밖은
`requests.post` 를 monkeypatch 로 대체한다. 테스트 키라도 실호출은 결제사 트래픽이다
(`tests/test_billing_service.py` 와 같은 규약).

왜 이 파일이 필요한가: 빌링키는 토스 규격상 **URL 경로**에 실리고(`/v1/billing/{billingKey}`),
requests 의 연결 계열 예외는 메시지에 URL 을 통째로 담는다. 예외를 `{error!r}` 로 찍던 동안
빌링키가 평문으로 로그에 남았다 — DB 는 AES-256-GCM 으로 암호화해 두고 로그로 흘리면 그 암호화가
무의미해진다. 빌링키 하나면 그 회원 카드를 다시 긁을 수 있다.
(CLAUDE.md '절대 하지 말아야 할 것', DATA_MODEL.md 24장)
"""

import io
import logging

import pytest
import requests

from services import toss_client
from services.toss_client import TossError

# 로그에서 찾을 카나리아. 실제 빌링키 형태(bk_로 시작)를 흉내낸다.
CANARY_BILLING_KEY = "bk_LEAK_CANARY_0123456789"
CANARY_SECRET_KEY = "test_sk_LEAK_CANARY_SECRET"


@pytest.fixture
def toss_keys(monkeypatch):
    """`ensure_configured()` 를 통과시킨다. 실제 키가 아니라 카나리아다."""
    monkeypatch.setattr(toss_client, "TOSS_SECRET_KEY", CANARY_SECRET_KEY)
    monkeypatch.setattr(toss_client, "TOSS_CLIENT_KEY", "test_ck_fake")


@pytest.fixture
def error_log():
    """`error_logger` 에 나가는 줄을 캡처한다.

    `setup_level_logger` 가 만든 로거는 파일·콘솔 핸들러를 직접 달고 있어, 핸들러를 하나 더
    붙이는 쪽이 propagate 설정에 기대는 것보다 확실하다.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.ERROR)
    toss_client.error_logger.addHandler(handler)

    try:
        yield stream
    finally:
        toss_client.error_logger.removeHandler(handler)


def _charge_canary():
    return toss_client.charge_billing(
        CANARY_BILLING_KEY, "cust_test", 5000, "order_test", "Pro 요금제"
    )


# ---- 연결 실패 (실제 requests 예외) ----

def test_connection_failure_does_not_leak_billing_key(toss_keys, error_log, monkeypatch):
    """닫힌 포트로 실제 연결 실패를 만든다 — requests 가 실제로 무엇을 메시지에 담는지 검증한다.

    가짜 예외를 던지는 monkeypatch 로는 "requests 가 URL 을 담는다"는 전제 자체를 검증할 수 없다.
    """
    monkeypatch.setattr(toss_client, "CHARGE_BILLING_URL", "https://127.0.0.1:9/v1/billing")

    with pytest.raises(TossError) as caught:
        _charge_canary()

    logged = error_log.getvalue()

    assert CANARY_BILLING_KEY not in logged, f"빌링키가 로그에 샜다: {logged}"
    assert CANARY_SECRET_KEY not in logged
    # 진단은 남아야 한다 — 어느 호출이 어떤 범주로 실패했는지.
    assert "charge billing" in logged
    assert "ConnectionError" in logged
    # 사용자에게 가는 메시지에도 비밀값이 없다.
    assert CANARY_BILLING_KEY not in caught.value.message


def test_toss_error_does_not_chain_original_exception(toss_keys, monkeypatch):
    """원인 체인을 남기면 상위가 트레이스백을 찍는 순간 같은 URL 이 그 경로로 샌다.

    그래서 `raise ... from None` 으로 끊는다. 로깅만 고치면 `logger.exception` 하나가 추가되는
    날 되살아나는 종류의 유출이다.
    """
    monkeypatch.setattr(toss_client, "CHARGE_BILLING_URL", "https://127.0.0.1:9/v1/billing")

    with pytest.raises(TossError) as caught:
        _charge_canary()

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None or caught.value.__suppress_context__


def test_any_request_exception_message_is_not_logged(toss_keys, error_log, monkeypatch):
    """예외 메시지에 무엇이 들어 있든 로그로 옮기지 않는다 (타입 이름만 남긴다).

    requests 가 메시지를 만드는 방식이 바뀌어도(urllib3 업그레이드 등) 유출이 없어야 한다.
    """

    def _raise_with_url(*args, **kwargs):
        raise requests.exceptions.ConnectionError(
            f"HTTPSConnectionPool: Max retries exceeded with url: /v1/billing/{CANARY_BILLING_KEY}"
        )

    monkeypatch.setattr(requests, "post", _raise_with_url)

    with pytest.raises(TossError):
        _charge_canary()

    assert CANARY_BILLING_KEY not in error_log.getvalue()


# ---- 결제사 4xx 응답 ----

class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload

        return self._payload


def test_error_response_logs_code_not_billing_key(toss_keys, error_log, monkeypatch):
    """4xx 는 결제사 **코드**만 남긴다. 원문 메시지는 남기되 URL·빌링키는 남지 않는다."""
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: _FakeResponse(400, {"code": "REJECT_CARD_COMPANY", "message": "거절"}),
    )

    with pytest.raises(TossError) as caught:
        _charge_canary()

    logged = error_log.getvalue()

    assert CANARY_BILLING_KEY not in logged
    assert "code=REJECT_CARD_COMPANY" in logged
    # 사용자에게는 우리가 통제하는 한국어 문구가 간다 (토스 원문 '거절'이 아니다).
    assert caught.value.message == "카드사에서 결제를 거절했습니다. 카드사에 문의해주세요."
    assert caught.value.code == "REJECT_CARD_COMPANY"


def test_unknown_fail_code_falls_back_to_default_message(toss_keys, monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: _FakeResponse(400, {"code": "SOME_NEW_CODE_WE_DO_NOT_KNOW", "message": "x"}),
    )

    with pytest.raises(TossError) as caught:
        _charge_canary()

    assert caught.value.message == "결제에 실패했습니다. 잠시 후 다시 시도해주세요."
    # 코드는 원장(payments.fail_code)에 남겨야 하므로 보존한다.
    assert caught.value.code == "SOME_NEW_CODE_WE_DO_NOT_KNOW"


def test_non_json_response_does_not_leak(toss_keys, error_log, monkeypatch):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: _FakeResponse(200, ValueError("not json"))
    )

    with pytest.raises(TossError):
        _charge_canary()

    assert CANARY_BILLING_KEY not in error_log.getvalue()


# ---- 인증 헤더 규격 ----

def test_auth_header_is_basic_base64_secret_colon(toss_keys):
    """토스 규격: base64("{시크릿}:") — 비밀번호 없는 Basic 이라 콜론까지만 인코딩한다."""
    import base64

    header = toss_client._auth_header()

    assert header.startswith("Basic ")
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode("utf-8")
    assert decoded == f"{CANARY_SECRET_KEY}:"


def test_ensure_configured_raises_when_key_missing(monkeypatch):
    monkeypatch.setattr(toss_client, "TOSS_SECRET_KEY", "")
    monkeypatch.setattr(toss_client, "TOSS_CLIENT_KEY", "")

    with pytest.raises(toss_client.TossNotConfiguredError):
        toss_client.ensure_configured()
