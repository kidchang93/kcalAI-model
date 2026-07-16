from pydantic import BaseModel


class DetectedFood(BaseModel):
    # 사진에서 인식된 하나의 음식. 한 사진에 밥·국·반찬이 있으면 각각 별도 항목이다.
    label: str
    score: float
    # 1인분 추정 무게(g). Gemini 가 모르면 null.
    portion_g: int | None = None


class PredictionResponse(BaseModel):
    # 그 사진에서 인식된 서로 다른 음식들. 한 음식의 후보 나열이 아니다.
    foods: list[DetectedFood]
    # 이번 호출까지 반영한 오늘 사용량. 앱이 "오늘 2/5건" 을 별도 조회 없이 보여준다.
    # 쿼터는 사진(호출)당 1건 — foods 개수와 무관하다.
    vision_used: int
    vision_limit: int


class ErrorResponse(BaseModel):
    # FastAPI 의 HTTPException 이 내보내는 형태와 일치시킨다.
    # 앱의 readErrorMessage 는 detail 키만 파싱한다.
    detail: str
