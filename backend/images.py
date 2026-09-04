"""첨부 이미지의 실제 형식과 자원 제한을 검증한다."""
import base64
import binascii
import warnings
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, model_validator

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_BASE64_LENGTH = 4 * ((MAX_IMAGE_BYTES + 2) // 3)


class ImageAttachment(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mime_type: str
    data_base64: str = Field(min_length=1, max_length=MAX_BASE64_LENGTH, repr=False)

    @model_validator(mode="after")
    def validate_image(self):
        formats = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
        if self.mime_type not in formats.values():
            raise ValueError("PNG, JPEG, WebP 이미지만 첨부할 수 있습니다.")
        try:
            raw = base64.b64decode(self.data_base64, validate=True)
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("이미지는 10MB 이하여야 합니다.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as img:
                    if formats.get(img.format) != self.mime_type:
                        raise ValueError("이미지 내용과 MIME 형식이 일치하지 않습니다.")
                    if max(img.size) > 8000 or img.width * img.height > 25_000_000:
                        raise ValueError("이미지는 가로·세로 8000px, 총 2500만 픽셀 이하여야 합니다.")
                    if getattr(img, "n_frames", 1) != 1:
                        raise ValueError("움직이는 이미지는 지원하지 않습니다.")
                    img.verify()
                with Image.open(BytesIO(raw)) as img:
                    img.load()
        except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            raise ValueError("올바른 이미지 파일이 아닙니다.") from exc
        return self
