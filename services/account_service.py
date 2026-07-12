from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.auth_model import AuthSession, PhoneVerificationCode, User
from models.consent_model import UserAllergy, UserCondition, UserConsent, UserHealthProfile
from models.group_model import Group, GroupMember, GroupPet
from models.health_model import MealItem, MealLog, UserGoal, UserProfile, WeightLog
from models.pet_model import Pet, PetFeedingLog
from models.recommendation_model import DietRecommendation


def delete_account(db: Session, user: User) -> None:
    # 회원 탈퇴 = 개인정보보호법 제21조(파기)에 따른 물리 삭제다. soft delete 행(deleted_at)도 파기한다.
    # FK 가 전부 ON DELETE NO ACTION 이므로 자식 → 부모 순서를 지킨다. 근거·연쇄 표는 DATA_MODEL.md 18장.
    # commit 은 마지막 한 번 — 중간 실패 시 세션 종료와 함께 전체 롤백된다.
    user_id = user.id
    phone_number = user.phone_number
    owned_group_ids = select(Group.id).where(Group.owner_id == user_id)
    owned_pet_ids = select(Pet.id).where(Pet.owner_id == user_id)
    my_meal_log_ids = select(MealLog.id).where(MealLog.user_id == user_id)

    # 1) 세션·인증코드 — 세션 행 파기로 해당 유저의 모든 토큰이 즉시 무효(401)가 된다.
    #    phone_verification_codes 는 FK 없이 phone_number 로 귀속되므로 번호 기준으로 파기한다.
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    db.execute(
        delete(PhoneVerificationCode).where(PhoneVerificationCode.phone_number == phone_number)
    )

    # 2) 동의·민감정보 — 동의 이력도 개인정보이므로 함께 파기한다 (18장 잠정 결정).
    db.execute(delete(UserConsent).where(UserConsent.user_id == user_id))
    db.execute(delete(UserHealthProfile).where(UserHealthProfile.user_id == user_id))
    db.execute(delete(UserCondition).where(UserCondition.user_id == user_id))
    db.execute(delete(UserAllergy).where(UserAllergy.user_id == user_id))

    # 3) 건강 기록 — meal_items 는 meal_logs 의 자식이라 먼저 지운다 (soft delete 된 끼니 포함).
    db.execute(delete(MealItem).where(MealItem.meal_log_id.in_(my_meal_log_ids)))
    db.execute(delete(MealLog).where(MealLog.user_id == user_id))
    db.execute(delete(WeightLog).where(WeightLog.user_id == user_id))
    db.execute(delete(UserGoal).where(UserGoal.user_id == user_id))
    db.execute(delete(UserProfile).where(UserProfile.user_id == user_id))
    db.execute(delete(DietRecommendation).where(DietRecommendation.user_id == user_id))

    # 4) 소유 펫의 자식 — 급여 기록과 그룹 연결(남의 그룹에 참여한 것 포함)을 먼저 지운다.
    #    급여 기록에는 작성자 FK 가 없어 pet_id 귀속이다. 타인이 내 펫에 남긴 기록도 함께 파기되고,
    #    반대로 내가 타인 펫에 남긴 기록은 참조가 없어 그대로 보존된다 (18장).
    db.execute(delete(PetFeedingLog).where(PetFeedingLog.pet_id.in_(owned_pet_ids)))
    db.execute(delete(GroupPet).where(GroupPet.pet_id.in_(owned_pet_ids)))

    # 5) 소유 그룹은 그룹째 삭제 — 17장 그룹 삭제와 같은 연쇄. 타인 펫 연결·타인 멤버십을 먼저 지운다.
    db.execute(delete(GroupPet).where(GroupPet.group_id.in_(owned_group_ids)))
    db.execute(delete(GroupMember).where(GroupMember.group_id.in_(owned_group_ids)))

    # 6) 남의 그룹에 남은 내 멤버십 — 그룹 자체는 보존된다.
    db.execute(delete(GroupMember).where(GroupMember.user_id == user_id))

    # 7) 부모 행 — groups(owner FK) → pets → users 순서로 마감한다.
    db.execute(delete(Group).where(Group.owner_id == user_id))
    db.execute(delete(Pet).where(Pet.owner_id == user_id))
    db.execute(delete(User).where(User.id == user_id))

    db.commit()
