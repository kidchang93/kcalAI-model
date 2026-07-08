import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, HTTPException, File, Form
from fastapi.responses import JSONResponse, StreamingResponse

from log_utils import setup_level_logger
from schemas.s3_schemas import (
    S3UploadResponse,
    S3ErrorResponse,
    LocalFileUploadRequest,
    S3DeleteResponse,
    PrefixDeleteResponse,
    DirectoryUploadRequest,
    DirectoryUploadResponse,
    BucketListResponse,
    ObjectListResponse,
)
from services.s3_service import get_s3_service

# setup_level_logger 는 LevelFilter 로 해당 레벨만 기록한다.
# INFO 로거로 error() 를 호출하면 레코드가 버려지므로 레벨별로 따로 만든다.
info_logger = setup_level_logger(logging.INFO)
error_logger = setup_level_logger(logging.ERROR)

router = APIRouter()


@router.post(
    "/upload/file",
    response_model=S3UploadResponse,
    responses={500: {"model": S3ErrorResponse}},
    summary="파일 객체를 S3에 업로드",
    description="업로드된 파일을 네이버 클라우드 Object Storage에 저장합니다. PATH/{폴더명}/{파일명} 형식으로 저장됩니다.",
)
async def upload_file_to_s3(
    file: UploadFile = File(..., description="업로드할 파일"),
    parent_folder: str = Form(..., description="상위 폴더명 (예: images, documents)"),
):
    """
    파일 객체를 S3에 업로드하는 API 엔드포인트

    Args:
        file: 업로드할 파일
        parent_folder: 상위 폴더명

    Returns:
        S3UploadResponse: 업로드 결과 정보
    """
    try:
        # S3 서비스 인스턴스 가져오기
        s3_service = get_s3_service()

        # 파일 내용 읽기
        file_content = await file.read()
        file_size = len(file_content)

        # BytesIO로 변환하여 업로드
        from io import BytesIO

        file_obj = BytesIO(file_content)

        # S3에 업로드
        result = s3_service.upload_fileobj(
            file_obj=file_obj,
            filename=file.filename,
            parent_folder=parent_folder,
            content_type=file.content_type,
        )

        info_logger.info(
            f"File uploaded successfully: {file.filename} -> s3://{result['bucket']}/{result['key']}"
        )

        # 응답 생성
        return S3UploadResponse(
            success=result["success"],
            bucket=result["bucket"],
            key=result["key"],
            url=result["url"],
            region=result["region"],
            filename=file.filename,
            size=file_size,
            content_type=file.content_type,
        )

    except ValueError as e:
        error_logger.error(f"Configuration error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"설정 오류: {str(e)}")
    except Exception as e:
        error_logger.error(f"Failed to upload file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"파일 업로드 실패: {str(e)}")


@router.post(
    "/upload/local-file",
    response_model=S3UploadResponse,
    responses={404: {"model": S3ErrorResponse}, 500: {"model": S3ErrorResponse}},
    summary="로컬 파일을 S3에 업로드",
    description="서버의 로컬 파일 시스템에 있는 파일을 네이버 클라우드 Object Storage에 업로드합니다. PATH/{상위폴더명}/{파일명} 형식으로 자동 저장됩니다.",
)
async def upload_local_file_to_s3(request: LocalFileUploadRequest):
    """
    로컬 파일 시스템의 파일을 S3에 업로드하는 API 엔드포인트
    
    파일 경로에서 상위 폴더명을 자동으로 추출하여 PATH/{상위폴더명}/{파일명} 형식으로 저장됩니다.

    Args:
        request: 로컬 파일 업로드 요청 (file_path, content_type)

    Returns:
        S3UploadResponse: 업로드 결과 정보
    """
    try:
        # 파일 존재 확인
        if not os.path.exists(request.file_path):
            raise HTTPException(
                status_code=404, detail=f"파일을 찾을 수 없습니다: {request.file_path}"
            )

        # S3 서비스 인스턴스 가져오기
        s3_service = get_s3_service()

        # 파일 크기 확인
        file_size = os.path.getsize(request.file_path)

        # S3에 업로드
        result = s3_service.upload_file(
            file_path=request.file_path,
            content_type=request.content_type,
        )

        filename = os.path.basename(request.file_path)

        info_logger.info(
            f"Local file uploaded successfully: {request.file_path} -> s3://{result['bucket']}/{result['key']}"
        )

        # 응답 생성
        return S3UploadResponse(
            success=result["success"],
            bucket=result["bucket"],
            key=result["key"],
            url=result["url"],
            region=result["region"],
            filename=filename,
            size=file_size,
            content_type=request.content_type,
        )

    except HTTPException:
        raise
    except ValueError as e:
        error_logger.error(f"Configuration error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"설정 오류: {str(e)}")
    except Exception as e:
        error_logger.error(f"Failed to upload local file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"로컬 파일 업로드 실패: {str(e)}")


@router.delete(
    "/delete/{s3_key:path}",
    response_model=S3DeleteResponse,
    responses={500: {"model": S3ErrorResponse}},
    summary="S3에서 파일 삭제",
    description="AWS S3 버킷에서 지정된 파일을 삭제합니다.",
)
async def delete_file_from_s3(s3_key: str):
    """
    S3에서 파일을 삭제하는 API 엔드포인트

    Args:
        s3_key: 삭제할 파일의 S3 키

    Returns:
        S3DeleteResponse: 삭제 결과 정보
    """
    try:
        # S3 서비스 인스턴스 가져오기
        s3_service = get_s3_service()

        # 파일 존재 확인
        if not s3_service.file_exists(s3_key):
            raise HTTPException(
                status_code=404, detail=f"S3에 파일이 존재하지 않습니다: {s3_key}"
            )

        # 파일 삭제
        s3_service.delete_file(s3_key)

        info_logger.info(f"File deleted successfully from S3: {s3_key}")

        return S3DeleteResponse(
            success=True, key=s3_key, message="파일이 성공적으로 삭제되었습니다."
        )

    except HTTPException:
        raise
    except Exception as e:
        error_logger.error(f"Failed to delete file from S3: {str(e)}")
        raise HTTPException(status_code=500, detail=f"파일 삭제 실패: {str(e)}")


@router.delete(
    "/delete-prefix/{prefix:path}",
    response_model=PrefixDeleteResponse,
    responses={500: {"model": S3ErrorResponse}},
    summary="S3에서 특정 prefix(폴더)의 모든 파일 삭제",
    description="S3 버킷의 특정 prefix(폴더)에 있는 모든 객체를 일괄 삭제합니다. 예: foods/가지볶음",
)
async def delete_prefix_from_s3(prefix: str):
    """
    S3에서 특정 prefix(폴더)의 모든 파일을 삭제하는 API 엔드포인트

    Args:
        prefix: 삭제할 prefix (예: "foods/가지볶음", "foods/가지볶음/")

    Returns:
        PrefixDeleteResponse: 삭제 결과 정보
    """
    try:
        # S3 서비스 인스턴스 가져오기
        s3_service = get_s3_service()

        info_logger.info(f"Starting prefix deletion: {prefix}")

        # prefix의 모든 객체 삭제
        result = s3_service.delete_prefix(prefix)

        info_logger.info(
            f"Prefix deletion completed: {result['deleted_count']} deleted, "
            f"{result['failed_count']} failed"
        )

        return PrefixDeleteResponse(**result)

    except Exception as e:
        error_logger.error(f"Failed to delete prefix from S3: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Prefix 삭제 실패: {str(e)}")


@router.post(
    "/upload/directory",
    responses={404: {"model": S3ErrorResponse}, 500: {"model": S3ErrorResponse}},
    summary="디렉토리 내 모든 파일을 S3에 업로드 (스트리밍)",
    description="지정된 디렉토리 내의 모든 파일을 네이버 클라우드 Object Storage에 업로드합니다. 각 파일 업로드마다 실시간으로 진행 상황을 스트리밍합니다.",
)
async def upload_directory_to_s3(request: DirectoryUploadRequest):
    """
    디렉토리 내 모든 파일을 S3에 업로드하는 API 엔드포인트 (스트리밍 방식)
    
    대용량 파일 업로드 시 타임아웃을 방지하기 위해 각 파일 업로드마다 
    진행 상황을 JSON Lines 형식으로 스트리밍합니다.

    Args:
        request: 디렉토리 업로드 요청 (directory_path, recursive, content_type)

    Returns:
        StreamingResponse: 각 파일 업로드마다 JSON 응답을 스트리밍
    """
    # 디렉토리 존재 확인
    if not os.path.exists(request.directory_path):
        raise HTTPException(
            status_code=404, detail=f"디렉토리를 찾을 수 없습니다: {request.directory_path}"
        )

    if not os.path.isdir(request.directory_path):
        raise HTTPException(
            status_code=400, detail=f"경로가 디렉토리가 아닙니다: {request.directory_path}"
        )

    async def generate_upload_stream():
        """각 파일 업로드마다 진행 상황을 yield하는 제너레이터"""
        try:
            # S3 서비스 인스턴스 가져오기
            s3_service = get_s3_service()

            info_logger.info(
                f"Starting directory upload: {request.directory_path} (recursive={request.recursive})"
            )

            # 시작 메시지 전송
            start_message = {
                "status": "started",
                "message": f"디렉토리 업로드 시작: {request.directory_path}",
                "timestamp": datetime.now().isoformat(),
            }
            yield json.dumps(start_message, ensure_ascii=False) + "\n"

            # 파일 목록 수집
            file_list = []
            if request.recursive:
                for root, dirs, files in os.walk(request.directory_path):
                    for filename in files:
                        file_path = os.path.join(root, filename)
                        file_list.append(file_path)
            else:
                for filename in os.listdir(request.directory_path):
                    file_path = os.path.join(request.directory_path, filename)
                    if os.path.isfile(file_path):
                        file_list.append(file_path)

            total_files = len(file_list)
            uploaded_count = 0
            failed_count = 0

            # 전체 파일 수 전송
            total_message = {
                "status": "info",
                "message": f"총 {total_files}개 파일 발견",
                "total_files": total_files,
                "timestamp": datetime.now().isoformat(),
            }
            yield json.dumps(total_message, ensure_ascii=False) + "\n"

            # 각 파일 업로드 처리
            for index, file_path in enumerate(file_list, 1):
                try:
                    # 파일 업로드
                    result = s3_service.upload_file(file_path, request.content_type)
                    uploaded_count += 1

                    # 성공 메시지 전송
                    success_message = {
                        "status": "success",
                        "message": f"업로드 성공: {os.path.basename(file_path)}",
                        "file_path": file_path,
                        "s3_key": result["key"],
                        "url": result["url"],
                        "progress": {
                            "current": index,
                            "total": total_files,
                            "percentage": round((index / total_files) * 100, 2),
                        },
                        "timestamp": datetime.now().isoformat(),
                    }
                    yield json.dumps(success_message, ensure_ascii=False) + "\n"
                    
                    info_logger.info(f"[{index}/{total_files}] Uploaded: {file_path} -> {result['key']}")

                except Exception as e:
                    failed_count += 1

                    # 실패 메시지 전송
                    error_message = {
                        "status": "error",
                        "message": f"업로드 실패: {os.path.basename(file_path)}",
                        "file_path": file_path,
                        "error": str(e),
                        "progress": {
                            "current": index,
                            "total": total_files,
                            "percentage": round((index / total_files) * 100, 2),
                        },
                        "timestamp": datetime.now().isoformat(),
                    }
                    yield json.dumps(error_message, ensure_ascii=False) + "\n"
                    
                    error_logger.error(f"[{index}/{total_files}] Failed to upload {file_path}: {e}")

            # 완료 메시지 전송 (대용량 응답 방지를 위해 파일 목록은 제외하고 통계만 반환)
            completion_message = {
                "status": "completed",
                "message": "디렉토리 업로드 완료",
                "summary": {
                    "total_files": total_files,
                    "uploaded_count": uploaded_count,
                    "failed_count": failed_count,
                    "success_rate": round((uploaded_count / total_files) * 100, 2) if total_files > 0 else 0,
                },
                "timestamp": datetime.now().isoformat(),
            }
            yield json.dumps(completion_message, ensure_ascii=False) + "\n"

            info_logger.info(
                f"Directory upload completed: {uploaded_count}/{total_files} files uploaded successfully"
            )

        except Exception as e:
            # 전체 프로세스 실패 메시지
            error_message = {
                "status": "fatal_error",
                "message": f"디렉토리 업로드 중 치명적 오류 발생: {str(e)}",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }
            yield json.dumps(error_message, ensure_ascii=False) + "\n"
            error_logger.error(f"Fatal error during directory upload: {str(e)}")

    return StreamingResponse(
        generate_upload_stream(),
        media_type="application/x-ndjson",  # JSON Lines 형식
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 버퍼링 비활성화
        },
    )


@router.get(
    "/presigned-url/{s3_key:path}",
    summary="Presigned URL 생성",
    description="S3 파일에 대한 임시 접근 URL을 생성합니다.",
)
async def get_presigned_url(s3_key: str, expiration: int = 3600):
    """
    S3 파일에 대한 presigned URL을 생성하는 API 엔드포인트

    Args:
        s3_key: S3 파일 키
        expiration: URL 만료 시간(초), 기본값 1시간

    Returns:
        presigned URL 정보
    """
    try:
        # S3 서비스 인스턴스 가져오기
        s3_service = get_s3_service()

        # presigned URL 생성
        url = s3_service.get_presigned_url(s3_key, expiration)

        info_logger.info(f"Presigned URL generated for: {s3_key}")

        return {
            "success": True,
            "key": s3_key,
            "url": url,
            "expiration_seconds": expiration,
        }

    except Exception as e:
        error_logger.error(f"Failed to generate presigned URL: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Presigned URL 생성 실패: {str(e)}")


@router.get(
    "/buckets",
    response_model=BucketListResponse,
    responses={500: {"model": S3ErrorResponse}},
    summary="버킷 목록 조회",
    description="네이버 클라우드 플랫폼 Object Storage의 모든 버킷 목록을 조회합니다.",
)
async def list_buckets():
    """
    버킷 목록을 조회하는 API 엔드포인트

    Returns:
        BucketListResponse: 버킷 목록 정보
    """
    try:
        # S3 서비스 인스턴스 가져오기 (BUCKET_NAME 검증 없이)
        # 버킷 목록 조회를 위해 임시로 클라이언트만 사용
        from services.s3_service import S3Service
        import os
        from dotenv import load_dotenv
        import boto3
        
        load_dotenv()
        
        access_key = os.getenv("ACCESS_KEY")
        secret_key = os.getenv("SECRET_KEY")
        region = os.getenv("REGION")
        endpoint_url = os.getenv("DOMAIN")

        if not all([access_key, secret_key]):
            raise HTTPException(
                status_code=500,
                detail="ACCESS_KEY와 SECRET_KEY가 환경 변수에 설정되어야 합니다."
            )
        
        # 임시 S3 클라이언트 생성 (버킷 이름 불필요)
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            endpoint_url=endpoint_url,
        )
        
        # 버킷 목록 조회
        response = s3_client.list_buckets()
        buckets = []
        for bucket in response.get('Buckets', []):
            buckets.append({
                'name': bucket['Name'],
                'creation_date': bucket['CreationDate'].isoformat()
            })
        
        info_logger.info(f"Successfully retrieved {len(buckets)} buckets")
        
        return BucketListResponse(
            success=True,
            bucket_count=len(buckets),
            buckets=buckets
        )

    except HTTPException:
        raise
    except Exception as e:
        error_logger.error(f"Failed to list buckets: {str(e)}")
        raise HTTPException(status_code=500, detail=f"버킷 목록 조회 실패: {str(e)}")


@router.get(
    "/objects",
    response_model=ObjectListResponse,
    responses={500: {"model": S3ErrorResponse}},
    summary="버킷 내 객체 목록 조회",
    description="버킷 내의 파일과 폴더 구조를 조회합니다. prefix와 delimiter를 사용하여 특정 경로의 객체만 조회할 수 있습니다.",
)
async def list_objects(
    prefix: str = "",
    delimiter: str = "/",
    max_keys: int = 1000,
):
    """
    버킷 내 객체(파일) 목록을 조회하는 API 엔드포인트

    Args:
        prefix: 객체 키의 접두사 (예: "foods/", "foods/images/")
        delimiter: 구분자 (기본값: "/"). "/"를 사용하면 폴더 구조처럼 표시
        max_keys: 반환할 최대 객체 수 (기본값: 1000)

    Returns:
        ObjectListResponse: 객체 및 폴더 목록 정보
    """
    try:
        # S3 서비스 인스턴스 가져오기
        s3_service = get_s3_service()

        # 객체 목록 조회
        info_logger.info(f"Listing objects with prefix='{prefix}', delimiter='{delimiter}'")
        
        result = s3_service.list_objects(
            prefix=prefix,
            delimiter=delimiter,
            max_keys=max_keys,
        )

        info_logger.info(
            f"Successfully listed objects: {result['file_count']} files, "
            f"{result['folder_count']} folders"
        )

        return ObjectListResponse(
            success=True,
            bucket=result['bucket'],
            prefix=result['prefix'],
            delimiter=result['delimiter'],
            file_count=result['file_count'],
            folder_count=result['folder_count'],
            files=result['files'],
            folders=result['folders'],
            is_truncated=result['is_truncated'],
            max_keys=result['max_keys'],
        )

    except ValueError as e:
        error_logger.error(f"Configuration error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"설정 오류: {str(e)}")
    except Exception as e:
        error_logger.error(f"Failed to list objects: {str(e)}")
        raise HTTPException(status_code=500, detail=f"객체 목록 조회 실패: {str(e)}")
