# Hugging Face 이미지 분류 파이프라인(음식 특화 모델)
import io

from PIL import Image
from transformers import pipeline

classifier = pipeline(
    "image-classification",
    model="nateraw/food",
)

def predict_image(image_bytes: bytes):
    image = Image.open(io.BytesIO(image_bytes))
    results = classifier(image)

    return [{"label": r["label"], "score": r["score"]} for r in results[:3]]