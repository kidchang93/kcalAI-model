
from fastapi import FastAPI
from api import predict_router, file_upload_router

app = FastAPI(
    title="Food Classification API",
    description="음식 이미지를 분류하는 API",
    version="1.0.0",
)

# 라우터 등록
app.include_router(predict_router, prefix="/api", tags=["Predict"])
app.include_router(file_upload_router, prefix="/api/s3", tags=["S3 Upload"])

