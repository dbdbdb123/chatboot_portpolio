"""첨부 이미지의 실제 형식과 자원 제한을 검증한다."""

import base64
import binascii
import warnings
from io import BytesIO
from typing import Self

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, model_validator

from backend.constants.images import (
    IMAGE_MIME_TYPES,
    MAX_BASE64_LENGTH,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_NAME_LENGTH,
    MAX_IMAGE_PIXELS,
)


class ImageAttachment(BaseModel):
    """실제 이미지 내용과 자원 제한을 검증한 단일 첨부 데이터."""

    name: str = Field(min_length=1, max_length=MAX_IMAGE_NAME_LENGTH)
    mime_type: str
    data_base64: str = Field(min_length=1, max_length=MAX_BASE64_LENGTH, repr=False)

    @model_validator(mode="after")
    def validate_image(self) -> Self:
        """Base64와 이미지 형식·해상도·프레임을 검증하고 디코딩 가능한지 확인한다."""
        if self.mime_type not in IMAGE_MIME_TYPES.values():
            raise ValueError("PNG, JPEG, WebP 이미지만 첨부할 수 있습니다.")
        try:
            raw = base64.b64decode(self.data_base64, validate=True)
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("이미지는 10MB 이하여야 합니다.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as img:
                    if IMAGE_MIME_TYPES.get(img.format) != self.mime_type:
                        raise ValueError("이미지 내용과 MIME 형식이 일치하지 않습니다.")
                    if (
                        max(img.size) > MAX_IMAGE_DIMENSION
                        or img.width * img.height > MAX_IMAGE_PIXELS
                    ):
                        raise ValueError(
                            "이미지는 가로·세로 8000px, 총 2500만 픽셀 이하여야 합니다."
                        )
                    if getattr(img, "n_frames", 1) != 1:
                        raise ValueError("움직이는 이미지는 지원하지 않습니다.")
                    img.verify()
                with Image.open(BytesIO(raw)) as img:
                    img.load()
        except (
            binascii.Error,
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise ValueError("올바른 이미지 파일이 아닙니다.") from exc
        return self
