from fastapi import APIRouter, status

from api.dependencies import DB, ConsentedUser, CurrentUser
from schemas.common_schema import ErrorResponse, MessageResponse
from schemas.consent_schema import (
    AllergiesPutRequest,
    AllergiesResponse,
    ConditionsPutRequest,
    ConditionsResponse,
    ConsentCreateRequest,
    ConsentResponse,
    ConsentRevokeRequest,
    HealthProfileResponse,
    HealthProfileUpsertRequest,
)
from services import consent_service

router = APIRouter()


# ---- 동의 ----

@router.get(
    "/me/consents",
    response_model=list[ConsentResponse],
    responses={401: {"model": ErrorResponse}},
)
def read_consents(current_user: CurrentUser, db: DB):
    return [
        consent_service.serialize_consent(consent)
        for consent in consent_service.list_consents(db, current_user.id)
    ]


@router.post(
    "/me/consents",
    response_model=ConsentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def create_consent(request: ConsentCreateRequest, current_user: CurrentUser, db: DB):
    # 앱이 옛 문서를 보여주고 있으면 400 이다 (ensure_current_version) — 앱을 업데이트하면 해소된다.
    consent = consent_service.create_consent(db, current_user.id, request.kind, request.version)
    return consent_service.serialize_consent(consent)


@router.post(
    "/me/consents/revoke",
    response_model=MessageResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def revoke_consent(request: ConsentRevokeRequest, current_user: CurrentUser, db: DB):
    consent_service.revoke_consent(db, current_user.id, request.kind)
    return {"message": "동의를 철회했습니다."}


# ---- 건강 프로필 (혈액형·Rh) ----

@router.get(
    "/me/health-profile",
    response_model=HealthProfileResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def read_health_profile(current_user: ConsentedUser, db: DB):
    return consent_service.get_health_profile(db, current_user.id)


@router.put(
    "/me/health-profile",
    response_model=HealthProfileResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def update_health_profile(request: HealthProfileUpsertRequest, current_user: ConsentedUser, db: DB):
    return consent_service.upsert_health_profile(db, current_user.id, **request.model_dump())


# ---- 질병 ----

@router.get(
    "/me/conditions",
    response_model=ConditionsResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def read_conditions(current_user: ConsentedUser, db: DB):
    return {"conditions": consent_service.list_conditions(db, current_user.id)}


@router.put(
    "/me/conditions",
    response_model=ConditionsResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def replace_conditions(request: ConditionsPutRequest, current_user: ConsentedUser, db: DB):
    conditions = consent_service.replace_conditions(db, current_user.id, list(request.conditions))
    return {"conditions": conditions}


# ---- 알러지 ----

@router.get(
    "/me/allergies",
    response_model=AllergiesResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def read_allergies(current_user: ConsentedUser, db: DB):
    return {"allergies": consent_service.list_allergies(db, current_user.id)}


@router.put(
    "/me/allergies",
    response_model=AllergiesResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def replace_allergies(request: AllergiesPutRequest, current_user: ConsentedUser, db: DB):
    allergies = consent_service.replace_allergies(
        db,
        current_user.id,
        [allergy.model_dump() for allergy in request.allergies],
    )
    return {"allergies": allergies}
