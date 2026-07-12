from datetime import date, datetime, time, timedelta

from timeutil import UTC
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.group_model import GroupMember, GroupPet
from models.pet_model import Pet, PetFeedingLog


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _get_owned_pet(db: Session, user_id: int, pet_id: int) -> Pet:
    pet = db.scalar(select(Pet).where(Pet.id == pet_id, Pet.deleted_at.is_(None)))

    # 존재하지 않거나 남의 소유면 존재 자체를 숨긴다 (정보 노출 방지).
    if pet is None or pet.owner_id != user_id:
        raise LookupError("반려동물을 찾을 수 없습니다.")

    return pet


def _get_accessible_pet(db: Session, user_id: int, pet_id: int) -> Pet:
    # 급여 기록은 소유자 외에 펫이 참여한 그룹의 멤버도 접근한다 (가족이 함께 급여를 기록한다).
    pet = db.scalar(select(Pet).where(Pet.id == pet_id, Pet.deleted_at.is_(None)))

    if pet is None:
        raise LookupError("반려동물을 찾을 수 없습니다.")

    if pet.owner_id == user_id:
        return pet

    shared = db.scalar(
        select(GroupPet.id)
        .join(GroupMember, GroupMember.group_id == GroupPet.group_id)
        .where(GroupPet.pet_id == pet_id, GroupMember.user_id == user_id)
        .limit(1)
    )
    if shared is None:
        raise LookupError("반려동물을 찾을 수 없습니다.")

    return pet


# ---- 권장 칼로리 (RER/MER) ----

# MER 계수 — 성체·중성화 가정의 보수적 잠정값 (DATA_MODEL.md 18장. 전문가 감수 전까지의 초기값).
# species=other 는 계수 근거가 없어 산출하지 않는다.
MER_FACTORS = {"dog": 1.6, "cat": 1.2}


def compute_recommended_kcal(species: str, weight_kg: Decimal | None) -> int | None:
    # RER = 70 × 체중(kg)^0.75. 저장하지 않고 응답 시마다 계산한다 (체중 수정에 항상 따라간다).
    if weight_kg is None:
        return None

    factor = MER_FACTORS.get(species)
    if factor is None:
        return None

    rer = 70 * float(weight_kg) ** 0.75
    return round(rer * factor)


def _pet_response(pet: Pet) -> dict:
    return {
        "id": pet.id,
        "owner_id": pet.owner_id,
        "name": pet.name,
        "species": pet.species,
        "breed": pet.breed,
        "birth_year": pet.birth_year,
        "weight_kg": pet.weight_kg,
        "is_neutered": pet.is_neutered,
        "recommended_kcal": compute_recommended_kcal(pet.species, pet.weight_kg),
        "created_at": pet.created_at,
        "updated_at": pet.updated_at,
    }


# ---- 반려동물 ----

def create_pet(
    db: Session,
    owner_id: int,
    name: str,
    species: str,
    breed: str | None,
    birth_year: int | None,
    weight_kg: float | None,
    is_neutered: bool | None,
) -> dict:
    pet = Pet(
        owner_id=owner_id,
        name=name,
        species=species,
        breed=breed,
        birth_year=birth_year,
        weight_kg=Decimal(str(weight_kg)) if weight_kg is not None else None,
        is_neutered=is_neutered,
    )
    db.add(pet)
    db.commit()
    db.refresh(pet)
    return _pet_response(pet)


def list_pets(db: Session, owner_id: int) -> list[dict]:
    pets = db.scalars(
        select(Pet)
        .where(Pet.owner_id == owner_id, Pet.deleted_at.is_(None))
        .order_by(Pet.id.asc())
    ).all()
    return [_pet_response(pet) for pet in pets]


def update_pet(
    db: Session,
    user_id: int,
    pet_id: int,
    name: str,
    species: str,
    breed: str | None,
    birth_year: int | None,
    weight_kg: float | None,
    is_neutered: bool | None,
) -> dict:
    pet = _get_owned_pet(db, user_id, pet_id)

    pet.name = name
    pet.species = species
    pet.breed = breed
    pet.birth_year = birth_year
    pet.weight_kg = Decimal(str(weight_kg)) if weight_kg is not None else None
    pet.is_neutered = is_neutered

    db.commit()
    db.refresh(pet)
    return _pet_response(pet)


def soft_delete_pet(db: Session, user_id: int, pet_id: int) -> None:
    pet = _get_owned_pet(db, user_id, pet_id)
    pet.deleted_at = datetime.now(UTC)
    db.commit()


# ---- 급여 기록 ----

def create_feeding(
    db: Session,
    user_id: int,
    pet_id: int,
    food_label: str,
    amount_g: float,
    kcal: int | None,
    fed_at: datetime | None,
) -> PetFeedingLog:
    pet = _get_accessible_pet(db, user_id, pet_id)

    feeding = PetFeedingLog(
        pet_id=pet.id,
        food_label=food_label,
        amount_g=Decimal(str(amount_g)),
        kcal=kcal,
        fed_at=fed_at if fed_at is not None else datetime.now(UTC),
    )
    db.add(feeding)
    db.commit()
    db.refresh(feeding)
    return feeding


def list_feedings(db: Session, user_id: int, pet_id: int, target_date: date) -> list[PetFeedingLog]:
    pet = _get_accessible_pet(db, user_id, pet_id)
    start, end = _day_bounds(target_date)

    return list(
        db.scalars(
            select(PetFeedingLog)
            .where(
                PetFeedingLog.pet_id == pet.id,
                PetFeedingLog.fed_at >= start,
                PetFeedingLog.fed_at < end,
            )
            .order_by(PetFeedingLog.fed_at.asc())
        ).all()
    )
