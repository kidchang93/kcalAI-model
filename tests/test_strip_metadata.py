"""제3자 AI 로 보내는 사진에서 촬영 정보(EXIF·GPS)가 빠지는지 — App Store 5.1.2(i) 동의 문구의 약속."""

import io

from PIL import Image

from services.gemini_vision_service import strip_metadata


def _jpeg_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (37.0, 33.0, 0.0)}  # GPSInfo — 위도
    exif[0x0112] = 6  # Orientation: 90도 회전
    out = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(out, format="JPEG", exif=exif)
    return out.getvalue()


def test_strip_metadata_drops_exif_and_keeps_orientation():
    original = _jpeg_with_gps()
    assert Image.open(io.BytesIO(original)).getexif()  # 전제: 원본엔 있다

    with Image.open(io.BytesIO(strip_metadata(original))) as cleaned:
        assert not cleaned.getexif()
        assert cleaned.size == (20, 40)  # 회전은 픽셀에 반영됐다


def test_strip_metadata_accepts_png_with_alpha():
    out = io.BytesIO()
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(out, format="PNG")

    with Image.open(io.BytesIO(strip_metadata(out.getvalue()))) as cleaned:
        assert cleaned.format == "JPEG"
