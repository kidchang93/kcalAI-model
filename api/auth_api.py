from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.auth_schema import (
    AuthError,
    AuthTokenResponse,
    PhoneCodeResponse,
    PhoneNumberRequest,
    VerifyPhoneCodeRequest,
)
from services.auth_service import (
    create_login_code,
    create_signup_code,
    verify_login_code,
    verify_signup_code,
)

router = APIRouter()


@router.post(
    "/auth/signup/request-code",
    response_model=PhoneCodeResponse,
    responses={400: {"model": AuthError}},
)
def request_signup_code(request: PhoneNumberRequest, db: Session = Depends(get_db)):
    try:
        expires_at, dev_code = create_signup_code(db, request.phone_number)
        return {
            "message": "회원가입 인증번호를 발급했습니다.",
            "expires_at": expires_at,
            "dev_code": dev_code,
        }
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post(
    "/auth/signup/verify",
    response_model=AuthTokenResponse,
    responses={400: {"model": AuthError}},
)
def verify_signup(request: VerifyPhoneCodeRequest, db: Session = Depends(get_db)):
    try:
        user, auth_session = verify_signup_code(db, request.phone_number, request.code)
        return {
            "access_token": auth_session.token,
            "expires_at": auth_session.expires_at,
            "user": user,
        }
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post(
    "/auth/login/request-code",
    response_model=PhoneCodeResponse,
    responses={400: {"model": AuthError}},
)
def request_login_code(request: PhoneNumberRequest, db: Session = Depends(get_db)):
    try:
        expires_at, dev_code = create_login_code(db, request.phone_number)
        return {
            "message": "로그인 인증번호를 발급했습니다.",
            "expires_at": expires_at,
            "dev_code": dev_code,
        }
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post(
    "/auth/login/verify",
    response_model=AuthTokenResponse,
    responses={400: {"model": AuthError}},
)
def verify_login(request: VerifyPhoneCodeRequest, db: Session = Depends(get_db)):
    try:
        user, auth_session = verify_login_code(db, request.phone_number, request.code)
        return {
            "access_token": auth_session.token,
            "expires_at": auth_session.expires_at,
            "user": user,
        }
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
