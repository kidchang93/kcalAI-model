# 패키지 import 한 번(`import models`, `import models.auth_model` 포함)으로 전 모델을 Base.metadata 에
# 등록한다 — FK 대상 테이블이 빠지면 create_all 이 실패한다. 새 모델 모듈은 여기에 추가한다.
from . import (  # noqa: F401
    auth_model,
    consent_model,
    group_model,
    health_model,
    meta_model,
    pet_model,
    recommendation_model,
    subscription_model,
)
