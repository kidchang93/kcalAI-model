from pydantic import BaseModel


class OptionItem(BaseModel):
    code: str
    label: str


class MetaOptionsResponse(BaseModel):
    conditions: list[OptionItem]
    allergens: list[OptionItem]
    # 신장병 병기(투석 여부). 참조 테이블이 아니라 지침에서 온 고정 3종이라 코드 상수로 준다
    # — 그래도 라벨은 서버가 정한다(앱이 의학 용어를 자기 마음대로 쓰지 않게).
    ckd_stages: list[OptionItem] = []
