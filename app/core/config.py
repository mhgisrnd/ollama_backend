from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_SERVER_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Spatial LLM Server"
    environment: str = "local"
    agent_timeout_seconds: float = Field(default=240, ge=10, le=600)
    registry_database_path: Path = PROJECT_ROOT / "data" / "registry.sqlite3"
    ollama_base_url: HttpUrl = HttpUrl("http://127.0.0.1:11434")
    ollama_model: str = Field(default="qwen3:4b", min_length=1, pattern=r"^\S+$")
    ollama_timeout_seconds: float = Field(default=120, gt=0, le=600)
    ollama_num_ctx: int = Field(default=4096, ge=512, le=32768)
    ollama_num_predict: int = Field(default=512, ge=1, le=4096)
    ollama_keep_alive: str = "5m"
    ollama_disable_thinking: bool = True
