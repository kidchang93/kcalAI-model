from datetime import datetime

from pydantic import BaseModel, Field


class KakaoLoginRequest(BaseModel):
    # 딥링크로 받은 1회용 연동 코드 (카카오 인가 코드가 아니다 — 그건 서버가 이미 소비했다).
    link_code: str = Field(..., min_length=16, max_length=128)


class KakaoSignupRequest(KakaoLoginRequest):
    # 가입 필수 동의. 기본값을 두지 않는다 — 앱이 보내지 않으면 422 로 막혀야 한다.
    agreed_terms: bool
    agreed_privacy: bool
    # 앱이 **화면에 실제로 그린 문서**의 버전. 서버가 현재 버전과 대조해 다르면 400 으로 막는다
    # (consent_service.ensure_current_version) — 앱이 옛 약관을 띄워 놓고 서버가 새 버전으로
    # 기록하면 동의 증빙이 거짓이 되기 때문이다.
    #
    # 선택 필드인 이유는 하위호환뿐이다. 이 필드를 보내지 않는 앱이 남아 있는 동안은 서버 상수로
    # 기록되는데, 그건 "앱이 무엇을 보여줬는지 모른 채 기록하는 것"이라 증빙으로 약하다.
    # 앱에 자리잡으면 필수로 좁힌다.
    terms_version: str | None = Field(default=None, max_length=20)
    privacy_version: str | None = Field(default=None, max_length=20)
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
