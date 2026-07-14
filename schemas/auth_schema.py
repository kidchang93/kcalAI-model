from datetime import datetime

from pydantic import BaseModel, Field


class KakaoLoginRequest(BaseModel):
    # 딥링크로 받은 1회용 연동 코드 (카카오 인가 코드가 아니다 — 그건 서버가 이미 소비했다).
    link_code: str = Field(..., min_length=16, max_length=128)


class KakaoSignupRequest(KakaoLoginRequest):
    # 가입 필수 동의. 기본값을 두지 않는다 — 앱이 보내지 않으면 422 로 막혀야 한다.
    agreed_terms: bool
    agreed_privacy: bool
    # 미선택 시 무료 플랜(lite). 값 검증은 참조 테이블(plans) 조회로 한다.
    plan_code: str | None = None


class AuthUser(BaseModel):
    id: int
    # 카카오 닉네임. 프로필 동의를 거부하면 없을 수 있다.
    nickname: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUser


class LogoutResponse(BaseModel):
    message: str


class AuthError(BaseModel):
    detail: str
