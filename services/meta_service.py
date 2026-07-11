from sqlalchemy import select
from sqlalchemy.orm import Session

from models.consent_model import UserAllergy, UserCondition
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
