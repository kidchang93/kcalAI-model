from datetime import datetime
from enum import Enum

from timeutil import UTC

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from models.consent_model import UserAllergy, UserCondition, UserConsent, UserHealthProfile
from models.health_model import CareVisit, LabResult
from models.recommendation_model import DietRecommendation
from services import meta_service
from services.errors import BadRequestError, ForbiddenError, NotFoundError

SENSITIVE_HEALTH = "sensitive_health"
TERMS = "terms"
PRIVACY = "privacy"
# 그룹 챌린지에서 내 활동량·순위를 **같은 그룹 멤버에게** 보이는 것에 대한 동의.
# sensitive_health(우리가 건강정보를 수집·이용)와 별개다 — 이건 **제3자 노출**이라 따로 받아야 한다.
# 이 동의가 없으면 챌린지 순위에 나타나지 않는다(챌린지 자체는 볼 수 있다).
GROUP_ACTIVITY_SHARE = "group_activity_share"

# 각 동의의 **현재 버전**. 문서 문구를 고치면 여기를 올린다 — 기존 회원의 동의 행은 옛 버전으로
# 남아, 누가 무엇에 동의했는지가 증빙된다.
#
# ⚠️ 앱의 문서와 **함께** 올려야 한다. 앱이 화면에 그리는 문서가 정본이고(k-calAI-RN 의
# `constants/legal.ts` = 약관·처리방침, `constants/consent.ts` = 민감정보 동의), 여기 값은 그
# 문서의 버전과 일치해야 한다. 어긋나면 `ensure_current_version` 이 400 으로 막는다.
#
# 포맷이 kind 마다 다르다(terms·privacy 는 "1.0", sensitive_health 는 "v1.0"). 기존 데이터가
# 그렇게 쌓여 있어 통일하려면 마이그레이션이 필요하다 — 검증은 kind 별 비교라 지장이 없다.
#
# 2026-09-13 (KCAL-22): terms·privacy 1.0 → 1.1(생성형 AI 사전고지, AI기본법 제31조①),
# sensitive_health v1.0 → v1.1(검사 수치·진료 메모 항목과 경고·조언·리포트 목적 추가).
# ⚠️ sensitive_health 를 올릴 때 **범위가 넓어졌다면** 옛 버전을 SENSITIVE_HEALTH_REVALIDATE_VERSIONS
# 에 넣어야 한다 — 그래야 재동의 전까지 무효가 된다. 넓어지지 않았다면 넣지 않는다.
TERMS_VERSION = "1.1"
PRIVACY_VERSION = "1.1"
SENSITIVE_HEALTH_VERSION = "v1.1"
GROUP_ACTIVITY_SHARE_VERSION = "v1.0"

# **재동의를 강제하는 옛 민감정보 동의 버전.** 여기 있는 버전에 머문 동의만 무효(403)다.
#
# 2026-09-16까지는 "현재 버전이 아니면 전부 무효"였다. 그러면 문구를 한 글자만 고쳐도 — 사실과
# 다른 문장을 바로잡거나 어려운 말을 쉽게 푸는 개정에도 — 기존 동의자 **전원**의 질환 기능이
# 다시 동의할 때까지 멈춘다. 개인정보 보호법 제23조가 막는 것은 "알린 범위를 벗어난 처리"이지
# 문구 개정 자체가 아니다. 그래서 개정을 두 갈래로 나눈다:
#
#   ① 수집 항목·이용 목적이 **넓어지는** 개정  → 이 집합에 옛 버전을 넣는다. 재동의 전까지 403.
#      (예: v1.0 → v1.1 은 검사 수치·진료 메모를 항목에, 경고·조언·리포트를 목적에 더했다)
#   ② 범위가 그대로이거나 **좁아지는** 개정   → 넣지 않는다. 기능은 계속 동작하고,
#      `is_current: false` 로 앱이 "내용이 바뀌었어요"만 알린다.
#
# ⚠️ 판단 기준은 문구가 바뀌었는지가 아니라 **범위가 넓어졌는지**다. 새 항목을 받거나 새 목적에
# 쓰기 시작한다면 반드시 여기 넣는다 — 그러지 않으면 알린 적 없는 범위로 처리하게 된다.
SENSITIVE_HEALTH_REVALIDATE_VERSIONS = frozenset({"v1.0"})

_CURRENT_VERSIONS = {
    TERMS: TERMS_VERSION,
    PRIVACY: PRIVACY_VERSION,
    SENSITIVE_HEALTH: SENSITIVE_HEALTH_VERSION,
    GROUP_ACTIVITY_SHARE: GROUP_ACTIVITY_SHARE_VERSION,
}

# 앱이 옛 문서를 보여주고 있을 때의 사용자 메시지. 앱을 최신으로 올리면 해소된다.
_STALE_VERSION_MESSAGE = "약관이 변경되었습니다. 앱을 최신 버전으로 업데이트한 뒤 다시 시도해주세요."

# 민감정보 동의가 유효하지 않을 때의 사용자 메시지 (전역 핸들러가 403 으로 내린다).
_SENSITIVE_CONSENT_REQUIRED_MESSAGE = "건강 민감정보 이용 동의가 필요합니다. 동의 후 다시 시도해주세요."
# 동의는 살아 있는데 문구가 개정된 경우. "동의가 필요합니다"라고만 하면 이미 동의한 사용자는
# 무엇이 문제인지 모른다 — 바뀌었다는 사실과 다시 동의할 곳을 알려 준다.
_SENSITIVE_CONSENT_OUTDATED_MESSAGE = (
    "건강 정보 동의 내용이 바뀌었어요. 내 정보 → 동의 관리에서 다시 동의해 주세요."
)


# StrEnum 은 3.11+ 이라 운영(Ubuntu 22.04, Python 3.10)에서 import 가 죽는다(2026-09-15 배포 장애).
class ConsentState(str, Enum):
    ACTIVE = "active"
    # 동의한 적이 없다.
    MISSING = "missing"
    # 최신 행이 철회됐다.
    REVOKED = "revoked"
    # 최신 행이 살아 있지만 **범위가 넓어진 개정 이전**의 버전이라 다시 받아야 한다
    # (단순 문구 개정으로 낡기만 한 동의는 ACTIVE 다 — SENSITIVE_HEALTH_REVALIDATE_VERSIONS).
    OUTDATED = "outdated"


class SensitiveConsentRequiredError(ForbiddenError):
    """민감정보 동의가 유효하지 않다. 메시지는 사용자용 한국어 문구다 (전역 핸들러가 403 으로 변환)."""


def is_current_version(kind: str, version: str) -> bool:
    """그 kind 의 현재 버전인가. 현재 버전을 모르는 kind 는 True 다 (`ensure_current_version` 과 같은 규칙)."""
    current = _CURRENT_VERSIONS.get(kind)

    return current is None or version == current


def ensure_current_version(kind: str, version: str) -> None:
    """앱이 **실제로 보여준 문서**의 버전이 현재 버전인지 확인한다.

    동의 이력의 존재 이유는 "누가 무엇에 동의했는지"의 증빙이다. 그런데 앱이 화면에 v1.0 을
    띄워 놓고 서버가 "2.0 에 동의함"으로 기록하면 그 증빙은 거짓이 된다 — 문서를 개정한 뒤
    구버전 앱이 남아 있으면 정확히 그 일이 벌어진다. 그래서 앱이 보낸 버전을 받아 현재 버전과
    **대조**하고, 다르면 기록하지 않고 막는다(400 → 앱 업데이트 유도).

    모르는 kind 는 통과시킨다 — 동의 종류가 늘 때 서버만 먼저 배포돼도 깨지지 않아야 한다.
    """
    if not is_current_version(kind, version):
        raise BadRequestError(_STALE_VERSION_MESSAGE)


# ---- 동의 ----

def list_consents(db: Session, user_id: int) -> list[UserConsent]:
    return list(
        db.scalars(
            select(UserConsent)
            .where(UserConsent.user_id == user_id)
            .order_by(UserConsent.agreed_at.desc(), UserConsent.id.desc())
        ).all()
    )


def requires_reconsent(kind: str, version: str) -> bool:
    """이 버전의 동의로는 기능이 막히는가 (민감정보만 해당).

    `is_current` 와 갈라 둔다 — 낡은 것과 무효인 것은 다르다. 문구를 다듬기만 한 개정이면
    낡아도 유효하고, 앱은 "바뀌었어요"만 알리면 된다.
    """
    return kind == SENSITIVE_HEALTH and version in SENSITIVE_HEALTH_REVALIDATE_VERSIONS


def serialize_consent(consent: UserConsent) -> dict:
    """동의 행의 응답. `is_current` 는 저장값이 아니라 **지금의 현재 버전**과 비교한 계산값이다.

    옛 행을 이력으로 남기므로 한 kind 에 버전이 다른 행이 여럿 있다. 앱은 이 값으로 "다시
    동의해야 하는 항목"을 그린다 — 앱이 서버 상수를 따로 들고 비교하면 둘이 어긋나는 순간
    화면이 거짓말을 한다.
    """
    return {
        "id": consent.id,
        "user_id": consent.user_id,
        "kind": consent.kind,
        "version": consent.version,
        "agreed_at": consent.agreed_at,
        "revoked_at": consent.revoked_at,
        "is_current": is_current_version(consent.kind, consent.version),
        "requires_reconsent": requires_reconsent(consent.kind, consent.version),
    }


def create_consent(db: Session, user_id: int, kind: str, version: str) -> UserConsent:
    # 앱이 보여준 문서가 현재 것인지 먼저 확인한다 (BadRequestError → 400).
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
    (다르면 BadRequestError → 400), 그 값을 그대로 기록한다.

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


def _latest_consent(db: Session, user_id: int, kind: str) -> UserConsent | None:
    return db.scalar(
        select(UserConsent)
        .where(UserConsent.user_id == user_id, UserConsent.kind == kind)
        .order_by(UserConsent.agreed_at.desc(), UserConsent.id.desc())
        .limit(1)
    )


def get_consent_state(db: Session, user_id: int) -> ConsentState:
    """민감정보 동의의 **최신 행** 하나로 판정한다. 옛 행이 살아 있어도 최신 행이 철회면 철회다.

    철회를 버전보다 먼저 본다 — 철회한 사람에게 "내용이 바뀌었으니 다시 동의하라"고 하면
    철회 의사를 무시하는 문구가 된다.
    """
    latest = _latest_consent(db, user_id, SENSITIVE_HEALTH)

    if latest is None:
        return ConsentState.MISSING

    if latest.revoked_at is not None:
        return ConsentState.REVOKED

    # 버전이 낡았다고 전부 무효는 아니다 — 범위가 넓어진 개정만 재동의를 요구한다
    # (SENSITIVE_HEALTH_REVALIDATE_VERSIONS 주석). 그 밖의 옛 버전은 ACTIVE 로 두고,
    # 응답의 `is_current: false` 로 앱이 "내용이 바뀌었어요"를 알린다.
    if latest.version in SENSITIVE_HEALTH_REVALIDATE_VERSIONS:
        return ConsentState.OUTDATED

    return ConsentState.ACTIVE


def has_active_consent(db: Session, user_id: int) -> bool:
    """민감정보 동의 유효 = 최신 행이 철회되지 않았고 **재동의 대상 버전이 아니다**.

    버전까지 보는 것은 민감정보뿐이다. 개인정보보호법 제23조는 민감정보를 **알린 목적·항목
    범위에서만** 처리하게 하므로, 문구가 넓어졌는데 옛 동의로 계속 처리하면 그 범위를 벗어난다 —
    v1.0 은 혈액형·질병·알러지를 "식단 추천에서 거르는 데"만 알렸고, 검사 수치·진료 메모와
    경고·리포트 용도는 v1.1 에서야 알린다 — 그래서 v1.0 만 재동의 대상이다. 범위가 넓어지지 않는
    개정은 무효화하지 않는다(2026-09-16). terms·privacy 는 기능 게이트가 아니라 가입 조건이라
    버전으로 무효화하지 않는다(개정마다 전 회원이 막히는 건 제품 결정이다). group_activity_share
    판정은 `challenge_service` 가 따로 한다.
    """
    return get_consent_state(db, user_id) is ConsentState.ACTIVE


def ensure_sensitive_consent(db: Session, user_id: int) -> None:
    """민감정보 동의가 유효하지 않으면 사용자에게 보일 이유와 함께 막는다.

    이유를 가르는 이유: 문구 개정으로 무효가 된 사용자는 **이미 동의한 사람**이다. 그 사람에게
    "동의가 필요합니다"를 보이면 동의했는데 왜 막히는지 알 수 없다.
    """
    state = get_consent_state(db, user_id)

    if state is ConsentState.ACTIVE:
        return

    if state is ConsentState.OUTDATED:
        raise SensitiveConsentRequiredError(_SENSITIVE_CONSENT_OUTDATED_MESSAGE)

    raise SensitiveConsentRequiredError(_SENSITIVE_CONSENT_REQUIRED_MESSAGE)


def revoke_consent(db: Session, user_id: int, kind: str) -> UserConsent:
    # 버전이 낡은 동의도 철회할 수 있다 — 버전은 보지 않는다. 문구가 바뀌어 효력이 멈춘 동의라도
    # 그 동의로 모은 데이터는 남아 있고, 철회는 그것을 파기하는 유일한 경로다.
    latest = _latest_consent(db, user_id, kind)

    if latest is None or latest.revoked_at is not None:
        raise NotFoundError("철회할 동의 내역이 없습니다.")

    # 동의 행은 삭제하지 않고 revoked_at 만 채워 증빙으로 남긴다.
    latest.revoked_at = datetime.now(UTC)

    if kind == SENSITIVE_HEALTH:
        _destroy_sensitive_data(db, user_id)

    db.commit()
    db.refresh(latest)
    return latest


def _destroy_sensitive_data(db: Session, user_id: int) -> None:
    """민감정보는 soft delete 가 아니라 물리 삭제(파기)다 (`docs/DATA_MODEL.md` 7장).

    **2026-08-19: 검사 수치와 진료 메모를 파기 대상에 추가했다.** 그전까지는 혈액형·질병·
    알러지 셋만 지웠고, 리비전 0027(`lab_results`)·0028(`care_visits`)이 들어올 때 이 목록이
    갱신되지 않았다 — 철회해도 검사 수치가 남아 있었다. 조회는 403 으로 막혔지만 파기는
    "접근을 막는 것"이 아니라 "없애는 것"이다.

    ⚠️ 새로 민감정보를 담는 테이블을 만들면 **여기에 반드시 추가한다.** 추천 캐시처럼 민감정보에서
    **파생된 값**을 저장하는 테이블도 포함한다. 탈퇴 연쇄
    (`account_service.delete_account`)와 짝이지만 서로 다른 목록이라, 한쪽만 고치면 이 사고가
    그대로 반복된다.
    """
    db.execute(delete(UserHealthProfile).where(UserHealthProfile.user_id == user_id))
    db.execute(delete(UserCondition).where(UserCondition.user_id == user_id))
    db.execute(delete(UserAllergy).where(UserAllergy.user_id == user_id))
    # 검사 수치는 그 자체가 건강 민감정보다 — 행째 파기한다.
    db.execute(delete(LabResult).where(LabResult.user_id == user_id))
    # 진료 메모(`outcome`)만 비운다. **행을 지우지 않는 이유**는 `scheduled_on`(날짜)이
    # 민감정보가 아니어서다 — 동의 없이도 D-day 는 계속 쓸 수 있어야 하고, 철회했다고
    # 진료 일정까지 잃게 하는 것은 필요 이상의 파기다 (`docs/DATA_MODEL.md` 31장).
    db.execute(
        update(CareVisit).where(CareVisit.user_id == user_id).values(outcome=None)
    )
    # 추천 캐시는 **민감정보에서 파생된 값을 저장한다** (2026-09-13 추가). `excluded` 에 질병·알러지의
    # 코드와 라벨("신장 질환")이, `items[].reason` 에 질병 태그에서 나온 문구("칼륨이 낮은 순")가
    # 그대로 들어간다(`recommendation_service.get_recommendation`). 원본을 지우고 캐시를 남기면
    # 철회해도 질병이 남는다. JSONB 안에서 그 부분만 도려내지 않고 **행째 지운다** — 파생 캐시라
    # 다음 요청에 다시 계산되고, 부분 수정은 새 필드가 생길 때마다 빠뜨릴 자리가 늘어난다.
    db.execute(delete(DietRecommendation).where(DietRecommendation.user_id == user_id))


# ---- 건강 프로필 (혈액형·Rh) ----

def get_health_profile(db: Session, user_id: int) -> UserHealthProfile:
    profile = db.scalar(select(UserHealthProfile).where(UserHealthProfile.user_id == user_id))
    if profile is None:
        raise NotFoundError("등록된 건강 정보가 없습니다. 혈액형 정보를 먼저 등록해주세요.")
    return profile


def upsert_health_profile(
    db: Session,
    user_id: int,
    blood_type: str | None,
    rh: str | None,
    ckd_stage: str | None = None,
) -> UserHealthProfile:
    profile = db.scalar(select(UserHealthProfile).where(UserHealthProfile.user_id == user_id))

    if profile is None:
        profile = UserHealthProfile(user_id=user_id)
        db.add(profile)

    profile.blood_type = blood_type
    profile.rh = rh
    profile.ckd_stage = ckd_stage

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
        raise BadRequestError(f"선택할 수 없는 질병 코드입니다: {', '.join(invalid)}")

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
        raise BadRequestError(f"선택할 수 없는 알러지 코드입니다: {', '.join(invalid)}")

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
