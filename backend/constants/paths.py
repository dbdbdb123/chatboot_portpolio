"""실행 위치와 무관하게 계산되는 프로젝트 내부 경로."""

from pathlib import Path

# 현재 파일 위치를 기준으로 계산해 실행 디렉터리(cwd)에 의존하지 않는다.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
UI_DIRECTORY = PROJECT_ROOT / "chatbot-ui"
SETTING_DIRECTORY = PROJECT_ROOT / ".setting"
SETTINGS_FILE = SETTING_DIRECTORY / "settings.json"
