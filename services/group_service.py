import secrets

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from models.auth_model import User
from models.group_model import Group, GroupMember, GroupPet
from models.pet_model import Pet

# 혼동 문자(I, L, O, 0, 1)를 제외한 대문자·숫자.
INVITE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
INVITE_CODE_LENGTH = 8

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"


def mask_phone_number(phone_number: str) -> str:
    # 그룹 멤버 사이에서도 휴대폰 번호 원본은 노출하지 않는다 (개인정보 최소노출).
    if len(phone_number) < 8:
        return phone_number[:3] + "****"
    return phone_number[:3] + "****" + phone_number[-4:]


def _generate_invite_code(db: Session) -> str:
    while True:
        code = "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))
        if db.scalar(select(Group.id).where(Group.invite_code == code)) is None:
            return code


def _member_count(db: Session, group_id: int) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)
        )
    )


def _summary(db: Session, group: Group, role: str) -> dict:
    return {
        "id": group.id,
        "owner_id": group.owner_id,
        "name": group.name,
        "kind": group.kind,
        "invite_code": group.invite_code,
        "role": role,
        "member_count": _member_count(db, group.id),
        "created_at": group.created_at,
    }


def get_membership(db: Session, group_id: int, user_id: int) -> GroupMember | None:
    return db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    )


def create_group(db: Session, owner_id: int, name: str, kind: str) -> dict:
    group = Group(owner_id=owner_id, name=name, kind=kind, invite_code=_generate_invite_code(db))
    db.add(group)
    db.flush()

    # 생성자는 자동으로 owner 멤버가 된다.
    db.add(GroupMember(group_id=group.id, user_id=owner_id, role=ROLE_OWNER))
    db.commit()
    db.refresh(group)
    return _summary(db, group, role=ROLE_OWNER)


def list_my_groups(db: Session, user_id: int) -> list[dict]:
    rows = db.execute(
        select(Group, GroupMember.role)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.user_id == user_id)
        .order_by(Group.id.asc())
    ).all()
    return [_summary(db, group, role) for group, role in rows]


def join_group(db: Session, user_id: int, invite_code: str) -> dict:
    group = db.scalar(select(Group).where(Group.invite_code == invite_code.strip().upper()))
    if group is None:
        raise LookupError("초대 코드에 해당하는 그룹이 없습니다. 코드를 다시 확인해주세요.")

    if get_membership(db, group.id, user_id) is not None:
        raise ValueError("이미 참여한 그룹입니다.")

    db.add(GroupMember(group_id=group.id, user_id=user_id, role=ROLE_MEMBER))
    db.commit()
    return _summary(db, group, role=ROLE_MEMBER)


def get_group_detail(db: Session, user_id: int, group_id: int) -> dict:
    group = db.scalar(select(Group).where(Group.id == group_id))
    if group is None:
        raise LookupError("그룹을 찾을 수 없습니다.")

    if get_membership(db, group_id, user_id) is None:
        raise PermissionError("그룹 멤버만 조회할 수 있습니다.")

    member_rows = db.execute(
        select(GroupMember, User.phone_number)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at.asc(), GroupMember.id.asc())
    ).all()

    pet_rows = db.execute(
        select(GroupPet, Pet)
        .join(Pet, Pet.id == GroupPet.pet_id)
        .where(GroupPet.group_id == group_id, Pet.deleted_at.is_(None))
        .order_by(GroupPet.joined_at.asc(), GroupPet.id.asc())
    ).all()

    return {
        "id": group.id,
        "owner_id": group.owner_id,
        "name": group.name,
        "kind": group.kind,
        "invite_code": group.invite_code,
        "created_at": group.created_at,
        "members": [
            {
                "user_id": member.user_id,
                "phone_number_masked": mask_phone_number(phone_number),
                "role": member.role,
                "joined_at": member.joined_at,
            }
            for member, phone_number in member_rows
        ],
        "pets": [
            {
                "pet_id": pet.id,
                "name": pet.name,
                "species": pet.species,
                "joined_at": group_pet.joined_at,
            }
            for group_pet, pet in pet_rows
        ],
    }


def attach_pet(db: Session, user_id: int, group_id: int, pet_id: int) -> None:
    group = db.scalar(select(Group).where(Group.id == group_id))
    if group is None:
        raise LookupError("그룹을 찾을 수 없습니다.")

    if get_membership(db, group_id, user_id) is None:
        raise PermissionError("그룹 멤버만 반려동물을 참여시킬 수 있습니다.")

    pet = db.scalar(select(Pet).where(Pet.id == pet_id, Pet.deleted_at.is_(None)))
    # 존재하지 않거나 남의 소유면 존재 자체를 숨긴다 (정보 노출 방지).
    if pet is None or pet.owner_id != user_id:
        raise LookupError("반려동물을 찾을 수 없습니다.")

    exists = db.scalar(
        select(GroupPet.id).where(GroupPet.group_id == group_id, GroupPet.pet_id == pet_id)
    )
    if exists is not None:
        raise ValueError("이미 그룹에 참여한 반려동물입니다.")

    db.add(GroupPet(group_id=group_id, pet_id=pet_id))
    db.commit()


# ---- 라이프사이클 (탈퇴 · 삭제 · 제거 · 펫 해제) ----
# 파괴적 라우트는 비멤버에게 그룹 존재 자체를 숨긴다 (404) — 남의 펫 404 은닉과 같은 규칙.

def _get_group_membership_or_hide(
    db: Session, user_id: int, group_id: int
) -> tuple[Group, GroupMember]:
    group = db.scalar(select(Group).where(Group.id == group_id))
    membership = get_membership(db, group_id, user_id) if group is not None else None

    if group is None or membership is None:
        raise LookupError("그룹을 찾을 수 없습니다.")

    return group, membership


def _detach_pets_owned_by(db: Session, group_id: int, owner_id: int) -> None:
    # 소유자가 그룹을 떠나면 펫 공유의 전제(소유자의 멤버십)가 사라지므로 참여도 함께 해제한다.
    # 급여 기록은 pet_id 에 귀속되므로 보존된다.
    pet_ids = select(Pet.id).where(Pet.owner_id == owner_id)
    db.execute(
        delete(GroupPet).where(GroupPet.group_id == group_id, GroupPet.pet_id.in_(pet_ids))
    )


def leave_group(db: Session, user_id: int, group_id: int) -> None:
    group, membership = _get_group_membership_or_hide(db, user_id, group_id)

    if group.owner_id == user_id:
        raise ValueError("소유자는 탈퇴할 수 없습니다. 그룹 삭제로 진행해주세요.")

    _detach_pets_owned_by(db, group_id, user_id)
    db.delete(membership)
    db.commit()


def delete_group(db: Session, user_id: int, group_id: int) -> None:
    group, _ = _get_group_membership_or_hide(db, user_id, group_id)

    if group.owner_id != user_id:
        raise PermissionError("그룹 소유자만 삭제할 수 있습니다.")

    # 멤버십·펫 참여 연결만 지운다. 펫과 급여 기록은 그룹이 아니라 소유자·펫에 귀속되므로 남긴다.
    db.execute(delete(GroupPet).where(GroupPet.group_id == group_id))
    db.execute(delete(GroupMember).where(GroupMember.group_id == group_id))
    db.delete(group)
    db.commit()


def remove_member(db: Session, user_id: int, group_id: int, target_user_id: int) -> None:
    group, _ = _get_group_membership_or_hide(db, user_id, group_id)

    if group.owner_id != user_id:
        raise PermissionError("그룹 소유자만 멤버를 제거할 수 있습니다.")

    if target_user_id == user_id:
        raise ValueError("소유자 자신은 제거할 수 없습니다. 그룹 삭제로 진행해주세요.")

    target = get_membership(db, group_id, target_user_id)
    if target is None:
        raise LookupError("그룹에서 해당 멤버를 찾을 수 없습니다.")

    _detach_pets_owned_by(db, group_id, target_user_id)
    db.delete(target)
    db.commit()


def detach_pet(db: Session, user_id: int, group_id: int, pet_id: int) -> None:
    group, _ = _get_group_membership_or_hide(db, user_id, group_id)

    row = db.execute(
        select(GroupPet, Pet)
        .join(Pet, Pet.id == GroupPet.pet_id)
        .where(
            GroupPet.group_id == group_id,
            GroupPet.pet_id == pet_id,
            Pet.deleted_at.is_(None),
        )
    ).first()
    if row is None:
        raise LookupError("그룹에 참여한 반려동물을 찾을 수 없습니다.")

    group_pet, pet = row
    if pet.owner_id != user_id and group.owner_id != user_id:
        raise PermissionError("반려동물 소유자 또는 그룹 소유자만 참여를 해제할 수 있습니다.")

    # 급여 기록은 pet_id 에 귀속되므로 보존된다 (펫 soft delete 때와 같은 규칙).
    db.delete(group_pet)
    db.commit()
