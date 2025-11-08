from .predict_api import router as predict_router
from .file_upload_apy import router as file_upload_router

__all__ = ["predict_router", "file_upload_router"]