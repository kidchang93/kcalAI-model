from pydantic import BaseModel


class AccountDeleteResponse(BaseModel):
    message: str


class AccountError(BaseModel):
    detail: str
