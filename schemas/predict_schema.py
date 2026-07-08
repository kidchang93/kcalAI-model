from typing import List

from pydantic import BaseModel


class Prediction(BaseModel):
    label: str
    score: float

class PredictionResponse(BaseModel):
    predictions: List[Prediction]

class ErrorResponse(BaseModel):
    # FastAPI 의 HTTPException 이 내보내는 형태와 일치시킨다.
    # 앱의 readErrorMessage 는 detail 키만 파싱한다.
    detail: str