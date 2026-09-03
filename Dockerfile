# syntax=docker/dockerfile:1

# CPU 환경에서도 동일하게 실행되는 작은 Python 런타임을 사용한다.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성과 소스 파일을 분리해서 복사하면 코드 변경 시 빌드 캐시를 활용할 수 있다.
COPY pyproject.toml README.md ./
COPY backend ./backend
RUN pip install --no-cache-dir .

COPY main.py ./main.py
COPY chatbot-ui ./chatbot-ui
COPY .setting ./.setting

# 애플리케이션은 권한이 제한된 사용자로 실행한다.
RUN useradd --create-home --uid 10001 mori \
    && chown -R mori:mori /app
USER mori

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
