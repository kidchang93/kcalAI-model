from datetime import datetime

from pydantic import BaseModel, Field


class PhoneNumberRequest(BaseModel):
    phone_number: str = Field(..., min_length=8, max_length=30)


class VerifyPhoneCodeRequest(PhoneNumberRequest):
    code: str = Field(..., min_length=4, max_length=8)


class PhoneCodeResponse(BaseModel):
    message: str
    expires_at: datetime
    dev_code: str | None = None


class AuthUser(BaseModel):
    id: int
    phone_number: str
    is_phone_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUser


class AuthError(BaseModel):
    detail: str
