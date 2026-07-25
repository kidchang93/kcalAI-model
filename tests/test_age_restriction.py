"""만 14세 미만 가입 차단 (`docs/LEGAL_COMPLIANCE.md` §1).

이 파일이 지키는 것은 기능이 아니라 **법적 의무**다. 개인정보 보호법 제22조의2 위반은
5년 이하 징역 또는 5천만원 이하 벌금이고, 우리는 질병·알러지라는 민감정보까지 다룬다.

의학적 이유도 같은 방향이다 — 이 앱의 식이 규칙은 전부 성인 지침(KSN·KDA·KSH)에서 왔고,
소아 신장질환·소아 당뇨는 기준이 다르다. 막지 않으면 아이에게 성인 기준을 적용하게 된다.
"""

from datetime import datetime

import pytest
from timeutil import UTC

from models.auth_model import User
from services import health_service

THIS_YEAR = datetime.now(UTC).year


@pytest.fixture
def user(db):
    row = User(kakao_id="age-restriction-test", nickname="연령테스터")
    db.add(row)
    db.flush()
    return row


def _save(db, user, birth_year: int):
    return health_service.upsert_profile(
        db,
        user.id,
        sex="male",
        birth_year=birth_year,
        height_cm=170,
        weight_kg=65,
        activity_level="moderate",
    )


def test_under_14_is_rejected(db, user):
    with pytest.raises(ValueError) as error:
        _save(db, user, THIS_YEAR - 13)

    assert "만 14세 미만" in str(error.value)


def test_exactly_14_is_allowed(db, user):
    """경계는 통과시킨다 — 만 14세부터는 본인 동의로 가입할 수 있다."""
    profile = _save(db, user, THIS_YEAR - 14)

    assert profile.birth_year == THIS_YEAR - 14


def test_adult_is_allowed(db, user):
    profile = _save(db, user, 1993)

    assert profile.birth_year == 1993


def test_child_profile_is_not_persisted(db, user):
    """거부는 저장 **전에** 일어나야 한다 — 아동의 정보가 DB 에 남으면 차단의 의미가 없다."""
    from sqlalchemy import select

    from models.health_model import UserProfile

    with pytest.raises(ValueError):
        _save(db, user, THIS_YEAR - 10)

    assert db.scalar(select(UserProfile).where(UserProfile.user_id == user.id)) is None
