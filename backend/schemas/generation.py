"""Ollama 생성 파라미터. None은 서버·모델 기본값에 위임한다."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class GenerationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=0)
    min_p: float | None = Field(default=None, ge=0.0, le=1.0)
    typical_p: float | None = Field(default=None, ge=0.0, le=1.0)
    repeat_penalty: float | None = Field(default=None, ge=0.0, le=3.0)
    repeat_last_n: int | None = Field(default=None, ge=-1)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    mirostat: int | None = Field(default=None, ge=0, le=2)
    mirostat_tau: float | None = Field(default=None, ge=0.0)
    mirostat_eta: float | None = Field(default=None, ge=0.0)
    penalize_newline: bool | None = Field(default=None)
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    num_predict: int | None = Field(default=None, ge=-2, le=131072)
    num_ctx: int | None = Field(default=None, ge=512, le=131072)
    num_batch: int | None = Field(default=None, ge=1, le=8192)
    num_keep: int | None = Field(default=None, ge=0)
    num_thread: int | None = Field(default=None, ge=1, le=256)
    stop: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None, max_length=16
    )
