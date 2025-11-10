from typing import Optional
from pydantic import BaseModel, Field


class S3UploadResponse(BaseModel):
    """S3 업로드 성공 응답 스키마"""

    success: bool = Field(..., description="업로드 성공 여부")
    bucket: str = Field(..., description="S3 버킷 이름")
    key: str = Field(..., description="S3 객체 키")
    url: str = Field(..., description="업로드된 파일의 URL")
    region: str = Field(..., description="AWS 리전")
    filename: str = Field(..., description="원본 파일명")
    size: Optional[int] = Field(None, description="파일 크기(바이트)")
    content_type: Optional[str] = Field(None, description="파일 MIME 타입")


class S3ErrorResponse(BaseModel):
    """S3 업로드 실패 응답 스키마"""

    success: bool = Field(False, description="업로드 실패")
    error: str = Field(..., description="오류 메시지")
    detail: Optional[str] = Field(None, description="상세 오류 정보")


class LocalFileUploadRequest(BaseModel):
    """로컬 파일 업로드 요청 스키마"""

    file_path: str = Field(
        ..., 
        description="업로드할 로컬 파일 경로",
        example="D:/data/images/photo.jpg"
    )
    content_type: Optional[str] = Field(
        default=None, 
        description="파일 MIME 타입 (예: image/jpeg)",
        example="image/jpeg"
    )


class S3DeleteResponse(BaseModel):
    """S3 파일 삭제 응답 스키마"""

    success: bool = Field(..., description="삭제 성공 여부")
    key: str = Field(..., description="삭제된 파일의 S3 키")
    message: str = Field(..., description="결과 메시지")


class DeletedKeyInfo(BaseModel):
    """삭제된 키 정보"""

    key: str = Field(..., description="삭제된 객체 키")
    code: str = Field(..., description="오류 코드")
    message: str = Field(..., description="오류 메시지")


class PrefixDeleteResponse(BaseModel):
    """Prefix 일괄 삭제 응답 스키마"""

    success: bool = Field(..., description="전체 삭제 성공 여부")
    prefix: str = Field(..., description="삭제된 prefix")
    deleted_count: int = Field(..., description="삭제된 파일 수")
    failed_count: int = Field(..., description="삭제 실패 파일 수")
    deleted_keys: list[str] = Field(..., description="삭제된 파일 키 목록")
    failed_keys: list = Field(..., description="삭제 실패 파일 정보")


class DirectoryUploadRequest(BaseModel):
    """디렉토리 업로드 요청 스키마"""

    directory_path: str = Field(..., description="업로드할 디렉토리 경로", example="D:/lck_data/dataset/foods")
    recursive: bool = Field(True, description="하위 폴더 포함 여부")
    content_type: Optional[str] = Field(
        default=None,
        description="파일 MIME 타입 (null일 경우 자동 감지)",
        example=None
    )


class UploadedFileInfo(BaseModel):
    """업로드된 파일 정보"""

    file_path: str = Field(..., description="로컬 파일 경로")
    s3_key: str = Field(..., description="S3 키")
    url: str = Field(..., description="파일 URL")


class FailedFileInfo(BaseModel):
    """업로드 실패 파일 정보"""

    file_path: str = Field(..., description="로컬 파일 경로")
    error: str = Field(..., description="오류 메시지")


class DirectoryUploadResponse(BaseModel):
    """디렉토리 업로드 응답 스키마"""

    success: bool = Field(..., description="전체 업로드 성공 여부")
    total_files: int = Field(..., description="총 파일 수")
    uploaded_count: int = Field(..., description="업로드 성공 파일 수")
    failed_count: int = Field(..., description="업로드 실패 파일 수")
    uploaded_files: list[UploadedFileInfo] = Field(..., description="업로드 성공 파일 목록")
    failed_files: list[FailedFileInfo] = Field(..., description="업로드 실패 파일 목록")


class BucketInfo(BaseModel):
    """버킷 정보 스키마"""

    name: str = Field(..., description="버킷 이름")
    creation_date: str = Field(..., description="버킷 생성 날짜")


class BucketListResponse(BaseModel):
    """버킷 목록 응답 스키마"""

    success: bool = Field(..., description="조회 성공 여부")
    bucket_count: int = Field(..., description="버킷 개수")
    buckets: list[BucketInfo] = Field(..., description="버킷 목록")


class ObjectInfo(BaseModel):
    """객체(파일) 정보 스키마"""

    key: str = Field(..., description="객체 키 (전체 경로)")
    size: int = Field(..., description="파일 크기 (바이트)")
    last_modified: str = Field(..., description="마지막 수정 시간")
    storage_class: str = Field(..., description="스토리지 클래스")


class FolderInfo(BaseModel):
    """폴더 정보 스키마"""

    prefix: str = Field(..., description="폴더 경로 (접두사)")


class ObjectListResponse(BaseModel):
    """객체 목록 응답 스키마"""

    success: bool = Field(..., description="조회 성공 여부")
    bucket: str = Field(..., description="버킷 이름")
    prefix: str = Field(..., description="검색 접두사")
    delimiter: str = Field(..., description="구분자")
    file_count: int = Field(..., description="파일 개수")
    folder_count: int = Field(..., description="폴더 개수")
    files: list[ObjectInfo] = Field(..., description="파일 목록")
    folders: list[FolderInfo] = Field(..., description="폴더 목록")
    is_truncated: bool = Field(..., description="결과가 잘렸는지 여부")
    max_keys: int = Field(..., description="최대 키 개수")

