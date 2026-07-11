from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.health_model import FoodNutrition
from services import meta_service
from services.food_synonyms import expand_variants


class FoodNotFoundError(LookupError):
    """3단계 조회 전부 실패했을 때 던진다. api 가 404 로 변환한다 (DATA_MODEL.md 13장)."""


# pg_trgm similarity 하한. 실측(YOLO 721라벨 대조): 0.3 미만 구간은 오매칭이 다수
# (새우만두→새우탕, 계란말이→계란빵)라 초기값 0.3 을 유지한다 (13장).
SIMILARITY_THRESHOLD = 0.3

# LLM 추정(llm) 행은 반환하지 않는다 — 데이터셋 파이프라인은 실측·감수 값만 쓴다 (13장).
# mfds_processed(가공식품 집계)·mfds_raw(원재료성 집계)는 estimate 조회 전용이다 (14장).
DATASET_SOURCES = ("mfds", "curated", "mfds_processed", "mfds_raw")

_NOT_FOUND_MESSAGE = "일치하는 음식을 찾지 못했습니다. 칼로리를 직접 입력해주세요."


def estimate_nutrition(db: Session, food_label: str) -> tuple[FoodNutrition, bool]:
    """식약처 DB 4단계 조회: 정확 → 공백 제거 → '_' 뒤 이름 정확 → pg_trgm 유사도.

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
            return suffix_match, True

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
