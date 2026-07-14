from typing import List

from pydantic import BaseModel


class Prediction(BaseModel):
    label: str
    score: float

class PredictionResponse(BaseModel):
    predictions: List[Prediction]
    # 이번 호출까지 반영한 오늘 사용량. 앱이 "오늘 2/3건" 을 별도 조회 없이 보여준다.
    vision_used: int
    vision_limit: int

class ErrorResponse(BaseModel):
    # FastAPI 의 HTTPException 이 내보내는 형태와 일치시킨다.
    # 앱의 readErrorMessage 는 detail 키만 파싱한다.
    detail: str