"""
네이버 클라우드 플랫폼 Object Storage 객체 목록 조회 테스트 스크립트

이 스크립트는 버킷 내의 폴더와 파일 구조를 트리 형식으로 보여줍니다.
환경 변수 설정 후 실행하세요.
"""

import os
import boto3
from dotenv import load_dotenv
from botocore.exceptions import ClientError

# 환경 변수 로드
load_dotenv()


def format_size(size_bytes):
    """파일 크기를 읽기 쉬운 형식으로 변환"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def list_objects_tree(s3_client, bucket_name, prefix="", indent=0):
    """
    재귀적으로 버킷의 폴더 구조를 트리 형식으로 출력
    
    Args:
        s3_client: boto3 S3 클라이언트
        bucket_name: 버킷 이름
        prefix: 조회할 접두사
        indent: 들여쓰기 레벨
    """
    try:
        # delimiter="/"를 사용하여 폴더 구조로 조회
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=prefix,
            Delimiter='/'
        )
        
        # 현재 레벨의 폴더들 (CommonPrefixes)
        folders = response.get('CommonPrefixes', [])
        for folder in folders:
            folder_name = folder['Prefix'].replace(prefix, '').rstrip('/')
            print("  " * indent + f"📁 {folder_name}/")
            # 재귀적으로 하위 폴더 탐색
            list_objects_tree(s3_client, bucket_name, folder['Prefix'], indent + 1)
        
        # 현재 레벨의 파일들 (Contents)
        files = response.get('Contents', [])
        for obj in files:
            # prefix와 정확히 같은 경우는 폴더 자체이므로 제외
            if obj['Key'] == prefix:
                continue
            file_name = obj['Key'].replace(prefix, '')
            file_size = format_size(obj['Size'])
            print("  " * indent + f"📄 {file_name} ({file_size})")
            
    except ClientError as e:
        print("  " * indent + f"❌ 오류: {str(e)}")


def list_objects_flat(s3_client, bucket_name, prefix="", max_keys=100):
    """
    평면적으로 모든 객체 나열 (폴더 구분 없이)
    
    Args:
        s3_client: boto3 S3 클라이언트
        bucket_name: 버킷 이름
        prefix: 조회할 접두사
        max_keys: 최대 조회 개수
    """
    try:
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=prefix,
            MaxKeys=max_keys
        )
        
        objects = response.get('Contents', [])
        
        if not objects:
            print("  객체가 없습니다.")
            return
        
        print(f"\n  총 {len(objects)}개의 객체:")
        print("  " + "-" * 80)
        
        for idx, obj in enumerate(objects, 1):
            size = format_size(obj['Size'])
            modified = obj['LastModified'].strftime('%Y-%m-%d %H:%M:%S')
            print(f"  {idx:3d}. {obj['Key']}")
            print(f"       크기: {size:>12} | 수정일: {modified}")
        
        if response.get('IsTruncated', False):
            print(f"\n  ⚠️  결과가 잘렸습니다. MaxKeys={max_keys}보다 많은 객체가 있습니다.")
            
    except ClientError as e:
        print(f"  ❌ 오류: {str(e)}")


def main():
    """메인 함수"""
    
    # 환경 변수에서 인증 정보 가져오기
    access_key = os.getenv("ACCESS_KEY")
    secret_key = os.getenv("SECRET_KEY")
    region = os.getenv("REGION")
    endpoint_url = os.getenv("DOMAIN")
    bucket_name = os.getenv("BUKET_NAME")
    
    if not all([access_key, secret_key, bucket_name]):
        print("❌ 오류: ACCESS_KEY, SECRET_KEY, BUKET_NAME이 환경 변수에 설정되어야 합니다.")
        return
    
    print("=" * 80)
    print("네이버 클라우드 플랫폼 Object Storage 객체 목록 조회")
    print("=" * 80)
    print(f"\n버킷 정보:")
    print(f"  - 버킷 이름: {bucket_name}")
    print(f"  - Endpoint: {endpoint_url}")
    print(f"  - Region: {region}")
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
        
        # 1. 트리 구조로 보기
        print("📂 버킷 전체 구조 (트리 형식):")
        print("-" * 80)
        list_objects_tree(s3_client, bucket_name)
        
        print("\n")
        print("=" * 80)
        
        # 2. 특정 prefix만 트리 구조로 보기
        food_prefix = "foods/"
        print(f"📂 '{food_prefix}' 폴더 구조:")
        print("-" * 80)
        
        # foods/ 폴더가 있는지 확인
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=food_prefix,
            MaxKeys=1
        )
        
        if response.get('Contents') or response.get('CommonPrefixes'):
            list_objects_tree(s3_client, bucket_name, food_prefix)
        else:
            print(f"  '{food_prefix}' 폴더가 비어있거나 존재하지 않습니다.")
        
        print("\n")
        print("=" * 80)
        
        # 3. 평면적으로 모든 객체 보기 (처음 20개)
        print("📄 모든 객체 목록 (평면적, 최대 20개):")
        print("-" * 80)
        list_objects_flat(s3_client, bucket_name, "", max_keys=20)
        
        print("\n")
        print("=" * 80)
        print("✅ 조회 완료!")
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        print(f"\n❌ AWS/NCP Client 오류:")
        print(f"  - 오류 코드: {error_code}")
        print(f"  - 오류 메시지: {error_message}")
        
        if error_code == 'NoSuchBucket':
            print(f"\n💡 힌트: 버킷 '{bucket_name}'이(가) 존재하지 않습니다.")
            print("  test_list_buckets.py를 실행하여 사용 가능한 버킷을 확인하세요.")
        elif error_code == 'InvalidAccessKeyId':
            print("\n💡 힌트: ACCESS_KEY가 올바르지 않습니다.")
        elif error_code == 'SignatureDoesNotMatch':
            print("\n💡 힌트: SECRET_KEY가 올바르지 않습니다.")
            
    except Exception as e:
        print(f"\n❌ 예상치 못한 오류: {str(e)}")


if __name__ == "__main__":
    main()

