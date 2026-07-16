import logging
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from api.dependencies import extract_bearer_token, get_current_user
from database import get_db
from log_utils import setup_level_logger
from models.auth_model import User
from schemas.auth_schema import (
    AuthError,
    AuthTokenResponse,
    KakaoLoginRequest,
    KakaoSignupRequest,
    LogoutResponse,
)
from services.auth_service import (
    StateError,
    create_link_code,
    create_state,
    kakao_login,
    kakao_signup,
    platform_hint,
    revoke_session_token,
    verify_state,
)
from services.kakao_client import (
    KakaoAuthCodeError,
    KakaoError,
    build_authorize_url,
    exchange_code,
    fetch_profile,
)

error_logger = setup_level_logger(logging.ERROR)

router = APIRouter()

# 콜백이 앱으로 되돌아가는 목적지. 카카오는 Redirect URI 에 커스텀 스킴을 등록할 수 없으므로,
# 카카오 → 서버(https) → 앱(딥링크) 2단으로 돌아온다.
APP_DEEPLINK_SCHEME = os.getenv("APP_DEEPLINK_SCHEME", "kcalairn")
# 웹 빌드는 FastAPI 가 같은 오리진에서 서빙하므로 딥링크가 아니라 경로로 돌려보낸다.
WEB_CALLBACK_PATH = os.getenv("WEB_CALLBACK_PATH", "/auth")


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
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
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
        error_logger.error(f"kakao callback bad state: {state_error!r}")
        return _redirect_to_app(hinted_platform, {"error": "invalid_state"})

    try:
        access_token = exchange_code(code)
        kakao_id, nickname = fetch_profile(access_token)
    except KakaoAuthCodeError:
        return _redirect_to_app(platform, {"error": "expired"})
    except KakaoError as kakao_error:
        error_logger.error(f"kakao callback fail: {kakao_error!r}")
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
    responses={400: {"model": AuthError}, 404: {"model": AuthError}},
)
def login_with_kakao(request: KakaoLoginRequest, db: Session = Depends(get_db)):
    try:
        # DB에는 토큰 해시만 저장되므로 원문(raw_token)은 이 응답에서만 나간다.
        user, auth_session, raw_token = kakao_login(db, request.link_code)
        return {
            "access_token": raw_token,
            "expires_at": auth_session.expires_at,
            "user": user,
        }
    except LookupError as lookup_error:
        # 미가입 카카오 계정 — 앱은 404를 받으면 가입 화면(동의·요금제)으로 보낸다.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(lookup_error)
        ) from lookup_error
    except ValueError as value_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(value_error)
        ) from value_error


@router.post(
    "/auth/kakao/signup",
    response_model=AuthTokenResponse,
    responses={400: {"model": AuthError}},
)
def signup_with_kakao(request: KakaoSignupRequest, db: Session = Depends(get_db)):
    try:
        user, auth_session, raw_token = kakao_signup(
            db,
            request.link_code,
            request.agreed_terms,
            request.agreed_privacy,
            request.plan_code,
            request.terms_version,
            request.privacy_version,
        )
        return {
            "access_token": raw_token,
            "expires_at": auth_session.expires_at,
            "user": user,
        }
    except ValueError as value_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(value_error)
        ) from value_error


@router.post(
    "/auth/logout",
    response_model=LogoutResponse,
    responses={401: {"model": AuthError}},
)
def logout(
    _current_user: User = Depends(get_current_user),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    # get_current_user 를 통과했으므로 토큰은 유효하다. 같은 토큰을 폐기한다.
    token = extract_bearer_token(authorization)
    if token is not None:
        revoke_session_token(db, token)

    return {"message": "로그아웃되었습니다."}
