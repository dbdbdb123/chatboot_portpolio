import json

from backend.dataclass.settings import Settings


def test_loads_settings_file(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "app_name": "Test Mori",
                "ollama_model": "test-model",
                "redis_url": "redis://file-host:6379/2",
                "max_tool_rounds": 2,
            }
        ),
        encoding="utf-8",
    )

    settings = Settings.load(path)

    assert settings.app_name == "Test Mori"
    assert settings.ollama_model == "test-model"
    assert settings.redis_url == "redis://file-host:6379/2"
    assert settings.max_tool_rounds == 2
    assert settings.generation.temperature is None


def test_redis_url_environment_overrides_settings_file(tmp_path, monkeypatch) -> None:
    """Redis 주소도 다른 설정처럼 환경변수가 JSON 파일보다 우선하는지 확인한다."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"redis_url": "redis://file-host:6379/0"}), encoding="utf-8"
    )
    monkeypatch.setenv("REDIS_URL", "redis://environment-host:6379/1")

    settings = Settings.load(path)

    assert settings.redis_url == "redis://environment-host:6379/1"


def test_loads_settings_with_generation_file(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "app_name": "Test Mori",
                "generation": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "top_k": 40,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                    "repeat_penalty": 1.1,
                    "repeat_last_n": 64,
                    "num_predict": 512,
                    "num_ctx": 2048,
                },
            }
        ),
        encoding="utf-8",
    )

    settings = Settings.load(path)
    assert settings.generation.temperature == 0.3
    assert settings.generation.top_p == 0.9
    assert settings.generation.top_k == 40
    assert settings.generation.presence_penalty == 0.0
    assert settings.generation.frequency_penalty == 0.0
    assert settings.generation.repeat_penalty == 1.1
    assert settings.generation.repeat_last_n == 64
    assert settings.generation.num_predict == 512
    assert settings.generation.num_ctx == 2048


def test_settings_generation_env_override(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "generation": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_OPTIONS_JSON", json.dumps({"temperature": 0.7, "presence_penalty": 0.2}))

    settings = Settings.load(path)
    assert settings.generation.temperature == 0.7
    assert settings.generation.top_p == 0.9
    assert settings.generation.presence_penalty == 0.2


def test_settings_rejects_invalid_generation_in_file(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"generation": "invalid"}), encoding="utf-8")
    import pytest
    with pytest.raises(RuntimeError, match="Invalid application settings"):
        Settings.load(path)


def test_settings_rejects_invalid_env_options_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OLLAMA_OPTIONS_JSON", "[1, 2, 3]")
    import pytest
    with pytest.raises(RuntimeError, match="Invalid application settings"):
        Settings.load(path)


def test_generation_options_validation() -> None:
    import pytest
    from pydantic import ValidationError
    from backend.schemas.generation import GenerationOptions

    # Default produces empty dict with exclude_none
    opts = GenerationOptions()
    assert opts.model_dump(exclude_none=True) == {}

    # Valid values
    valid = GenerationOptions(
        temperature=0.0,
        top_p=1.0,
        top_k=20,
        min_p=0.05,
        typical_p=0.9,
        repeat_penalty=1.2,
        repeat_last_n=-1,
        presence_penalty=-1.5,
        frequency_penalty=1.5,
        mirostat=2,
        mirostat_tau=4.0,
        mirostat_eta=0.2,
        penalize_newline=True,
        seed=42,
        num_predict=-1,
        num_ctx=4096,
        num_batch=512,
        num_keep=10,
        num_thread=8,
        stop=["<|endoftext|>"],
    )
    dumped = valid.model_dump(exclude_none=True)
    assert dumped["temperature"] == 0.0
    assert dumped["num_predict"] == -1
    assert dumped["presence_penalty"] == -1.5

    # Out-of-range temperature
    with pytest.raises(ValidationError):
        GenerationOptions(temperature=2.5)
    with pytest.raises(ValidationError):
        GenerationOptions(temperature=-0.1)

    # Out-of-range top_p
    with pytest.raises(ValidationError):
        GenerationOptions(top_p=1.5)

    # Out-of-range presence_penalty
    with pytest.raises(ValidationError):
        GenerationOptions(presence_penalty=2.5)

    # Extra fields forbidden
    with pytest.raises(ValidationError):
        GenerationOptions.model_validate({"unknown_param": 123})
