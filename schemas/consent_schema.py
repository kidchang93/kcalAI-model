from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConsentKind = Literal["sensitive_health", "terms", "privacy"]
BloodType = Literal["A", "B", "O", "AB", "unknown"]
Rh = Literal["+", "-"]
# 신장병 병기(투석 여부). 나트륨 1일 상한이 여기서 갈린다 — 비투석 2,000 · 투석 3,000
# (`services/ckd_food_rules.py` STAGE_TARGETS). 모름은 별도 코드가 아니라 null 이다.
CkdStage = Literal["nondialysis", "hemodialysis", "peritoneal"]
# condition · allergen 코드는 Literal 이 아니라 서비스 레이어에서
# 참조 테이블(condition_types/allergen_types) 조회로 검증한다 (DATA_MODEL.md 10장).
Severity = Literal["mild", "severe"]


class ConsentCreateRequest(BaseModel):
    kind: ConsentKind
    version: str = Field(..., min_length=1, max_length=20)


class ConsentRevokeRequest(BaseModel):
    kind: ConsentKind


class ConsentResponse(BaseModel):
    id: int
    user_id: int
    kind: str
    version: str
    agreed_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class HealthProfileUpsertRequest(BaseModel):
    # 전부 nullable — 모름 허용.
    blood_type: BloodType | None = None
    rh: Rh | None = None
    # 신장 질환자만 의미가 있다. 그 외에는 보내지 않으면 그만이라 서버가 질환을 검사하지
    # 않는다 — 질환이 없으면 이 값을 읽는 곳이 없다(day_nutrition 이 축 자체를 안 만든다).
    ckd_stage: CkdStage | None = None


class HealthProfileResponse(BaseModel):
    id: int
    user_id: int
    blood_type: str | None
    rh: str | None
    ckd_stage: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConditionsPutRequest(BaseModel):
    # replace-all. 빈 배열 = 전체 삭제.
    conditions: list[str]


class ConditionsResponse(BaseModel):
    conditions: list[str]


class AllergyInput(BaseModel):
    allergen: str = Field(..., min_length=1, max_length=100)
    severity: Severity | None = None


class AllergyItem(BaseModel):
    allergen: str
    severity: str | None

    model_config = {"from_attributes": True}


class AllergiesPutRequest(BaseModel):
    # replace-all. 빈 배열 = 전체 삭제.
    allergies: list[AllergyInput]


class AllergiesResponse(BaseModel):
    allergies: list[AllergyItem]


class MessageResponse(BaseModel):
    message: str


class ConsentError(BaseModel):
    detail: str
