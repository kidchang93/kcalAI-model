from datetime import datetime

from timeutil import UTC

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.consent_model import UserAllergy, UserCondition, UserConsent, UserHealthProfile
from services import meta_service

SENSITIVE_HEALTH = "sensitive_health"
TERMS = "terms"
PRIVACY = "privacy"

# 각 동의의 **현재 버전**. 문서 문구를 고치면 여기를 올린다 — 기존 회원의 동의 행은 옛 버전으로
# 남아, 누가 무엇에 동의했는지가 증빙된다.
#
# ⚠️ 앱의 문서와 **함께** 올려야 한다. 앱이 화면에 그리는 문서가 정본이고(k-calAI-RN 의
# `constants/legal.ts` = 약관·처리방침, `constants/consent.ts` = 민감정보 동의), 여기 값은 그
# 문서의 버전과 일치해야 한다. 어긋나면 `ensure_current_version` 이 400 으로 막는다.
#
# 포맷이 kind 마다 다르다(terms·privacy 는 "1.0", sensitive_health 는 "v1.0"). 기존 데이터가
# 그렇게 쌓여 있어 통일하려면 마이그레이션이 필요하다 — 검증은 kind 별 비교라 지장이 없다.
TERMS_VERSION = "1.0"
PRIVACY_VERSION = "1.0"
SENSITIVE_HEALTH_VERSION = "v1.0"

_CURRENT_VERSIONS = {
    TERMS: TERMS_VERSION,
    PRIVACY: PRIVACY_VERSION,
    SENSITIVE_HEALTH: SENSITIVE_HEALTH_VERSION,
}

# 앱이 옛 문서를 보여주고 있을 때의 사용자 메시지. 앱을 최신으로 올리면 해소된다.
_STALE_VERSION_MESSAGE = "약관이 변경되었습니다. 앱을 최신 버전으로 업데이트한 뒤 다시 시도해주세요."


def ensure_current_version(kind: str, version: str) -> None:
    """앱이 **실제로 보여준 문서**의 버전이 현재 버전인지 확인한다.

    동의 이력의 존재 이유는 "누가 무엇에 동의했는지"의 증빙이다. 그런데 앱이 화면에 v1.0 을
    띄워 놓고 서버가 "2.0 에 동의함"으로 기록하면 그 증빙은 거짓이 된다 — 문서를 개정한 뒤
    구버전 앱이 남아 있으면 정확히 그 일이 벌어진다. 그래서 앱이 보낸 버전을 받아 현재 버전과
    **대조**하고, 다르면 기록하지 않고 막는다(400 → 앱 업데이트 유도).

    모르는 kind 는 통과시킨다 — 동의 종류가 늘 때 서버만 먼저 배포돼도 깨지지 않아야 한다.
    """
    current = _CURRENT_VERSIONS.get(kind)

    if current is not None and version != current:
        raise ValueError(_STALE_VERSION_MESSAGE)


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
    # 앱이 보여준 문서가 현재 것인지 먼저 확인한다 (api 레이어가 ValueError → 400).
    ensure_current_version(kind, version)
    # 재동의도 항상 새 행이다 (이력 보존). 기존 행을 갱신하지 않는다.
    consent = UserConsent(user_id=user_id, kind=kind, version=version)
    db.add(consent)
    db.commit()
    db.refresh(consent)
    return consent


def record_signup_consents(
    db: Session, user_id: int, terms_version: str | None = None, privacy_version: str | None = None
) -> None:
    """가입 필수 동의(이용약관·개인정보 처리방침)를 기록한다.

    `*_version` 은 **앱이 화면에 실제로 그린 문서의 버전**이다. 받으면 현재 버전과 대조하고
    (다르면 ValueError → 400), 그 값을 그대로 기록한다.

    None 은 버전을 보내지 않는 구버전 앱이다. 이때는 서버 상수로 기록한다 — 하위호환을 위한
    폴백이며, 앱이 무엇을 보여줬는지 알 수 없으므로 **증빙으로서는 약하다**. 두 필드가 앱에
    자리잡으면 필수로 좁히는 것이 맞다.

    가입 트랜잭션 안에서 불리므로 commit 하지 않는다 (호출자가 커밋한다) — 동의 없이 회원
    행만 남는 상태가 생기면 안 된다.
    """
    if terms_version is not None:
        ensure_current_version(TERMS, terms_version)

    if privacy_version is not None:
        ensure_current_version(PRIVACY, privacy_version)

    db.add(UserConsent(user_id=user_id, kind=TERMS, version=terms_version or TERMS_VERSION))
    db.add(UserConsent(user_id=user_id, kind=PRIVACY, version=privacy_version or PRIVACY_VERSION))
    db.flush()


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
    # 코드 검증은 Literal 이 아니라 참조 테이블 조회로 한다 (DATA_MODEL.md 10장).
    valid_codes = meta_service.active_condition_codes(db)
    invalid = [code for code in dict.fromkeys(conditions) if code not in valid_codes]
    if invalid:
        raise ValueError(f"선택할 수 없는 질병 코드입니다: {', '.join(invalid)}")

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
    # 코드 검증은 Literal 이 아니라 참조 테이블 조회로 한다 (DATA_MODEL.md 10장).
    valid_codes = meta_service.active_allergen_codes(db)
    invalid = [
        allergen
        for allergen in dict.fromkeys(allergy["allergen"] for allergy in allergies)
        if allergen not in valid_codes
    ]
    if invalid:
        raise ValueError(f"선택할 수 없는 알러지 코드입니다: {', '.join(invalid)}")

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
