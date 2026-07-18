"""curated 음식 시드 → food_nutrition 임포트 (source='curated').

사용법 (반드시 저장소 루트에서):
    venv/bin/python scripts/seed_curated_foods.py

목적: YOLO 라벨 중 식약처 DB 범위 밖이라 estimate가 404로 떨어지던 항목(외국 요리·
생선/일반명 한식·간식·음료 등)을 대표적으로 채워 매칭되게 한다 (DATA_MODEL.md 12장).

특징:
- 멱등 upsert. 재실행하면 curated 행의 값만 갱신한다.
- ON CONFLICT ... WHERE source='curated' — 같은 라벨이 이미 mfds(실측) 등으로 있으면
  건드리지 않는다 (mfds가 curated보다 신뢰도 높다).
- 값은 1인분 기준 근사값이다. macros·food_group은 우선 비워 둔다(뼈대 우선, 추후 보강).
- curated 는 추천 후보 풀(source='mfds')에 들어가지 않으므로 estimate 전용이다.

항목을 계속 추가/보강하려면 아래 CURATED_FOODS 리스트에 (라벨, kcal, 1인분 설명)을
넣고 다시 실행하면 된다.
"""

import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

# 스크립트를 scripts/ 밖의 로컬 모듈(database, models)과 연결한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from models.health_model import FoodNutrition  # noqa: E402
from services.serving_size import parse_serving_size_g  # noqa: E402

SOURCE_CURATED = "curated"

# (food_label, kcal_per_serving, serving_desc). food_label 은 YOLO 라벨과 정확히 일치해야
# estimate 정확 매칭이 된다 (현재 404 나는 라벨 실측 목록에서 골랐다).
CURATED_FOODS: list[tuple[str, int, str]] = [
    # --- 외국 요리 (일식) ---
    ("가츠동", 700, "1그릇"),
    ("낫또", 100, "1팩(50g)"),
    ("소바", 350, "1그릇"),
    ("야끼소바", 550, "1그릇"),
    ("오니기리", 180, "1개"),
    ("타코야끼", 330, "6개"),
    ("타코야키", 330, "6개"),
    ("데리야끼치킨", 400, "1인분"),
    ("도리아", 550, "1그릇"),
    ("완탕", 200, "1그릇"),
    ("딤섬", 250, "4개"),
    ("춘권", 220, "2개"),
    # --- 외국 요리 (동남아) ---
    ("나시고렝", 600, "1그릇"),
    ("반미", 400, "1개"),
    ("볶음쌀국수", 550, "1그릇"),
    ("똠양꿍", 200, "1그릇"),
    ("쏨땀", 150, "1접시"),
    # --- 외국 요리 (양식) ---
    ("봉골레파스타", 550, "1그릇"),
    ("크림파스타", 700, "1그릇"),
    ("펜네파스타", 600, "1그릇"),
    ("화덕피자", 700, "1판(개인)"),
    ("파에야", 600, "1인분"),
    ("라따뚜이", 200, "1접시"),
    ("스튜", 350, "1그릇"),
    ("피쉬앤칩스", 800, "1인분"),
    ("케밥", 550, "1개"),
    ("케사디야", 500, "1개"),
    ("퀘사디아", 500, "1개"),
    ("타코", 220, "1개"),
    ("나쵸", 350, "1접시"),
    ("카프레제샐러드", 250, "1접시"),
    ("크레페", 300, "1개"),
    ("슈바인학센", 900, "1인분"),
    ("카나페", 200, "4개"),
    # --- 생선 / 일반명 한식 ---
    ("생선구이", 250, "1토막"),
    ("생선찌개", 300, "1그릇"),
    ("생선튀김", 350, "1토막"),
    ("생선회", 200, "1인분"),
    ("회", 200, "1인분"),
    ("산낙지", 100, "1접시"),
    ("과메기", 250, "1인분"),
    ("북엇국", 150, "1그릇"),
    ("새우매운탕", 250, "1그릇"),
    ("냉채족발", 500, "1인분"),
    ("편육", 300, "1인분"),
    ("통닭", 500, "1인분"),
    ("오리로스구이", 500, "1인분"),
    ("데친두부", 150, "반 모"),
    # --- 치킨류 ---
    ("후라이드치킨다리", 180, "1조각"),
    ("윙봉후라이드치킨", 160, "1조각"),
    ("핫윙", 90, "1개"),
    # --- 김치 / 절임 ---
    ("무김치", 30, "1접시(70g)"),
    ("알타리김치", 30, "1접시(70g)"),
    # --- 간식 / 과자 ---
    ("군밤", 200, "10개"),
    ("뻥튀기", 50, "1장"),
    ("초코바", 230, "1개"),
    ("막대사탕", 50, "1개"),
    ("한과", 120, "2개"),
    ("회오리감자", 300, "1개"),
    ("떡꼬치", 250, "1개"),
    # --- 음료 / 주류 ---
    ("감귤주스", 110, "1잔(200ml)"),
    ("사이다", 100, "1캔(250ml)"),
    ("생맥주", 185, "500ml"),
    ("레드와인", 125, "1잔(150ml)"),
    ("수정과", 130, "1잔(200ml)"),
]


def seed() -> None:
    rows = [
        {
            "food_label": label,
            "kcal_per_serving": kcal,
            "serving_desc": serving_desc,
            # serving_desc("1팩(50g)"·"1잔(200ml)")에서 1인분 무게를 뽑는다. "1그릇"처럼 무게가 없으면 None.
            "serving_size_g": parse_serving_size_g(serving_desc),
            "source": SOURCE_CURATED,
        }
        for label, kcal, serving_desc in CURATED_FOODS
    ]

    session = SessionLocal()
    try:
        statement = insert(FoodNutrition).values(rows)
        # 같은 라벨이 이미 curated 로 있으면 값 갱신, mfds 등 다른 source 면 건드리지 않는다.
        statement = statement.on_conflict_do_update(
            index_elements=[FoodNutrition.food_label],
            set_={
                "kcal_per_serving": statement.excluded.kcal_per_serving,
                "serving_desc": statement.excluded.serving_desc,
                "serving_size_g": statement.excluded.serving_size_g,
            },
            where=(FoodNutrition.source == SOURCE_CURATED),
        )
        session.execute(statement)
        session.commit()
        print(f"curated 시드 {len(rows)}건 upsert 완료.")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
