from datetime import datetime

from pydantic import BaseModel, Field


class SignupAgreementFields(BaseModel):
    """카카오·Apple 가입이 공유하는 동의·요금제 필드. 라우트 바디로 직접 쓰지 않는다."""

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


class KakaoLoginRequest(BaseModel):
    # 딥링크로 받은 1회용 연동 코드 (카카오 인가 코드가 아니다 — 그건 서버가 이미 소비했다).
    link_code: str = Field(..., min_length=16, max_length=128)


class KakaoSignupRequest(KakaoLoginRequest, SignupAgreementFields):
    pass


class AppleLoginRequest(BaseModel):
    # iOS 가 기기에서 받은 Apple identity token(JWT). 서버가 Apple 공개키로 서명을 검증한다.
    identity_token: str = Field(..., min_length=1, max_length=4096)


class AppleSignupRequest(AppleLoginRequest, SignupAgreementFields):
    # 1회용·5분. 서버가 refresh token 으로 바꿔 두어야 탈퇴 때 Apple 에 폐기를 요청할 수 있다.
    authorization_code: str = Field(..., min_length=1, max_length=512)
    # Apple 이 첫 로그인에만 주는 이름을 앱이 조합한 값. 비거나 공백이면 null 로 저장한다.
    # 이메일 필드는 두지 않는다 — 앱이 이메일 범위를 요청하지 않는다(최소 수집).
    nickname: str | None = Field(default=None, max_length=50)


class AuthUser(BaseModel):
    id: int
    # 카카오 닉네임 또는 Apple 이름. 카카오 프로필 동의 거부·Apple 이름 미제공이면 없다.
    nickname: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUser
