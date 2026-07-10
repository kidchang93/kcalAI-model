from sqlalchemy import select
from sqlalchemy.orm import Session

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
