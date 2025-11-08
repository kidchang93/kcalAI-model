"""
S3 업로드 API 테스트 스크립트

이 스크립트는 로컬 파일을 S3에 업로드하는 예제입니다.
"""
import os
import requests


def test_upload_file_multipart():
    """파일 객체를 multipart/form-data로 업로드하는 테스트"""
    url = "http://localhost:8000/api/s3/upload/file"

    # 테스트할 파일 경로 (프로젝트 내 실제 파일로 변경하세요)
    test_file_path = "test_image.jpg"

    if not os.path.exists(test_file_path):
        print(f"❌ 테스트 파일을 찾을 수 없습니다: {test_file_path}")
        print("테스트 파일을 생성하거나 경로를 수정하세요.")
        return

    try:
        with open(test_file_path, "rb") as f:
            files = {"file": (os.path.basename(test_file_path), f, "image/jpeg")}
            data = {"parent_folder": "test_images"}  # 상위 폴더명 지정

            print("📤 파일 업로드 중...")
            response = requests.post(url, files=files, data=data)

        if response.status_code == 200:
            result = response.json()
            print("✅ 업로드 성공!")
            print(f"   - 버킷: {result['bucket']}")
            print(f"   - 키: {result['key']}")
            print(f"   - URL: {result['url']}")
            print(f"   - 파일명: {result['filename']}")
            print(f"   - 크기: {result['size']} bytes")
        else:
            print(f"❌ 업로드 실패: {response.status_code}")
            print(f"   응답: {response.text}")

    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")


def test_upload_local_file():
    """로컬 파일 경로를 통한 업로드 테스트"""
    url = "http://localhost:8000/api/s3/upload/local-file"

    # 테스트할 파일 경로 (서버에서 접근 가능한 경로로 설정하세요)
    # 예: D:/data/images/test_image.jpg -> PATH/images/test_image.jpg 형식으로 저장됨
    test_file_path = "D:/lck_data/python/kcalAI/test_images/test_image.jpg"

    if not os.path.exists(test_file_path):
        print(f"❌ 테스트 파일을 찾을 수 없습니다: {test_file_path}")
        print("테스트 파일을 생성하거나 경로를 수정하세요.")
        return

    payload = {
        "file_path": test_file_path,
        "content_type": "image/jpeg",
    }

    try:
        print("📤 로컬 파일 업로드 중...")
        print(f"   파일 경로: {test_file_path}")
        print(f"   상위 폴더: {os.path.basename(os.path.dirname(test_file_path))}")
        response = requests.post(url, json=payload)

        if response.status_code == 200:
            result = response.json()
            print("✅ 업로드 성공!")
            print(f"   - 버킷: {result['bucket']}")
            print(f"   - 키: {result['key']}")
            print(f"   - URL: {result['url']}")
            print(f"   - 파일명: {result['filename']}")
            print(f"   - 크기: {result['size']} bytes")
        else:
            print(f"❌ 업로드 실패: {response.status_code}")
            print(f"   응답: {response.text}")

    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")


def test_upload_directory():
    """디렉토리 전체 업로드 테스트"""
    url = "http://localhost:8000/api/s3/upload/directory"

    # 테스트할 디렉토리 경로 (서버에서 접근 가능한 경로로 설정하세요)
    test_directory_path = "D:/lck_data/python/kcalAI/test_images"

    if not os.path.exists(test_directory_path):
        print(f"❌ 테스트 디렉토리를 찾을 수 없습니다: {test_directory_path}")
        print("테스트 디렉토리를 생성하거나 경로를 수정하세요.")
        return

    payload = {
        "directory_path": test_directory_path,
        "recursive": True,  # 하위 폴더 포함
        "content_type": None,
    }

    try:
        print("📤 디렉토리 업로드 중...")
        print(f"   디렉토리: {test_directory_path}")
        response = requests.post(url, json=payload)

        if response.status_code == 200:
            result = response.json()
            print("✅ 디렉토리 업로드 완료!")
            print(f"   - 전체: {result['success']}")
            print(f"   - 총 파일 수: {result['total_files']}")
            print(f"   - 성공: {result['uploaded_count']}")
            print(f"   - 실패: {result['failed_count']}")
            
            if result['uploaded_files']:
                print("\n   📁 업로드된 파일:")
                for file_info in result['uploaded_files'][:5]:  # 처음 5개만 출력
                    print(f"      - {file_info['file_path']} -> {file_info['s3_key']}")
                if len(result['uploaded_files']) > 5:
                    print(f"      ... 외 {len(result['uploaded_files']) - 5}개")
            
            if result['failed_files']:
                print("\n   ❌ 실패한 파일:")
                for file_info in result['failed_files']:
                    print(f"      - {file_info['file_path']}: {file_info['error']}")
        else:
            print(f"❌ 디렉토리 업로드 실패: {response.status_code}")
            print(f"   응답: {response.text}")

    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")


def test_get_presigned_url():
    """Presigned URL 생성 테스트"""
    # 먼저 업로드된 파일의 S3 키가 필요합니다
    s3_key = "foods/test_images/test_image.jpg"  # 실제 S3 키로 변경하세요
    url = f"http://localhost:8000/api/s3/presigned-url/{s3_key}"

    try:
        print("🔗 Presigned URL 생성 중...")
        response = requests.get(url, params={"expiration": 3600})

        if response.status_code == 200:
            result = response.json()
            print("✅ Presigned URL 생성 성공!")
            print(f"   - 키: {result['key']}")
            print(f"   - URL: {result['url']}")
            print(f"   - 만료 시간: {result['expiration_seconds']}초")
        else:
            print(f"❌ Presigned URL 생성 실패: {response.status_code}")
            print(f"   응답: {response.text}")

    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")


if __name__ == "__main__":
    print("=" * 60)
    print("S3 업로드 API 테스트")
    print("=" * 60)

    print("\n[1] 파일 객체 업로드 테스트 (Multipart Form)")
    print("-" * 60)
    test_upload_file_multipart()

    print("\n[2] 로컬 파일 경로 업로드 테스트")
    print("-" * 60)
    test_upload_local_file()

    print("\n[3] 디렉토리 전체 업로드 테스트")
    print("-" * 60)
    test_upload_directory()

    print("\n[4] Presigned URL 생성 테스트")
    print("-" * 60)
    # test_get_presigned_url()  # 주석 해제하고 실제 S3 키로 테스트

    print("\n" + "=" * 60)
    print("테스트 완료!")
    print("=" * 60)

