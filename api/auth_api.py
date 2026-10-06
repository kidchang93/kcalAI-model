import os
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from api.dependencies import DB, CurrentUser, extract_bearer_token
from log_utils import get_logger
from models.auth_model import AuthSession, User
from schemas.auth_schema import (
    AppleLoginRequest,
    AppleSignupRequest,
    AuthTokenResponse,
    EmailCodeRequest,
    EmailLoginRequest,
    EmailNicknameRequest,
    EmailRequest,
    EmailSignupRequest,
    KakaoLoginRequest,
    KakaoSignupRequest,
    PasswordResetRequest,
)
from schemas.common_schema import ErrorResponse, MessageResponse
from services.apple_client import AppleUnavailableError
from services.auth_service import (
    EMAIL_RESET,
    EMAIL_SIGNUP,
    RateLimitError,
    StateError,
    apple_login,
    apple_signup,
    check_signup_nickname,
    create_link_code,
    create_state,
    email_login,
    email_signup,
    kakao_login,
    kakao_signup,
    platform_hint,
    request_email_code,
    reset_password,
    revoke_session_token,
    verify_signup_code,
    verify_state,
)
from services.mail_client import MailUnavailableError
from services.kakao_client import (
    KakaoAuthCodeError,
    KakaoError,
    build_authorize_url,
    exchange_code,
    fetch_profile,
)

logger = get_logger(__name__)

router = APIRouter()

# 콜백이 앱으로 되돌아가는 목적지. 카카오는 Redirect URI 에 커스텀 스킴을 등록할 수 없으므로,
# 카카오 → 서버(https) → 앱(딥링크) 2단으로 돌아온다.
APP_DEEPLINK_SCHEME = os.getenv("APP_DEEPLINK_SCHEME", "kcalairn")
# 웹 빌드는 FastAPI 가 같은 오리진에서 서빙하므로 딥링크가 아니라 경로로 돌려보낸다.
WEB_CALLBACK_PATH = "/auth"


@router.get("/auth/kakao/start")
def start_kakao_login(
    platform: str = Query(default="native", pattern="^(native|web)$"),
    switch_account: bool = Query(default=False),
):
    """카카오 인가 화면으로 보낸다. state 는 서명값이라 별도 저장소가 필요 없다.

    `switch_account=true` 면 카카오 세션이 있어도 로그인 화면을 다시 띄운다 — 그러지 않으면
    브라우저에 남은 카카오 세션 때문에 **항상 같은 계정으로만** 로그인된다.
    """
    return RedirectResponse(
        build_authorize_url(create_state(platform), force_login=switch_account),
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/auth/kakao/callback")
def kakao_callback(
    db: DB,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """카카오가 인가 코드를 들고 돌아오는 지점.

    브라우저(인앱 브라우저)가 여는 화면이라 **JSON 이 아니라 리다이렉트**로 답한다. 실패도
    딥링크에 error 를 실어 보낸다 — 사용자가 브라우저에 갇히면 안 된다.
    """
    # 에러 응답의 목적지는 **검증되지 않은** platform 힌트로 고른다 — state 가 깨졌을 때도
    # 사용자를 원래 왔던 곳(앱/웹)으로 돌려보내야 브라우저에 갇히지 않는다 (auth_service 주석).
    hinted_platform = platform_hint(state)

    # 사용자가 동의 화면에서 취소한 경우다 (에러가 아니라 정상 흐름).
    if error or not code or not state:
        return _redirect_to_app(hinted_platform, {"error": "cancelled"})

    try:
        platform = verify_state(state)
    except StateError as state_error:
        logger.error(f"kakao callback bad state: {state_error!r}")
        return _redirect_to_app(hinted_platform, {"error": "invalid_state"})

    try:
        access_token = exchange_code(code)
        kakao_id, nickname = fetch_profile(access_token)
    except KakaoAuthCodeError:
        return _redirect_to_app(platform, {"error": "expired"})
    except KakaoError as kakao_error:
        logger.error(f"kakao callback fail: {kakao_error!r}")
        return _redirect_to_app(platform, {"error": "kakao_unavailable"})

    # 앱이 다시 쓸 수 있는 1회용 코드로 바꿔 넘긴다 (카카오 인가 코드는 이미 소비됐다).
    link_code, is_new_user = create_link_code(db, kakao_id, nickname)

    return _redirect_to_app(
        platform,
        {"code": link_code, "is_new": "true" if is_new_user else "false"},
    )


def _redirect_to_app(platform: str, params: dict[str, str]) -> RedirectResponse:
    query = urlencode(params)
    target = (
        f"{WEB_CALLBACK_PATH}?{query}"
        if platform == "web"
        else f"{APP_DEEPLINK_SCHEME}://auth?{query}"
    )
    return RedirectResponse(target, status_code=status.HTTP_302_FOUND)


@router.post(
    "/auth/kakao/login",
    response_model=AuthTokenResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def login_with_kakao(request: KakaoLoginRequest, db: DB):
    # 미가입 카카오 계정은 404 — 앱은 404를 받으면 가입 화면(동의·요금제)으로 보낸다.
    return _token_response(*kakao_login(db, request.link_code))


@router.post(
    "/auth/kakao/signup",
    response_model=AuthTokenResponse,
    responses={400: {"model": ErrorResponse}},
)
def signup_with_kakao(request: KakaoSignupRequest, db: DB):
    return _token_response(
        *kakao_signup(
            db,
            request.link_code,
            request.agreed_terms,
            request.agreed_privacy,
            request.plan_code,
            request.terms_version,
            request.privacy_version,
        )
    )


# Apple: 400(토큰 무효·만료, 코드 교환 실패)·404(미가입)는 서비스 예외를 전역 핸들러가 바꾼다.
# 503 만 여기서 바꾼다 — Apple 공개키를 못 가져왔거나 SIWA 설정이 없다(문구는 서비스가 정한다).
@router.post(
    "/auth/apple/login",
    response_model=AuthTokenResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def login_with_apple(request: AppleLoginRequest, db: DB):
    # 미가입 Apple 계정은 404 — 앱은 약관 동의 단계로 보낸다 (카카오와 같다).
    try:
        return _token_response(*apple_login(db, request.identity_token))
    except AppleUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


@router.post(
    "/auth/apple/signup",
    response_model=AuthTokenResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def signup_with_apple(request: AppleSignupRequest, db: DB):
    try:
        return _token_response(*apple_signup(db, **request.model_dump()))
    except AppleUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


# 이메일: 400(형식·코드·비밀번호 규칙·로그인 실패)은 서비스 예외를 전역 핸들러가 바꾼다.
# 코드 요청만 429(재요청이 잦다)·503(메일을 못 보낸다)을 여기서 바꾼다.
_EMAIL_CODE_RESPONSES = {
    400: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}
# 가입 여부와 무관하게 같은 문구다(서비스 request_email_code 주석).
_EMAIL_CODE_SENT = "인증 메일을 보냈어요. 메일함을 확인해주세요."


@router.post("/auth/email/signup/code", response_model=MessageResponse, responses=_EMAIL_CODE_RESPONSES)
def send_signup_code(request: EmailRequest, db: DB):
    _send_email_code(db, request.email, EMAIL_SIGNUP)
    return {"message": _EMAIL_CODE_SENT}


@router.post(
    "/auth/email/signup/verify",
    response_model=MessageResponse,
    responses={400: {"model": ErrorResponse}},
)
def verify_email_signup_code(request: EmailCodeRequest, db: DB):
    verify_signup_code(db, request.email, request.code)
    return {"message": "이메일이 확인됐어요."}


@router.post(
    "/auth/email/signup/nickname",
    response_model=MessageResponse,
    responses={400: {"model": ErrorResponse}},
)
def check_email_signup_nickname(request: EmailNicknameRequest, db: DB):
    check_signup_nickname(db, request.email, request.code, request.nickname)
    return {"message": "쓸 수 있는 닉네임이에요."}


@router.post(
    "/auth/email/signup",
    response_model=AuthTokenResponse,
    responses={400: {"model": ErrorResponse}},
)
def signup_with_email(request: EmailSignupRequest, db: DB):
    return _token_response(*email_signup(db, **request.model_dump()))


@router.post(
    "/auth/email/login",
    response_model=AuthTokenResponse,
    responses={400: {"model": ErrorResponse}},
)
def login_with_email(request: EmailLoginRequest, db: DB):
    return _token_response(*email_login(db, request.email, request.password))


@router.post(
    "/auth/email/password-reset/code",
    response_model=MessageResponse,
    responses=_EMAIL_CODE_RESPONSES,
)
def send_password_reset_code(request: EmailRequest, db: DB):
    _send_email_code(db, request.email, EMAIL_RESET)
    return {"message": _EMAIL_CODE_SENT}


@router.post(
    "/auth/email/password-reset",
    response_model=MessageResponse,
    responses={400: {"model": ErrorResponse}},
)
def reset_email_password(request: PasswordResetRequest, db: DB):
    reset_password(db, request.email, request.code, request.new_password)
    return {"message": "비밀번호를 바꿨어요. 새 비밀번호로 로그인해주세요."}


def _send_email_code(db: DB, email: str, purpose: str) -> None:
    try:
        request_email_code(db, email, purpose)
    except RateLimitError as error:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error)) from error
    except MailUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


def _token_response(user: User, auth_session: AuthSession, raw_token: str) -> dict:
    # DB에는 토큰 해시만 저장되므로 원문(raw_token)은 이 응답에서만 나간다.
    return {"access_token": raw_token, "expires_at": auth_session.expires_at, "user": user}


@router.post(
    "/auth/logout",
    response_model=MessageResponse,
    responses={401: {"model": ErrorResponse}},
)
def logout(_current_user: CurrentUser, db: DB, authorization: str | None = Header(default=None)):
    # get_current_user 를 통과했으므로 토큰은 유효하다. 같은 토큰을 폐기한다.
    token = extract_bearer_token(authorization)
    if token is not None:
        revoke_session_token(db, token)

    return {"message": "로그아웃되었습니다."}
