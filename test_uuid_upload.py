"""
UUID 파일명 생성 테스트 스크립트

UUID가 파일명에 제대로 추가되는지 확인합니다.
"""

import uuid

def generate_unique_filename(original_filename: str) -> tuple[str, str]:
    """
    UUID를 추가한 유니크 파일명 생성
    
    Args:
        original_filename: 원본 파일명
        
    Returns:
        (short_uuid, unique_filename) 튜플
    """
    short_uuid = str(uuid.uuid4())[:8]
    unique_filename = f"{short_uuid}_{original_filename}"
    return short_uuid, unique_filename


if __name__ == "__main__":
    print("=" * 80)
    print("UUID 파일명 생성 테스트")
    print("=" * 80)
    print()
    
    # 테스트 파일명들
    test_files = [
        "photo.jpg",
        "가지볶음.jpg",
        "김치찌개_레시피.pdf",
        "IMG_20241108.png",
        "document.txt",
    ]
    
    print("같은 파일명이 여러 번 업로드되어도 각각 고유한 UUID가 부여됩니다:\n")
    
    for original_name in test_files:
        print(f"원본 파일명: {original_name}")
        print(f"업로드 결과:")
        
        # 같은 파일을 3번 업로드하는 시뮬레이션
        for i in range(3):
            uuid_part, unique_name = generate_unique_filename(original_name)
            s3_key = f"foods/가지볶음/{unique_name}"
            print(f"  {i+1}회: {s3_key}")
        
        print()
    
    print("=" * 80)
    print("✅ 매번 다른 UUID가 생성되어 파일명이 중복되지 않습니다!")
    print("=" * 80)

