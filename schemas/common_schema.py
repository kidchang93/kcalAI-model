from pydantic import BaseModel


class ErrorResponse(BaseModel):
    # FastAPI 의 HTTPException 이 내보내는 형태와 일치시킨다.
    # 앱의 readErrorMessage 는 detail 키만 파싱한다.
    detail: str


class MessageResponse(BaseModel):
    message: str
