from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import extract_bearer_token, get_current_user
from database import get_db
from models.auth_model import User
from schemas.auth_schema import (
    AuthError,
    AuthTokenResponse,
    LogoutResponse,
    PhoneCodeResponse,
    PhoneNumberRequest,
    VerifyPhoneCodeRequest,
)
from services.auth_service import (
    RateLimitError,
    create_login_code,
    create_signup_code,
    revoke_session_token,
    verify_login_code,
    verify_signup_code,
)

router = APIRouter()


@router.post(
    "/auth/signup/request-code",
    response_model=PhoneCodeResponse,
    responses={400: {"model": AuthError}, 429: {"model": AuthError}},
)
def request_signup_code(request: PhoneNumberRequest, db: Session = Depends(get_db)):
    try:
        expires_at, dev_code = create_signup_code(db, request.phone_number)
        return {
            "message": "회원가입 인증번호를 발급했습니다.",
            "expires_at": expires_at,
            "dev_code": dev_code,
        }
    except RateLimitError as error:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post(
    "/auth/signup/verify",
    response_model=AuthTokenResponse,
    responses={400: {"model": AuthError}},
)
def verify_signup(request: VerifyPhoneCodeRequest, db: Session = Depends(get_db)):
    try:
        # DB에는 토큰 해시만 저장되므로 원문(raw_token)은 이 응답에서만 나간다.
        user, auth_session, raw_token = verify_signup_code(db, request.phone_number, request.code)
        return {
            "access_token": raw_token,
            "expires_at": auth_session.expires_at,
            "user": user,
        }
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


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


@router.post(
    "/auth/login/request-code",
    response_model=PhoneCodeResponse,
    responses={400: {"model": AuthError}, 429: {"model": AuthError}},
)
def request_login_code(request: PhoneNumberRequest, db: Session = Depends(get_db)):
    try:
        expires_at, dev_code = create_login_code(db, request.phone_number)
        return {
            "message": "로그인 인증번호를 발급했습니다.",
            "expires_at": expires_at,
            "dev_code": dev_code,
        }
    except RateLimitError as error:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post(
    "/auth/login/verify",
    response_model=AuthTokenResponse,
    responses={400: {"model": AuthError}},
)
def verify_login(request: VerifyPhoneCodeRequest, db: Session = Depends(get_db)):
    try:
        # DB에는 토큰 해시만 저장되므로 원문(raw_token)은 이 응답에서만 나간다.
        user, auth_session, raw_token = verify_login_code(db, request.phone_number, request.code)
        return {
            "access_token": raw_token,
            "expires_at": auth_session.expires_at,
            "user": user,
        }
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
