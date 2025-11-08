"""
S3 Prefix(폴더) 삭제 테스트 스크립트

특정 prefix의 모든 파일을 일괄 삭제하는 기능을 테스트합니다.
서버가 실행 중이어야 합니다.
"""

import requests

API_BASE_URL = "http://localhost:8000/api/s3"


def delete_prefix(prefix: str):
    """
    특정 prefix의 모든 파일 삭제
    
    Args:
        prefix: 삭제할 prefix (예: "foods/가지볶음", "foods/가지볶음/")
    """
    print("=" * 80)
    print(f"Prefix 삭제 요청: {prefix}")
    print("=" * 80)
    
    # prefix에 슬래시가 없으면 추가 (옵션)
    # API에서 자동으로 추가하지만, 명시적으로 할 수도 있음
    
    url = f"{API_BASE_URL}/delete-prefix/{prefix}"
    
    print(f"\n🔄 요청 URL: {url}")
    print(f"🔄 메서드: DELETE")
    print("\n⏳ 삭제 중...\n")
    
    try:
        response = requests.delete(url)
        
        if response.status_code == 200:
            data = response.json()
            
            print("✅ 삭제 성공!")
            print(f"\n📊 삭제 결과:")
            print(f"  - Prefix: {data['prefix']}")
            print(f"  - 삭제된 파일 수: {data['deleted_count']}")
            print(f"  - 실패한 파일 수: {data['failed_count']}")
            print(f"  - 전체 성공 여부: {'✅ 성공' if data['success'] else '❌ 일부 실패'}")
            
            if data['deleted_count'] > 0:
                print(f"\n📁 삭제된 파일 목록:")
                for idx, key in enumerate(data['deleted_keys'][:10], 1):  # 최대 10개만 표시
                    print(f"  {idx}. {key}")
                
                if data['deleted_count'] > 10:
                    print(f"  ... 외 {data['deleted_count'] - 10}개")
            
            if data['failed_count'] > 0:
                print(f"\n❌ 실패한 파일:")
                for failed in data['failed_keys']:
                    print(f"  - {failed['key']}: {failed['message']}")
        
        else:
            print(f"❌ 오류 발생: {response.status_code}")
            print(f"응답: {response.text}")
    
    except requests.exceptions.ConnectionError:
        print("❌ 서버에 연결할 수 없습니다.")
        print("서버가 실행 중인지 확인하세요: uvicorn main:app --reload")
    
    except Exception as e:
        print(f"❌ 예외 발생: {str(e)}")
    
    print("\n" + "=" * 80 + "\n")


def list_objects(prefix: str = ""):
    """
    특정 prefix의 객체 목록 조회
    
    Args:
        prefix: 조회할 prefix
    """
    url = f"{API_BASE_URL}/objects"
    params = {
        "prefix": prefix,
        "delimiter": "/",
        "max_keys": 1000
    }
    
    print(f"📂 '{prefix}' 객체 목록 조회 중...")
    
    try:
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"  - 파일 수: {data['file_count']}")
            print(f"  - 폴더 수: {data['folder_count']}")
            
            if data['file_count'] > 0:
                print(f"\n  파일 목록 (최대 5개):")
                for idx, file_info in enumerate(data['files'][:5], 1):
                    size_mb = file_info['size'] / 1024 / 1024
                    print(f"    {idx}. {file_info['key']} ({size_mb:.2f} MB)")
                
                if data['file_count'] > 5:
                    print(f"    ... 외 {data['file_count'] - 5}개")
        
        else:
            print(f"  ❌ 조회 실패: {response.status_code}")
    
    except Exception as e:
        print(f"  ❌ 조회 오류: {str(e)}")
    
    print()


if __name__ == "__main__":
    print("\n")
    print("🗑️  S3 Prefix 삭제 테스트")
    print("=" * 80)
    print("⚠️  주의: 이 작업은 되돌릴 수 없습니다!")
    print("=" * 80)
    print()
    
    # 사용 예시
    print("📋 사용 예시:")
    print()
    
    # 예시 1: foods/가지볶음 폴더 내 파일 확인
    print("1️⃣  삭제 전 확인")
    list_objects("foods/가지볶음/")
    
    # 예시 2: 실제 삭제 (주석 해제하여 사용)
    print("2️⃣  삭제 실행 (아래 주석을 해제하여 실행)")
    print("    # delete_prefix('foods/가지볶음')")
    print()
    
    # 실제 삭제를 원하면 아래 주석을 해제하세요
    # delete_prefix("foods/가지볶음")
    
    # 예시 3: 삭제 후 확인
    print("3️⃣  삭제 후 확인")
    print("    # list_objects('foods/가지볶음/')")
    print()
    
    print("=" * 80)
    print("💡 팁:")
    print("  - 스크립트를 수정하여 delete_prefix() 주석을 해제하면 실제 삭제됩니다")
    print("  - 또는 test_s3.http 파일에서 DELETE 요청을 직접 실행하세요")
    print("  - 또는 Swagger UI (http://localhost:8000/docs)에서 테스트하세요")
    print("=" * 80)

