from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.health_model import FoodNutrition


class FoodNotFoundError(LookupError):
    """3단계 조회 전부 실패했을 때 던진다. api 가 404 로 변환한다 (DATA_MODEL.md 13장)."""


# pg_trgm similarity 하한. 실측(YOLO 721라벨 대조): 0.3 미만 구간은 오매칭이 다수
# (새우만두→새우탕, 계란말이→계란빵)라 초기값 0.3 을 유지한다 (13장).
SIMILARITY_THRESHOLD = 0.3

# LLM 추정(llm) 행은 반환하지 않는다 — 데이터셋 파이프라인은 실측·감수 값만 쓴다 (13장).
DATASET_SOURCES = ("mfds", "curated")

_NOT_FOUND_MESSAGE = "일치하는 음식을 찾지 못했습니다. 칼로리를 직접 입력해주세요."


def estimate_nutrition(db: Session, food_label: str) -> tuple[FoodNutrition, bool]:
    """식약처 DB 3단계 조회: 정확 일치 → 공백 제거 일치 → pg_trgm 유사도 최고 1건.

    반환 food_label 은 매칭된 DB 행의 이름이다 (요청 라벨과 다를 수 있음).
    cached 는 응답 계약 유지용 — LLM 을 태우지 않으므로 항상 True 다.
    """
    label = food_label.strip()

    exact = db.scalar(
        select(FoodNutrition).where(
            FoodNutrition.food_label == label,
            FoodNutrition.source.in_(DATASET_SOURCES),
        )
    )
    if exact is not None:
        return exact, True

    normalized = label.replace(" ", "")
    normalized_match = db.scalar(
        select(FoodNutrition)
        .where(
            func.replace(FoodNutrition.food_label, " ", "") == normalized,
            FoodNutrition.source.in_(DATASET_SOURCES),
        )
        .order_by(FoodNutrition.id.asc())
        .limit(1)
    )
    if normalized_match is not None:
        return normalized_match, True

    similarity = func.similarity(FoodNutrition.food_label, label)
    similar = db.scalar(
        select(FoodNutrition)
        .where(
            similarity >= SIMILARITY_THRESHOLD,
            FoodNutrition.source.in_(DATASET_SOURCES),
        )
        # 동률이면 id 로 tie-break — 같은 라벨은 항상 같은 행을 돌려준다.
        .order_by(similarity.desc(), FoodNutrition.id.asc())
        .limit(1)
    )
    if similar is not None:
        return similar, True

    raise FoodNotFoundError(_NOT_FOUND_MESSAGE)
