from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.health_model import FoodNutrition
from services.food_synonyms import expand_variants


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

    각 단계는 동의어 변형 후보 전체(expand_variants)를 대상으로 한다 —
    "계란찜"은 정확 일치 단계에서 이미 "달걀찜" 행을 찾는다.
    반환 food_label 은 매칭된 DB 행의 이름이다 (요청 라벨과 다를 수 있음).
    cached 는 응답 계약 유지용 — LLM 을 태우지 않으므로 항상 True 다.
    """
    variants = expand_variants(food_label.strip())

    # 1·2단계: 변형 후보를 순서대로 — 원 라벨이 항상 우선한다.
    for variant in variants:
        exact = db.scalar(
            select(FoodNutrition)
            .where(
                FoodNutrition.food_label == variant,
                FoodNutrition.source.in_(DATASET_SOURCES),
            )
            .order_by(FoodNutrition.id.asc())
            .limit(1)
        )
        if exact is not None:
            return exact, True

    for variant in variants:
        normalized_match = db.scalar(
            select(FoodNutrition)
            .where(
                func.replace(FoodNutrition.food_label, " ", "") == variant.replace(" ", ""),
                FoodNutrition.source.in_(DATASET_SOURCES),
            )
            .order_by(FoodNutrition.id.asc())
            .limit(1)
        )
        if normalized_match is not None:
            return normalized_match, True

    # 3단계: 변형 후보 전체에서 유사도 최고 1건. 변형 내부는 쿼리가 낮은 id 를,
    # 변형 간 동률은 앞선 변형을 우선한다 — 같은 라벨은 항상 같은 행 (결정성, 13장).
    best: tuple[float, FoodNutrition] | None = None
    for variant in variants:
        similarity = func.similarity(FoodNutrition.food_label, variant)
        similar = db.execute(
            select(FoodNutrition, similarity)
            .where(
                similarity >= SIMILARITY_THRESHOLD,
                FoodNutrition.source.in_(DATASET_SOURCES),
            )
            .order_by(similarity.desc(), FoodNutrition.id.asc())
            .limit(1)
        ).first()
        if similar is None:
            continue

        row, score = similar[0], float(similar[1])
        if best is None or score > best[0]:
            best = (score, row)

    if best is not None:
        return best[1], True

    raise FoodNotFoundError(_NOT_FOUND_MESSAGE)
