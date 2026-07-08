from pydantic import BaseModel


class GptAnswer(BaseModel):
    text: str
    max_tokens: int = 256

class GptResponse(BaseModel):
    response_text: str

class GptError(BaseModel):
    detail: str