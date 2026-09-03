import json

from backend.dataclass.settings import Settings


def test_loads_settings_file(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "app_name": "Test Mori",
        "ollama_model": "test-model",
        "max_tool_rounds": 2,
    }), encoding="utf-8")

    settings = Settings.load(path)

    assert settings.app_name == "Test Mori"
    assert settings.ollama_model == "test-model"
    assert settings.max_tool_rounds == 2
