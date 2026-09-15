"""Bounded text extraction for searchable PDFs; no OCR or file execution."""

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PDF_BYTES = 10_000_000
MAX_PDF_PAGES = 100
MAX_EXTRACTED_BYTES = 200_000


def extract_pdf(data: bytes) -> list[str]:
    if not data or len(data) > MAX_PDF_BYTES:
        raise ValueError("PDF는 10 MB 이하만 등록할 수 있습니다.")
    if b"%PDF-" not in data[:1024]:
        raise ValueError("올바른 PDF 파일이 아닙니다.")
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("암호화된 PDF는 지원하지 않습니다. 암호를 해제한 파일을 등록해 주세요.")
        if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise ValueError("PDF는 1~100페이지까지 지원합니다.")
        pages = []
        size = 0
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            size += len(text.encode("utf-8"))
            if size > MAX_EXTRACTED_BYTES:
                raise ValueError("PDF의 추출 텍스트가 200 KB를 초과합니다. 파일을 나누어 등록해 주세요.")
            pages.append(text)
    except PdfReadError as exc:
        raise ValueError("PDF를 읽을 수 없습니다. 파일 손상 여부를 확인해 주세요.") from exc
    if not any(pages):
        raise ValueError("추출할 텍스트가 없습니다. 스캔 PDF는 OCR 처리 후 등록해 주세요.")
    return pages
