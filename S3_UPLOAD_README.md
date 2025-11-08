# 네이버 클라우드 플랫폼 Object Storage 파일 업로드 API 가이드

## 개요
이 프로젝트는 네이버 클라우드 플랫폼 Object Storage에 파일을 업로드하는 FastAPI 기반 API를 제공합니다.

boto3를 사용하며 AWS Signature Version 4 인증을 지원합니다.

## 환경 설정

### 1. 의존성 패키지 설치
```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정
프로젝트 루트 디렉토리에 `.env` 파일을 생성하고 다음 내용을 추가하세요:

```env
# 네이버 클라우드 플랫폼 Object Storage 설정
ACCESS_KEY=your_ncp_access_key
SECRET_KEY=your_ncp_secret_key
REGION=kr-standard
BUKET_NAME=your_bucket_name
DOMAIN=https://kr.object.ncloudstorage.com
PATH_PREFIX=uploads

# Hugging Face Token (기존 설정)
HF_TOKEN=your_huggingface_token
```

#### 환경 변수 설명
- `ACCESS_KEY`: 네이버 클라우드 플랫폼 API 인증키 (Access Key ID)
- `SECRET_KEY`: 네이버 클라우드 플랫폼 API 인증키 (Secret Key)
- `REGION`: Object Storage 리전
- `BUKET_NAME`: 파일을 업로드할 버킷 이름
- `DOMAIN`: Object Storage 엔드포인트
- `PATH_PREFIX`: 파일 저장 기본 경로 (기본값: uploads)

### 3. 네이버 클라우드 플랫폼 인증키 발급
1. [네이버 클라우드 플랫폼 콘솔](https://console.ncloud.com)에 로그인
2. 마이페이지 > 계정 관리 > 인증키 관리
3. 신규 API 인증키 생성
4. Access Key ID와 Secret Key를 `.env` 파일에 설정

### 4. Object Storage 버킷 생성
1. 네이버 클라우드 플랫폼 콘솔 > Services > Object Storage
2. 버킷 생성
3. 버킷 이름을 `.env` 파일의 `BUKET_NAME`에 설정

## API 서버 실행

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

서버가 실행되면 다음 주소에서 API 문서를 확인할 수 있습니다:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API 엔드포인트

### 1. 파일 객체 업로드
**POST** `/api/s3/upload/file`

클라이언트에서 전송한 파일을 Object Storage에 업로드합니다.

**저장 형식**: `PATH_PREFIX/{parent_folder}/{filename}`

**요청 (Multipart Form)**
- `file`: 업로드할 파일 (필수)
- `parent_folder`: 상위 폴더명 (필수, 예: images, documents)

**응답 예시**
```json
{
  "success": true,
  "bucket": "my-bucket",
  "key": "uploads/images/photo.jpg",
  "url": "https://kr.object.ncloudstorage.com/my-bucket/uploads/images/photo.jpg",
  "region": "kr-standard",
  "filename": "photo.jpg",
  "size": 1024000,
  "content_type": "image/jpeg"
}
```

### 2. 로컬 파일 업로드
**POST** `/api/s3/upload/local-file`

서버의 로컬 파일 시스템에 있는 파일을 Object Storage에 업로드합니다.

**저장 형식**: `PATH_PREFIX/{상위폴더명}/{filename}` (파일 경로에서 자동 추출)

**예시**: `D:/data/images/photo.jpg` → `uploads/images/photo.jpg`

**요청 (JSON)**
```json
{
  "file_path": "D:/data/images/photo.jpg",
  "content_type": "image/jpeg"
}
```

**응답 예시**
```json
{
  "success": true,
  "bucket": "my-bucket",
  "key": "uploads/images/photo.jpg",
  "url": "https://kr.object.ncloudstorage.com/my-bucket/uploads/images/photo.jpg",
  "region": "kr-standard",
  "filename": "photo.jpg",
  "size": 1024000,
  "content_type": "image/jpeg"
}
```

### 3. 디렉토리 전체 업로드
**POST** `/api/s3/upload/directory`

디렉토리 내의 모든 파일을 Object Storage에 업로드합니다.

**저장 형식**: 각 파일이 `foods/{상위폴더명}/{파일명}` 형식으로 저장됩니다.

**요청 (JSON)**
```json
{
  "directory_path": "D:/data/images",
  "recursive": true,
  "content_type": null
}
```

**파라미터**:
- `directory_path`: 업로드할 디렉토리 경로 (필수)
- `recursive`: 하위 폴더 포함 여부 (기본값: true)
- `content_type`: 파일 MIME 타입 (선택)

**응답 예시**
```json
{
  "success": true,
  "total_files": 10,
  "uploaded_count": 10,
  "failed_count": 0,
  "uploaded_files": [
    {
      "file_path": "D:/data/images/photo1.jpg",
      "s3_key": "foods/images/photo1.jpg",
      "url": "https://kr.object.ncloudstorage.com/my-bucket/foods/images/photo1.jpg"
    }
  ],
  "failed_files": []
}
```

### 4. 파일 삭제
**DELETE** `/api/s3/delete/{s3_key}`

S3에서 파일을 삭제합니다.

**응답 예시**
```json
{
  "success": true,
  "key": "uploads/20250108_123456_image.jpg",
  "message": "파일이 성공적으로 삭제되었습니다."
}
```

### 5. Presigned URL 생성
**GET** `/api/s3/presigned-url/{s3_key}`

S3 파일에 대한 임시 접근 URL을 생성합니다.

**Query Parameters**
- `expiration`: URL 만료 시간(초), 기본값 3600 (1시간)

**응답 예시**
```json
{
  "success": true,
  "key": "uploads/20250108_123456_image.jpg",
  "url": "https://kr.object.ncloudstorage.com/my-bucket/uploads/20250108_123456_image.jpg?AWSAccessKeyId=...&Signature=...&Expires=...",
  "expiration_seconds": 3600
}
```

## 사용 예제

### Python을 사용한 파일 업로드

#### 1. 파일 객체 업로드 (Multipart)
```python
import requests

url = "http://localhost:8000/api/s3/upload/file"

with open("image.jpg", "rb") as f:
    files = {"file": ("image.jpg", f, "image/jpeg")}
    data = {"parent_folder": "images"}  # 폴더명 지정
    response = requests.post(url, files=files, data=data)

print(response.json())
# 결과: uploads/images/image.jpg로 저장됨
```

#### 2. 로컬 파일 경로로 업로드
```python
import requests

url = "http://localhost:8000/api/s3/upload/local-file"

# D:/data/images/photo.jpg -> foods/images/photo.jpg로 저장됨
payload = {
    "file_path": "D:/data/images/photo.jpg",
    "content_type": "image/jpeg"
}

response = requests.post(url, json=payload)
print(response.json())
```

#### 3. 디렉토리 전체 업로드
```python
import requests

url = "http://localhost:8000/api/s3/upload/directory"

# D:/data/images/ 디렉토리의 모든 파일 업로드
payload = {
    "directory_path": "D:/data/images",
    "recursive": True,  # 하위 폴더 포함
    "content_type": None
}

response = requests.post(url, json=payload)
result = response.json()

print(f"총 {result['total_files']}개 중 {result['uploaded_count']}개 업로드 성공!")
for file_info in result['uploaded_files']:
    print(f"  - {file_info['s3_key']}")
```

### cURL을 사용한 파일 업로드

#### 1. 파일 객체 업로드
```bash
curl -X POST "http://localhost:8000/api/s3/upload/file" \
  -F "file=@image.jpg" \
  -F "parent_folder=images"
```

#### 2. 로컬 파일 경로로 업로드
```bash
curl -X POST "http://localhost:8000/api/s3/upload/local-file" \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "D:/data/images/photo.jpg",
    "content_type": "image/jpeg"
  }'
```

#### 3. 디렉토리 전체 업로드
```bash
curl -X POST "http://localhost:8000/api/s3/upload/directory" \
  -H "Content-Type: application/json" \
  -d '{
    "directory_path": "D:/data/images",
    "recursive": true,
    "content_type": null
  }'
```

#### 4. 단일 파일 삭제
```bash
curl -X DELETE "http://localhost:8000/api/s3/delete/foods/가지볶음/a1b2c3d4_photo.jpg"
```

#### 5. 폴더(prefix) 전체 삭제
```bash
# foods/가지볶음 폴더 내의 모든 파일 삭제
curl -X DELETE "http://localhost:8000/api/s3/delete-prefix/foods/가지볶음"
```

응답 예시:
```json
{
  "success": true,
  "prefix": "foods/가지볶음/",
  "deleted_count": 150,
  "failed_count": 0,
  "deleted_keys": [
    "foods/가지볶음/a1b2c3d4_photo1.jpg",
    "foods/가지볶음/e5f6g7h8_photo2.jpg",
    "..."
  ],
  "failed_keys": []
}
```

#### 7. 버킷 목록 조회
```bash
curl -X GET "http://localhost:8000/api/s3/buckets"
```

응답 예시:
```json
{
  "success": true,
  "bucket_count": 2,
  "buckets": [
    {
      "name": "my-bucket-1",
      "creation_date": "2024-01-15T10:30:00+00:00"
    },
    {
      "name": "kcalai-storage",
      "creation_date": "2024-02-20T14:15:30+00:00"
    }
  ]
}
```

#### 8. 버킷 내 객체 목록 조회
```bash
# 루트 폴더 목록 조회
curl -X GET "http://localhost:8000/api/s3/objects?prefix=&delimiter=/&max_keys=1000"

# foods 폴더 내 하위 폴더 조회
curl -X GET "http://localhost:8000/api/s3/objects?prefix=foods/&delimiter=/&max_keys=1000"

# 특정 폴더의 모든 파일 조회
curl -X GET "http://localhost:8000/api/s3/objects?prefix=foods/images/&delimiter=/&max_keys=1000"

# 모든 객체를 평면적으로 조회 (폴더 구분 없이)
curl -X GET "http://localhost:8000/api/s3/objects?prefix=&delimiter=&max_keys=100"
```

응답 예시:
```json
{
  "success": true,
  "bucket": "kcalai-storage",
  "prefix": "foods/",
  "delimiter": "/",
  "file_count": 5,
  "folder_count": 2,
  "files": [
    {
      "key": "foods/test.jpg",
      "size": 204800,
      "last_modified": "2024-03-15T10:30:00+00:00",
      "storage_class": "STANDARD"
    }
  ],
  "folders": [
    {
      "prefix": "foods/images/"
    },
    {
      "prefix": "foods/documents/"
    }
  ],
  "is_truncated": false,
  "max_keys": 1000
}
```

## 테스트 스크립트 실행

프로젝트에 포함된 테스트 스크립트를 실행하여 API를 테스트할 수 있습니다:

### 1. 버킷 목록 조회
```bash
python test_list_buckets.py
```
- 사용 가능한 모든 버킷 목록을 조회합니다
- 환경 변수의 `BUKET_NAME` 설정을 검증합니다
- 서버 실행 없이 독립적으로 실행 가능합니다

### 2. 객체 목록 조회
```bash
python test_list_objects.py
```
- 버킷 내의 폴더와 파일 구조를 트리 형식으로 보여줍니다
- 평면적으로 모든 객체를 나열합니다
- 서버 실행 없이 독립적으로 실행 가능합니다

### 3. 파일 업로드 테스트
```bash
# 서버가 실행 중인 상태에서
python test_s3_upload.py
```

테스트 스크립트를 실행하기 전에:
1. `test_s3_upload.py` 파일의 파일 경로를 실제 경로로 수정하세요
2. 테스트할 이미지 파일을 준비하세요

## 프로젝트 구조

```
kcalAI/
├── api/
│   ├── __init__.py
│   ├── file_upload_apy.py     # S3 업로드 API 엔드포인트
│   └── predict_api.py
├── services/
│   ├── s3_service.py           # S3 클라이언트 서비스
│   └── ...
├── schemas/
│   ├── s3_schemas.py           # S3 API 스키마
│   └── ...
├── main.py                     # FastAPI 앱
├── requirements.txt
├── test_s3_upload.py           # 파일 업로드 테스트 스크립트
├── test_list_buckets.py        # 버킷 목록 조회 테스트 스크립트
├── test_list_objects.py        # 객체 목록 조회 테스트 스크립트
├── test_s3.http                # HTTP 요청 테스트 파일
└── S3_UPLOAD_README.md         # 이 문서
```

## 문제 해결

### 1. 인증 오류
```
ValueError: NCP credentials and bucket name must be set in environment variables
```
- `.env` 파일이 프로젝트 루트에 있는지 확인
- 환경 변수 (`ACCESS_KEY`, `SECRET_KEY`, `BUKET_NAME`)가 올바르게 설정되었는지 확인

### 2. Object Storage 권한 오류
```
ClientError: An error occurred (AccessDenied) when calling the PutObject operation
```
- API 인증키가 유효한지 확인
- 버킷 ACL 설정이 올바른지 확인
- 네이버 클라우드 플랫폼 콘솔에서 Object Storage 서비스가 활성화되어 있는지 확인

### 3. 엔드포인트 연결 오류
```
EndpointConnectionError
```
- `ENDPOINT_URL`이 올바른지 확인 (기본값: https://kr.object.ncloudstorage.com)
- 네트워크 연결 상태 확인
- 방화벽 설정 확인

### 4. 파일을 찾을 수 없음
```
FileNotFoundError: File not found: /path/to/file
```
- 로컬 파일 경로가 올바른지 확인
- 서버가 해당 파일에 접근 권한이 있는지 확인

## 보안 고려사항

1. **환경 변수 보호**: `.env` 파일을 절대로 버전 관리 시스템에 커밋하지 마세요
2. **API 인증키 관리**: 인증키를 안전하게 보관하고 주기적으로 갱신하세요
3. **Presigned URL 만료 시간**: 적절한 만료 시간을 설정하세요 (기본 1시간)
4. **파일 크기 제한**: 큰 파일 업로드를 제한하려면 FastAPI의 `max_upload_size` 설정을 조정하세요
5. **버킷 ACL 설정**: 버킷의 접근 권한을 최소한으로 설정하세요

## 추가 기능 개발 아이디어

- [x] S3 버킷 목록 조회 ✅
- [x] 버킷 내 객체 및 폴더 구조 조회 ✅
- [x] 디렉토리 전체 업로드 ✅
- [ ] 파일 타입 검증 (이미지, 문서 등)
- [ ] 파일 크기 제한
- [ ] 여러 파일 동시 업로드 (병렬 처리)
- [ ] 업로드 진행률 표시 (WebSocket)
- [ ] 파일 메타데이터 저장 (데이터베이스)
- [ ] 객체 복사/이동 기능
- [ ] 버킷 간 파일 전송

