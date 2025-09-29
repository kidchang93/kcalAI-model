from typing import List

from pydantic import BaseModel


class Prediction(BaseModel):
    label: str
    score: float

class PredictionResponse(BaseModel):
    predictions: List[Prediction]

class ErrorResponse(BaseModel):
    error: str