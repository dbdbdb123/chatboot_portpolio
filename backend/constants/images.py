"""이미지 첨부 검증에서 사용하는 용량·해상도 제한과 형식 매핑."""

from types import MappingProxyType

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_BASE64_LENGTH = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
MAX_IMAGE_DIMENSION = 8000
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_NAME_LENGTH = 255
IMAGE_MIME_TYPES = MappingProxyType(
    {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
)
