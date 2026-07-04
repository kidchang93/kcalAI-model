import io
import os

from PIL import Image
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from transformers import pipeline

from api import auth_router
from database import init_db

app = FastAPI()

cors_allow_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Hugging Face 이미지 분류 파이프라인(음식 특화 모델)
classifier = pipeline(
    "image-classification",
    model="nateraw/food",
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    try:
        # 이미지 파일 읽기
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))

        # 모델 예측
        results = classifier(image)

        return JSONResponse(content={"predictions": results[:3]})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


app.include_router(auth_router, prefix="/api", tags=["Auth"])
