import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database import SessionLocal
from log_utils import setup_level_logger
from models.health_model import FoodNutrition
from services import meta_service
from services.food_synonyms import expand_variants
from services.gemini_nutrition_service import (
    NutritionEstimationError,
    NutritionEstimationUnavailable,
    estimate_by_label,
)


class FoodNotFoundError(LookupError):
    """데이터셋·llm 캐시·신규 추정이 모두 실패했을 때. api 가 404 로 변환한다 (19장)."""


# pg_trgm similarity 하한. 실측(YOLO 721라벨 대조): 0.3 미만 구간은 오매칭이 다수
# (새우만두→새우탕, 계란말이→계란빵)라 초기값 0.3 을 유지한다 (13장).
SIMILARITY_THRESHOLD = 0.3

# 실측·감수 데이터셋. 유사도 매칭까지 허용하는 1패스 대상이다 (13·14장).
DATASET_SOURCES = ("mfds", "curated", "mfds_processed", "mfds_raw")

# LLM 추정 행. 2패스에서 **정확·정규화 일치만** 허용한다 — 추정값에 유사도 매칭을 얹으면
# 추정 오차가 엉뚱한 라벨로 번진다("파에야" 추정값이 "파이"를 먹는 식) (19장).
LLM_SOURCE = "llm"

_NOT_FOUND_MESSAGE = "일치하는 음식을 찾지 못했습니다. 칼로리를 직접 입력해주세요."
_UNAVAILABLE_MESSAGE = "지금은 영양 정보를 계산할 수 없습니다. 잠시 후 다시 시도해주세요."

info_logger = setup_level_logger(logging.INFO)
error_logger = setup_level_logger(logging.ERROR)


class NutritionUnavailableError(RuntimeError):
    """추정 백엔드 장애. api 가 503 으로 변환한다 — 미매칭(404)과 구분한다 (19장)."""


def estimate_nutrition(db: Session, food_label: str) -> tuple[FoodNutrition, bool]:
    """영양 조회. 1패스 데이터셋 → 2패스 llm 캐시 → 실패 시 LLM 1회 추정·적재 (19장).

    조회 경로에 LLM 은 없다. 미등록 라벨만 **한 번** 추정해 food_nutrition(source='llm')
    으로 동결하고, 이후 같은 라벨은 그 행을 그대로 읽는다 — 같은 음식은 항상 같은 값이다.

    반환의 두 번째 값(cached)은 기존 행을 읽었으면 True, 이번에 새로 추정·적재했으면 False.
    """
    label = food_label.strip()

    dataset_row = _find_in_dataset(db, label)
    if dataset_row is not None:
        return dataset_row, True

    cached_row = _find_llm_cached(db, label)
    if cached_row is not None:
        return cached_row, True

    return _estimate_and_store(db, label), False


def prewarm_labels(food_labels: list[str]) -> None:
    """인식 후보 라벨들을 미리 조회·적재한다 — predict가 백그라운드로 호출한다 (19장).

    사용자는 후보 하나만 고르지만 나머지도 **버리기 아까운 인식 결과**다. 여기서 미리
    추정·적재해 두면 데이터가 쌓이고, 사용자가 어느 후보를 고르든 estimate가 캐시 히트한다.

    - 이미 데이터셋·llm 캐시에 있으면 **LLM을 타지 않는다** (대부분의 라벨이 여기서 끝난다).
    - 실패(음식 아님·게이트 탈락·Gemini 장애)는 **삼킨다** — 백그라운드라 사용자 응답에
      영향을 주면 안 되고, 적재 실패는 다음 요청에서 다시 시도되면 그만이다.
    - 요청 세션은 응답과 함께 닫히므로 **자체 세션**을 연다.
    """
    db = SessionLocal()
    try:
        for label in food_labels:
            clean = label.strip()
            if not clean:
                continue
            try:
                if _find_in_dataset(db, clean) is not None:
                    continue
                if _find_llm_cached(db, clean) is not None:
                    continue
                _estimate_and_store(db, clean)
            except (FoodNotFoundError, NutritionUnavailableError) as error:
                info_logger.info(f"prewarm skip label={clean} ({type(error).__name__})")
            except Exception as error:  # 백그라운드 작업이 요청을 깨뜨리면 안 된다.
                db.rollback()
                error_logger.error(f"prewarm 실패 label={clean}: {type(error).__name__}")
    finally:
        db.close()


def _find_in_dataset(db: Session, food_label: str) -> FoodNutrition | None:
    """식약처 DB 4단계 조회: 정확 → 공백 제거 → '_' 뒤 이름 정확 → pg_trgm 유사도.

    각 단계는 동의어 변형 후보 전체(expand_variants)를 대상으로 한다 —
    "계란찜"은 정확 일치 단계에서 이미 "달걀찜" 행을 찾는다.
    반환 food_label 은 매칭된 DB 행의 이름이다 (요청 라벨과 다를 수 있음).
    """
    variants = expand_variants(food_label)

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
            return exact

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
            return normalized_match

    # 2b단계: 식약처 라벨은 "카테고리_이름" 패턴이다("과ㆍ채주스_사과주스"). 접두어가
    # trgm 유사도를 깎아 짧은 라벨이 오폭하므로("토마토주스"→케첩), '_' 뒤 이름과의
    # 정확(공백 무시) 일치를 유사도보다 먼저 본다.
    for variant in variants:
        suffix_match = db.scalar(
            select(FoodNutrition)
            .where(
                func.replace(func.split_part(FoodNutrition.food_label, "_", -1), " ", "")
                == variant.replace(" ", ""),
                FoodNutrition.source.in_(DATASET_SOURCES),
            )
            .order_by(FoodNutrition.id.asc())
            .limit(1)
        )
        if suffix_match is not None:
            return suffix_match

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

    return best[1] if best is not None else None


def _find_llm_cached(db: Session, food_label: str) -> FoodNutrition | None:
    """이미 추정·동결해 둔 llm 행을 찾는다 — 정확 일치와 공백 무시 일치만 본다.

    유사도(trgm)를 쓰지 않는 것이 핵심이다. llm 행은 근사값이라, 유사도 매칭을 허용하면
    한 번 잘못 추정된 값이 이름이 비슷한 다른 음식들까지 오염시킨다 (19장).
    """
    variants = expand_variants(food_label)

    for variant in variants:
        exact = db.scalar(
            select(FoodNutrition)
            .where(
                FoodNutrition.food_label == variant,
                FoodNutrition.source == LLM_SOURCE,
            )
            .order_by(FoodNutrition.id.asc())
            .limit(1)
        )
        if exact is not None:
            return exact

    for variant in variants:
        normalized_match = db.scalar(
            select(FoodNutrition)
            .where(
                func.replace(FoodNutrition.food_label, " ", "") == variant.replace(" ", ""),
                FoodNutrition.source == LLM_SOURCE,
            )
            .order_by(FoodNutrition.id.asc())
            .limit(1)
        )
        if normalized_match is not None:
            return normalized_match

    return None


def _estimate_and_store(db: Session, food_label: str) -> FoodNutrition:
    """LLM 으로 1회 추정해 food_nutrition(source='llm')에 적재하고 그 행을 반환한다 (19장).

    적재는 ON CONFLICT DO NOTHING 이다 — 같은 라벨이 동시에 요청돼도 행은 하나만 남고,
    진 쪽은 이긴 쪽의 행을 그대로 읽는다(값이 갈라지지 않는다). 이미 실측(mfds 등) 행이
    있는 라벨도 충돌로 스킵되므로 실측값을 절대 덮지 않는다.
    """
    try:
        estimated = estimate_by_label(food_label)
    except NutritionEstimationError as error:
        # 음식이 아니거나 게이트 탈락 — DB에 남기지 않고 수동 입력으로 유도한다.
        raise FoodNotFoundError(_NOT_FOUND_MESSAGE) from error
    except NutritionEstimationUnavailable as error:
        raise NutritionUnavailableError(_UNAVAILABLE_MESSAGE) from error

    db.execute(
        insert(FoodNutrition)
        .values(
            food_label=food_label,
            kcal_per_serving=estimated.kcal_per_serving,
            serving_desc=estimated.serving_desc,
            carbs_g=estimated.carbs_g,
            protein_g=estimated.protein_g,
            fat_g=estimated.fat_g,
            # sugar/sodium/potassium/phosphorus 는 실측 전용 컬럼이라 비운다 (12장).
            # food_group 도 비운다 — 추천 후보 풀(source='mfds')에 llm 행은 들어가지 않는다.
            source=LLM_SOURCE,
        )
        .on_conflict_do_nothing(index_elements=["food_label"])
    )
    db.commit()

    stored = db.scalar(select(FoodNutrition).where(FoodNutrition.food_label == food_label))
    if stored is None:
        # 적재 직후 조회가 비는 건 정상 경로에 없다(충돌이어도 상대 행이 있어야 한다).
        raise FoodNotFoundError(_NOT_FOUND_MESSAGE)

    info_logger.info(
        f"nutrition estimate stored label={food_label} kcal={stored.kcal_per_serving} "
        f"source={stored.source}"
    )
    return stored


def get_record_warnings(db: Session, user_id: int, food_labels: list[str]) -> list[dict]:
    """기록 직전 알러지·질병 경고 판정 (DATA_MODEL.md 16장).

    사용자의 질병·알러지 참조 행의 exclude_keywords 를 각 라벨에 대조한다.
    매칭 규칙은 추천 후처리 필터와 공용이다 (meta_service.match_exclude_keyword).
    키워드 사전은 노출하지 않고 걸린 키워드 1개(matched_keyword)만 내려준다.
    """
    # 입력 순서를 보존하며 중복 라벨을 제거한다 (16장 — 서버 dedupe).
    labels = list(dict.fromkeys(food_labels))

    sources = (
        ("condition", meta_service.list_user_condition_types(db, user_id)),
        ("allergy", meta_service.list_user_allergen_types(db, user_id)),
    )

    warnings: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for source, rows in sources:
        for row in rows:
            for label in labels:
                matched = meta_service.match_exclude_keyword(label, row.exclude_keywords)
                if matched is None:
                    continue
                key = (source, row.code, label)
                if key in seen:
                    continue
                seen.add(key)
                warnings.append(
                    {
                        "source": source,
                        "code": row.code,
                        "label": row.label_ko,
                        "matched_keyword": matched,
                        "matched_label": label,
                    }
                )
    return warnings
