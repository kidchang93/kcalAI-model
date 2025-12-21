# Hugging Face 이미지 분류 파이프라인(음식 특화 모델)
import io
from cProfile import label

from PIL import Image
from transformers import pipeline
from ultralytics.models import YOLO

from schemas.predict_schema import PredictionResponse, Prediction

# classifier = pipeline(
#     "image-classification",
#     model="nateraw/food",
# )
#
# def predict_image(image_bytes: bytes):
#     image = Image.open(io.BytesIO(image_bytes))
#     results = classifier(image)
#
#     return [{"label": r["label"], "score": r["score"]} for r in results[:3]]

model = YOLO("runs/classify/s3_korean_food_all_classes_v2/weights/last.pt")

def predict_image(image_bytes: bytes) -> PredictionResponse:
    # byte Image 를 다시 컨버팅한다. 다른 형식들로 인해 발생되는 오류 방지
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    result = model(image)
    probs = result[0].probs

    # 상위 3개 예측
    top3_indices = probs.top5[:3]
    top3_names = [result[0].names[int(i)] for i in top3_indices]
    top3_confs = [float(probs.data[int(i)].item()) for i in top3_indices]

    # # Top-1 인덱스
    # top1_idx = probs.top1
    #
    # # Top-1 클래스명
    # label = result[0].names[top1_idx]
    #
    # # Top-1 confidence
    # confidence = float(probs.top1conf)
    # Response 타입 명시 하지 않았을때.
    # predictions = [{"label": n, "score": c} for n, c in zip(top3_names, top3_confs)]
    # Response 타입 명시 했을 때.
    predictions = [Prediction(label=n, score=c) for n, c in zip(top3_names,top3_confs)]
    return predictions