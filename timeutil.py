"""datetime 호환 유틸.

`datetime.UTC`는 Python 3.11+에서 추가됐다. 배포 서버(Lightsail Ubuntu 22.04)는 Python
3.10이라 `from datetime import UTC`가 ImportError를 낸다. `UTC`는 `timezone.utc`와 동일하므로
여기서 정의해 3.10에서도 동작하게 한다. (코드는 `from timeutil import UTC`로 쓴다.)
"""

from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc

# 요금제 일일 쿼터의 리셋 경계. 기록(meal_logs·weight_logs)의 하루 경계는 UTC지만, 쿼터는
# "오늘 몇 건 남았나"를 사용자가 체감하는 값이라 국내 서비스 기준시(KST) 자정에 리셋한다.
# 서버 TZ 설정에 의존하지 않도록 고정 오프셋으로 둔다 (한국은 서머타임이 없다).
KST = timezone(timedelta(hours=9))


def today_kst() -> date:
    return datetime.now(KST).date()
