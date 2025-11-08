"""
네이버 클라우드 플랫폼 Object Storage 버킷 목록 조회 테스트 스크립트

이 스크립트는 직접 boto3를 사용하여 버킷 목록을 조회합니다.
환경 변수 설정 후 실행하세요.
"""

import os
import boto3
from dotenv import load_dotenv
from botocore.exceptions import ClientError

# 환경 변수 로드
load_dotenv()

def list_buckets():
    """네이버 클라우드 플랫폼 Object Storage 버킷 목록 조회"""
    
    # 환경 변수에서 인증 정보 가져오기
    access_key = os.getenv("ACCESS_KEY")
    secret_key = os.getenv("SECRET_KEY")
    region = os.getenv("REGION")
    endpoint_url = os.getenv("DOMAIN")
    
    if not all([access_key, secret_key]):
        print("❌ 오류: ACCESS_KEY와 SECRET_KEY가 환경 변수에 설정되어야 합니다.")
        return
    
    print("=" * 60)
    print("네이버 클라우드 플랫폼 Object Storage 버킷 목록 조회")
    print("=" * 60)
    print(f"\n접속 정보:")
    print(f"  - Endpoint: {endpoint_url}")
    print(f"  - Region: {region}")
    print(f"  - Access Key: {access_key[:10]}...")
    print()
    
    try:
        # S3 클라이언트 생성
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            endpoint_url=endpoint_url,
        )
        
        # 버킷 목록 조회
        print("버킷 목록 조회 중...")
        response = s3_client.list_buckets()
        
        buckets = response.get('Buckets', [])
        
        if not buckets:
            print("\n⚠️  버킷이 없습니다.")
            return
        
        print(f"\n✅ 총 {len(buckets)}개의 버킷을 찾았습니다:\n")
        
        # 버킷 정보 출력
        for idx, bucket in enumerate(buckets, 1):
            print(f"{idx}. 버킷 이름: {bucket['Name']}")
            print(f"   생성 날짜: {bucket['CreationDate']}")
            print()
        
        # 환경 변수에 설정된 버킷 이름과 비교
        configured_bucket = os.getenv("BUKET_NAME")
        print("-" * 60)
        print(f"\n현재 환경 변수(BUKET_NAME)에 설정된 값: {configured_bucket}")
        
        if configured_bucket in [b['Name'] for b in buckets]:
            print("✅ 설정된 버킷이 존재합니다!")
        else:
            print("❌ 설정된 버킷이 목록에 없습니다. BUKET_NAME 환경 변수를 확인해주세요.")
            print(f"\n사용 가능한 버킷 이름:")
            for bucket in buckets:
                print(f"  - {bucket['Name']}")
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        print(f"\n❌ AWS/NCP Client 오류:")
        print(f"  - 오류 코드: {error_code}")
        print(f"  - 오류 메시지: {error_message}")
        
        if error_code == 'InvalidAccessKeyId':
            print("\n💡 힌트: ACCESS_KEY가 올바르지 않습니다.")
        elif error_code == 'SignatureDoesNotMatch':
            print("\n💡 힌트: SECRET_KEY가 올바르지 않습니다.")
            
    except Exception as e:
        print(f"\n❌ 예상치 못한 오류: {str(e)}")

if __name__ == "__main__":
    list_buckets()

