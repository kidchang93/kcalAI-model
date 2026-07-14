from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

GroupKind = Literal["family", "couple", "friends", "challenge"]


class GroupCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: GroupKind


class GroupJoinRequest(BaseModel):
    invite_code: str = Field(..., min_length=1, max_length=12)


class GroupPetAttachRequest(BaseModel):
    pet_id: int


class GroupSummary(BaseModel):
    id: int
    owner_id: int
    name: str
    kind: str
    # 목록·생성·참여가 이미 멤버 전용 응답이므로 멤버에게만 보인다.
    invite_code: str
    # 현재 사용자의 역할 (owner / member).
    role: str
    member_count: int
    created_at: datetime


class GroupMemberItem(BaseModel):
    user_id: int
    # 그룹에 보이는 이름 = 카카오 닉네임 (2026-07-14 이전엔 마스킹한 휴대폰 번호였다).
    nickname: str
    role: str
    joined_at: datetime


class GroupPetItem(BaseModel):
    pet_id: int
    name: str
    species: str
    joined_at: datetime


class GroupDetailResponse(BaseModel):
    id: int
    owner_id: int
    name: str
    kind: str
    invite_code: str
    created_at: datetime
    members: list[GroupMemberItem]
    pets: list[GroupPetItem]


class MessageResponse(BaseModel):
    message: str


class GroupError(BaseModel):
    detail: str
