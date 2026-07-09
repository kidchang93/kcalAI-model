from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.consent_model import UserAllergy, UserCondition, UserConsent, UserHealthProfile

SENSITIVE_HEALTH = "sensitive_health"


# ---- 동의 ----

def list_consents(db: Session, user_id: int) -> list[UserConsent]:
    return list(
        db.scalars(
            select(UserConsent)
            .where(UserConsent.user_id == user_id)
            .order_by(UserConsent.agreed_at.desc(), UserConsent.id.desc())
        ).all()
    )


def create_consent(db: Session, user_id: int, kind: str, version: str) -> UserConsent:
    # 재동의도 항상 새 행이다 (이력 보존). 기존 행을 갱신하지 않는다.
    consent = UserConsent(user_id=user_id, kind=kind, version=version)
    db.add(consent)
    db.commit()
    db.refresh(consent)
    return consent


def has_active_consent(db: Session, user_id: int, kind: str = SENSITIVE_HEALTH) -> bool:
    # 동의 유효 = 해당 kind 의 최신 행이 존재하고 revoked_at IS NULL.
    latest = db.scalar(
        select(UserConsent)
        .where(UserConsent.user_id == user_id, UserConsent.kind == kind)
        .order_by(UserConsent.agreed_at.desc(), UserConsent.id.desc())
        .limit(1)
    )
    return latest is not None and latest.revoked_at is None


def revoke_consent(db: Session, user_id: int, kind: str) -> UserConsent:
    latest = db.scalar(
        select(UserConsent)
        .where(UserConsent.user_id == user_id, UserConsent.kind == kind)
        .order_by(UserConsent.agreed_at.desc(), UserConsent.id.desc())
        .limit(1)
    )

    if latest is None or latest.revoked_at is not None:
        raise LookupError("철회할 동의 내역이 없습니다.")

    # 동의 행은 삭제하지 않고 revoked_at 만 채워 증빙으로 남긴다.
    latest.revoked_at = datetime.now(UTC)

    if kind == SENSITIVE_HEALTH:
        _destroy_sensitive_data(db, user_id)

    db.commit()
    db.refresh(latest)
    return latest


def _destroy_sensitive_data(db: Session, user_id: int) -> None:
    # 민감정보는 soft delete 가 아니라 물리 삭제(파기)다. DATA_MODEL.md 7장 파기 규칙.
    db.execute(delete(UserHealthProfile).where(UserHealthProfile.user_id == user_id))
    db.execute(delete(UserCondition).where(UserCondition.user_id == user_id))
    db.execute(delete(UserAllergy).where(UserAllergy.user_id == user_id))


# ---- 건강 프로필 (혈액형·Rh) ----

def get_health_profile(db: Session, user_id: int) -> UserHealthProfile:
    profile = db.scalar(select(UserHealthProfile).where(UserHealthProfile.user_id == user_id))
    if profile is None:
        raise ValueError("등록된 건강 정보가 없습니다. 혈액형 정보를 먼저 등록해주세요.")
    return profile


def upsert_health_profile(
    db: Session,
    user_id: int,
    blood_type: str | None,
    rh: str | None,
) -> UserHealthProfile:
    profile = db.scalar(select(UserHealthProfile).where(UserHealthProfile.user_id == user_id))

    if profile is None:
        profile = UserHealthProfile(user_id=user_id)
        db.add(profile)

    profile.blood_type = blood_type
    profile.rh = rh

    db.commit()
    db.refresh(profile)
    return profile


# ---- 질병 ----

def list_conditions(db: Session, user_id: int) -> list[str]:
    return list(
        db.scalars(
            select(UserCondition.condition)
            .where(UserCondition.user_id == user_id)
            .order_by(UserCondition.id.asc())
        ).all()
    )


def replace_conditions(db: Session, user_id: int, conditions: list[str]) -> list[str]:
    # replace-all. 빈 배열이면 전체 삭제로 끝난다.
    db.execute(delete(UserCondition).where(UserCondition.user_id == user_id))

    # 중복 입력은 (user_id, condition) unique 위반이므로 순서를 보존하며 제거한다.
    for condition in dict.fromkeys(conditions):
        db.add(UserCondition(user_id=user_id, condition=condition))

    db.commit()
    return list_conditions(db, user_id)


# ---- 알러지 ----

def list_allergies(db: Session, user_id: int) -> list[UserAllergy]:
    return list(
        db.scalars(
            select(UserAllergy)
            .where(UserAllergy.user_id == user_id)
            .order_by(UserAllergy.id.asc())
        ).all()
    )


def replace_allergies(db: Session, user_id: int, allergies: list[dict]) -> list[UserAllergy]:
    # replace-all. 빈 배열이면 전체 삭제로 끝난다.
    db.execute(delete(UserAllergy).where(UserAllergy.user_id == user_id))

    # 같은 allergen 이 중복 입력되면 마지막 severity 가 이긴다 ((user_id, allergen) unique).
    deduped: dict[str, str | None] = {}
    for allergy in allergies:
        deduped[allergy["allergen"]] = allergy.get("severity")

    for allergen, severity in deduped.items():
        db.add(UserAllergy(user_id=user_id, allergen=allergen, severity=severity))

    db.commit()
    return list_allergies(db, user_id)
