import os
import logging
import uuid
from typing import Optional
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

logger = logging.getLogger(__name__)


class S3Service:
    """네이버 클라우드 플랫폼 Object Storage 업로드 서비스 클래스"""

    def __init__(self):
        """S3 클라이언트 초기화 (네이버 클라우드 플랫폼 Object Storage)"""
        self.access_key = os.getenv("ACCESS_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.region = os.getenv("REGION")
        self.bucket_name = os.getenv("BUKET_NAME")
        self.endpoint_url = os.getenv("DOMAIN")

        if not all([self.access_key, self.secret_key, self.bucket_name]):
            raise ValueError(
                "NCP credentials and bucket name must be set in environment variables (ACCESS_KEY, SECRET_KEY, BUKET_NAME)"
            )

        # 네이버 클라우드 플랫폼 Object Storage 클라이언트 생성
        # AWS Signature Version 4 인증 사용
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        )

    def upload_file(
        self,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> dict:
        """
        로컬 파일을 S3에 업로드
        
        파일은 foods/{상위폴더명}/{UUID}_{파일명} 형식으로 저장됩니다.
        UUID 8자리를 파일명 앞에 추가하여 중복을 방지합니다.

        Args:
            file_path: 업로드할 로컬 파일 경로
            content_type: 파일의 MIME 타입

        Returns:
            업로드된 파일 정보를 담은 딕셔너리
            - original_filename: 원본 파일명
            - unique_filename: UUID가 추가된 유니크 파일명

        Raises:
            FileNotFoundError: 파일이 존재하지 않을 경우
            ClientError: S3 업로드 중 오류 발생 시
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # 파일명과 상위 폴더명 추출
        filename = os.path.basename(file_path)
        parent_folder = os.path.basename(os.path.dirname(file_path))
        
        # 유니크한 식별자 생성 (UUID 8자리)
        short_uuid = str(uuid.uuid4())[:8]
        unique_filename = f"{short_uuid}_{filename}"
        
        # S3 키 생성: foods/{상위폴더명}/{UUID}_{파일명}
        s3_key = f"foods/{parent_folder}/{unique_filename}"

        try:
            # 파일 업로드
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type

            self.s3_client.upload_file(
                file_path, self.bucket_name, s3_key, ExtraArgs=extra_args
            )

            # 업로드된 파일 URL 생성
            file_url = f"{self.endpoint_url}/{self.bucket_name}/{s3_key}"

            logger.info(f"Successfully uploaded {file_path} to s3://{self.bucket_name}/{s3_key}")

            return {
                "success": True,
                "bucket": self.bucket_name,
                "key": s3_key,
                "url": file_url,
                "region": self.region,
                "original_filename": filename,
                "unique_filename": unique_filename,
            }

        except ClientError as e:
            logger.error(f"Failed to upload file to S3: {e}")
            raise

    def upload_fileobj(
        self,
        file_obj,
        filename: str,
        parent_folder: str,
        content_type: Optional[str] = None,
    ) -> dict:
        """
        파일 객체를 S3에 업로드
        
        파일은 foods/{상위폴더명}/{UUID}_{파일명} 형식으로 저장됩니다.
        UUID 8자리를 파일명 앞에 추가하여 중복을 방지합니다.

        Args:
            file_obj: 업로드할 파일 객체 (BytesIO 또는 파일 핸들)
            filename: 파일명
            parent_folder: 상위 폴더명
            content_type: 파일의 MIME 타입

        Returns:
            업로드된 파일 정보를 담은 딕셔너리
            - original_filename: 원본 파일명
            - unique_filename: UUID가 추가된 유니크 파일명

        Raises:
            ClientError: S3 업로드 중 오류 발생 시
        """
  
        # 유니크한 식별자 생성 (UUID 8자리)
        short_uuid = str(uuid.uuid4())[:8]
        unique_filename = f"{short_uuid}_{filename}"
        
        # S3 키 생성: foods/{상위폴더명}/{UUID}_{파일명}
        s3_key = f"foods/{parent_folder}/{unique_filename}"
        
        try:
            # 파일 객체 업로드
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type

            self.s3_client.upload_fileobj(
                file_obj, self.bucket_name, s3_key, ExtraArgs=extra_args
            )

            # 업로드된 파일 URL 생성
            file_url = f"{self.endpoint_url}/{self.bucket_name}/{s3_key}"

            logger.info(f"Successfully uploaded file object to s3://{self.bucket_name}/{s3_key}")

            return {
                "success": True,
                "bucket": self.bucket_name,
                "key": s3_key,
                "url": file_url,
                "region": self.region,
                "original_filename": filename,
                "unique_filename": unique_filename,
            }

        except ClientError as e:
            logger.error(f"Failed to upload file object to S3: {e}")
            raise

    def delete_file(self, s3_key: str) -> bool:
        """
        S3에서 파일 삭제

        Args:
            s3_key: 삭제할 파일의 S3 키

        Returns:
            삭제 성공 여부

        Raises:
            ClientError: S3 삭제 중 오류 발생 시
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Successfully deleted s3://{self.bucket_name}/{s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete file from S3: {e}")
            raise

    def delete_prefix(self, prefix: str) -> dict:
        """
        S3에서 특정 prefix(폴더)의 모든 객체 삭제
        
        Args:
            prefix: 삭제할 prefix (예: "foods/가지볶음/", "foods/가지볶음")
            
        Returns:
            삭제 결과 정보를 담은 딕셔너리
            
        Raises:
            ClientError: S3 삭제 중 오류 발생 시
        """
        # prefix가 슬래시로 끝나지 않으면 추가
        if prefix and not prefix.endswith('/'):
            prefix = prefix + '/'
        
        deleted_count = 0
        failed_count = 0
        deleted_keys = []
        failed_keys = []
        
        try:
            # 해당 prefix의 모든 객체 조회
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)
            
            for page in pages:
                objects = page.get('Contents', [])
                
                if not objects:
                    logger.info(f"No objects found with prefix: {prefix}")
                    break
                
                # 삭제할 객체 리스트 구성 (최대 1000개씩)
                delete_keys = [{'Key': obj['Key']} for obj in objects]
                
                # 일괄 삭제 실행
                response = self.s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={'Objects': delete_keys}
                )
                
                # 삭제 성공한 객체들
                for deleted in response.get('Deleted', []):
                    deleted_count += 1
                    deleted_keys.append(deleted['Key'])
                    logger.info(f"Deleted: s3://{self.bucket_name}/{deleted['Key']}")
                
                # 삭제 실패한 객체들
                for error in response.get('Errors', []):
                    failed_count += 1
                    failed_keys.append({
                        'key': error['Key'],
                        'code': error['Code'],
                        'message': error['Message']
                    })
                    logger.error(f"Failed to delete {error['Key']}: {error['Message']}")
            
            logger.info(
                f"Deleted {deleted_count} objects with prefix '{prefix}' "
                f"({failed_count} failures)"
            )
            
            return {
                'success': failed_count == 0,
                'prefix': prefix,
                'deleted_count': deleted_count,
                'failed_count': failed_count,
                'deleted_keys': deleted_keys,
                'failed_keys': failed_keys,
            }
            
        except ClientError as e:
            logger.error(f"Failed to delete objects with prefix {prefix}: {e}")
            raise

    def file_exists(self, s3_key: str) -> bool:
        """
        S3에 파일이 존재하는지 확인

        Args:
            s3_key: 확인할 파일의 S3 키

        Returns:
            파일 존재 여부
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError:
            return False

    def upload_directory(
        self,
        directory_path: str,
        recursive: bool = True,
        content_type: Optional[str] = None,
    ) -> dict:
        """
        디렉토리 내의 모든 파일을 S3에 업로드
        
        Args:
            directory_path: 업로드할 디렉토리 경로
            recursive: 하위 폴더도 포함할지 여부 (기본값: True)
            content_type: 파일의 MIME 타입

        Returns:
            업로드 결과 정보를 담은 딕셔너리

        Raises:
            FileNotFoundError: 디렉토리가 존재하지 않을 경우
            ClientError: S3 업로드 중 오류 발생 시
        """
        if not os.path.exists(directory_path):
            raise FileNotFoundError(f"Directory not found: {directory_path}")
        
        if not os.path.isdir(directory_path):
            raise ValueError(f"Path is not a directory: {directory_path}")

        uploaded_files = []
        failed_files = []
        
        # 디렉토리 내 파일 목록 가져오기
        if recursive:
            # 재귀적으로 모든 파일 찾기
            for root, dirs, files in os.walk(directory_path):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    try:
                        result = self.upload_file(file_path, content_type)
                        uploaded_files.append({
                            "file_path": file_path,
                            "s3_key": result["key"],
                            "url": result["url"]
                        })
                        logger.info(f"Uploaded: {file_path} -> {result['key']}")
                    except Exception as e:
                        failed_files.append({
                            "file_path": file_path,
                            "error": str(e)
                        })
                        logger.error(f"Failed to upload {file_path}: {e}")
        else:
            # 현재 디렉토리의 파일만
            for filename in os.listdir(directory_path):
                file_path = os.path.join(directory_path, filename)
                if os.path.isfile(file_path):
                    try:
                        result = self.upload_file(file_path, content_type)
                        uploaded_files.append({
                            "file_path": file_path,
                            "s3_key": result["key"],
                            "url": result["url"]
                        })
                        logger.info(f"Uploaded: {file_path} -> {result['key']}")
                    except Exception as e:
                        failed_files.append({
                            "file_path": file_path,
                            "error": str(e)
                        })
                        logger.error(f"Failed to upload {file_path}: {e}")

        return {
            "success": len(failed_files) == 0,
            "total_files": len(uploaded_files) + len(failed_files),
            "uploaded_count": len(uploaded_files),
            "failed_count": len(failed_files),
            "uploaded_files": uploaded_files,
            "failed_files": failed_files,
        }

    def get_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """
        S3 파일에 대한 presigned URL 생성

        Args:
            s3_key: S3 파일 키
            expiration: URL 만료 시간(초), 기본값 1시간

        Returns:
            presigned URL 문자열

        Raises:
            ClientError: URL 생성 중 오류 발생 시
        """
        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise

    def list_buckets(self) -> list:
        """
        모든 버킷 목록 조회

        Returns:
            버킷 정보 리스트

        Raises:
            ClientError: 버킷 목록 조회 중 오류 발생 시
        """
        try:
            response = self.s3_client.list_buckets()
            buckets = []
            for bucket in response.get('Buckets', []):
                buckets.append({
                    'name': bucket['Name'],
                    'creation_date': bucket['CreationDate'].isoformat()
                })
            logger.info(f"Found {len(buckets)} buckets")
            return buckets
        except ClientError as e:
            logger.error(f"Failed to list buckets: {e}")
            raise

    def list_objects(
        self,
        prefix: str = "",
        delimiter: str = "",
        max_keys: int = 1000,
    ) -> dict:
        """
        버킷 내 객체 목록 조회
        
        Args:
            prefix: 객체 키의 접두사 (예: "foods/", "foods/images/")
            delimiter: 구분자 (기본값: ""). "/"를 사용하면 폴더 구조처럼 표시
            max_keys: 반환할 최대 객체 수 (기본값: 1000)

        Returns:
            객체 및 폴더 정보를 담은 딕셔너리

        Raises:
            ClientError: 객체 목록 조회 중 오류 발생 시
        """
        try:
            # list_objects_v2 파라미터 구성
            params = {
                'Bucket': self.bucket_name,
                'MaxKeys': max_keys,
            }
            
            if prefix:
                params['Prefix'] = prefix
            
            if delimiter:
                params['Delimiter'] = delimiter
            
            response = self.s3_client.list_objects_v2(**params)
            
            # 파일 목록
            files = []
            for obj in response.get('Contents', []):
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                    'storage_class': obj.get('StorageClass', 'STANDARD'),
                })
            
            # 폴더 목록 (CommonPrefixes)
            folders = []
            for prefix_obj in response.get('CommonPrefixes', []):
                folders.append({
                    'prefix': prefix_obj['Prefix'],
                })
            
            result = {
                'bucket': self.bucket_name,
                'prefix': prefix,
                'delimiter': delimiter,
                'file_count': len(files),
                'folder_count': len(folders),
                'files': files,
                'folders': folders,
                'is_truncated': response.get('IsTruncated', False),
                'max_keys': max_keys,
            }
            
            logger.info(
                f"Listed objects in s3://{self.bucket_name}/{prefix} - "
                f"{len(files)} files, {len(folders)} folders"
            )
            
            return result
            
        except ClientError as e:
            logger.error(f"Failed to list objects: {e}")
            raise


# 싱글톤 인스턴스
_s3_service_instance = None


def get_s3_service() -> S3Service:
    """S3 서비스 싱글톤 인스턴스 반환"""
    global _s3_service_instance
    if _s3_service_instance is None:
        _s3_service_instance = S3Service()
    return _s3_service_instance

