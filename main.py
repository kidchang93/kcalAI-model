
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import predict_router, file_upload_router

app = FastAPI(
    title="Food Classification API",
    description="음식 이미지를 분류하는 API",
    version="1.0.0",
)

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

# 라우터 등록
app.include_router(predict_router, prefix="/api", tags=["Predict"])
app.include_router(file_upload_router, prefix="/api/s3", tags=["S3 Upload"])
