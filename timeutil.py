"""datetime 호환 유틸.

`datetime.UTC`는 Python 3.11+에서 추가됐다. 배포 서버(Lightsail Ubuntu 22.04)는 Python
3.10이라 `from datetime import UTC`가 ImportError를 낸다. `UTC`는 `timezone.utc`와 동일하므로
여기서 정의해 3.10에서도 동작하게 한다. (코드는 `from timeutil import UTC`로 쓴다.)
"""

from datetime import timezone

UTC = timezone.utc
