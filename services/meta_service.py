from sqlalchemy import select
from sqlalchemy.orm import Session

from models.consent_model import UserAllergy, UserCondition, UserHealthProfile
from models.meta_model import AllergenType, ConditionType


def list_condition_options(db: Session) -> list[ConditionType]:
    return list(
        db.scalars(
            select(ConditionType)
            .where(ConditionType.is_active.is_(True))
            .order_by(ConditionType.sort_order.asc())
        ).all()
    )


def list_allergen_options(db: Session) -> list[AllergenType]:
    return list(
        db.scalars(
            select(AllergenType)
            .where(AllergenType.is_active.is_(True))
            .order_by(AllergenType.sort_order.asc())
        ).all()
    )


def list_user_condition_types(db: Session, user_id: int) -> list[ConditionType]:
    return list(
        db.scalars(
            select(ConditionType)
            .join(UserCondition, UserCondition.condition == ConditionType.code)
            .where(UserCondition.user_id == user_id)
            .order_by(ConditionType.sort_order.asc())
        ).all()
    )


def get_user_ckd_stage(db: Session, user_id: int) -> str | None:
    """건강 프로필의 신장병 병기. 프로필 자체가 없으면 None — 없다고 조회가 실패하면 안 된다.

    질환 목록과 같이 판정 규칙이 읽는 사용자 메타라 여기 둔다. 예전엔 `day_nutrition`에 있어
    `nutrition_service`(경고)가 부를 수 없었고(순환 import), 그래서 경고·추천의 칼륨 등급이
    병기를 모른 채 투석 기준으로만 판정됐다(KCAL-15, 2026-09-13).
    """
    return db.scalar(
        select(UserHealthProfile.ckd_stage).where(UserHealthProfile.user_id == user_id)
    )


def list_user_allergen_types(db: Session, user_id: int) -> list[AllergenType]:
    return list(
        db.scalars(
            select(AllergenType)
            .join(UserAllergy, UserAllergy.allergen == AllergenType.code)
            .where(UserAllergy.user_id == user_id)
            .order_by(AllergenType.sort_order.asc())
        ).all()
    )


def match_exclude_keyword(name: str, keywords: list[str]) -> str | None:
    # 추천 후처리 필터와 기록 경고 판정이 같은 매칭 규칙(부분 문자열)을 쓴다 (11·16장).
    for keyword in keywords:
        if keyword in name:
            return keyword
    return None


def active_condition_codes(db: Session) -> set[str]:
    return set(
        db.scalars(
            select(ConditionType.code).where(ConditionType.is_active.is_(True))
        ).all()
    )


def active_allergen_codes(db: Session) -> set[str]:
    return set(
        db.scalars(
            select(AllergenType.code).where(AllergenType.is_active.is_(True))
        ).all()
    )
