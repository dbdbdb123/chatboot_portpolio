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
    """실제 파일 내용 검증을 수행하는 단일 이미지 첨부 요청 모델.

    name은 표시용 파일명, mime_type은 선언된 형식, data_base64는 파일 원문이다.
    생성 과정에서 Base64·용량·실제 형식·해상도·프레임 수와 디코딩 가능성을
    검증하며 PNG·JPEG·WebP 정지 이미지만 받는다. 제한값은 constants.images에 둔다.
    data_base64의 repr=False는 객체 표현에서만 숨기며 직렬화에서 제거하지 않는다.
    오류 응답과 UI 노출 방지는 별도 처리 계층에서 보장해야 한다.
    """

    name: str = Field(min_length=1, max_length=MAX_IMAGE_NAME_LENGTH)
    mime_type: str
    data_base64: str = Field(min_length=1, max_length=MAX_BASE64_LENGTH, repr=False)

    @model_validator(mode="after")
    def validate_image(self) -> Self:
        """첨부 원문이 지원 형식과 자원 제한을 만족하는 실제 이미지인지 검증한다.

        Base64를 엄격히 디코딩하고 용량, 선언 MIME과 실제 형식, 해상도,
        프레임 수를 확인한 뒤 파일 검증과 실제 픽셀 디코딩을 수행한다.
        성공하면 현재 인스턴스를 반환하며 원본 필드값을 변환하지 않는다.
        손상된 파일·지원하지 않는 형식·제한 초과는 ValueError로 전달한다.
        이미지 객체는 컨텍스트 관리자로 닫으며 파일을 디스크에 저장하지 않는다.
        """
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
