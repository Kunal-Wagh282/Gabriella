from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
_INSECURE_SECRETS = {"", "replace-with-a-long-random-string", "dev-only-insecure-secret-change-me"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env"),
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = Field("dev", alias="GABRIELLA_ENV")
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+asyncpg://gabriella:gabriella@localhost:5544/gabriella"
    test_database_url: str = (
        "postgresql+asyncpg://gabriella:gabriella@localhost:5544/gabriella_test"
    )

    jwt_secret: SecretStr = SecretStr("dev-only-insecure-secret-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    cookie_secure: bool = False

    cors_origins: list[str] = ["http://localhost:3000"]
    media_root: Path = BACKEND_ROOT / "media"
    media_url: str = "/media"

    seed_admin_email: str = "admin@gabriella.example"
    seed_admin_password: SecretStr = SecretStr("gabriella-admin")
    seed_demo_email: str = "demo@gabriella.example"
    seed_demo_password: SecretStr = SecretStr("gabriella-demo")

    # Gabriella's chat model. `auto` uses Groq if GROQ_API_KEY is set, else Anthropic if
    # ANTHROPIC_API_KEY is set, else the deterministic stylist. Ollama must be chosen explicitly.
    llm_provider: Literal["auto", "groq", "ollama", "openai_compatible", "anthropic", "none"] = (
        "auto"
    )
    groq_api_key: SecretStr | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:7b"
    # Any other OpenAI-compatible server (OpenRouter, vLLM, LM Studio…).
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str = ""
    anthropic_api_key: SecretStr | None = None
    gabriella_model: str = "claude-sonnet-5-5"
    gabriella_effort: Literal["low", "medium", "high"] = "low"

    # Retrieval
    embedding_backend: Literal["clip", "hashing"] = "clip"
    model_cache_dir: Path = BACKEND_ROOT / ".models"
    redis_url: str = "redis://localhost:6390/0"

    @model_validator(mode="after")
    def _refuse_insecure_prod(self) -> "Settings":
        if self.env == "prod" and self.jwt_secret.get_secret_value() in _INSECURE_SECRETS:
            raise ValueError("JWT_SECRET must be set to a strong random value in prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
