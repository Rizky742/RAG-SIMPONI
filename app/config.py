from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/central_db"

    # OpenAI
    openai_api_key: str = ""

    # Optional custom endpoint (e.g. Azure / proxy). Leave empty to use the
    # official OpenAI API. None lets the SDK pick its default base URL.
    base_url: str | None = None

    # App Settings
    app_env: str = "development"
    max_rows_returned: int = 500
    sql_timeout_seconds: int = 30

    # LLM Model
    # gpt-5.x / o-series are reasoning models: the service uses
    # `max_completion_tokens` and the default temperature for them automatically.
    # gpt-4o-mini / gpt-4o use `max_tokens` + custom temperature.
    llm_model: str = "gpt-5.4-mini"
    # Output-token budget. For reasoning models this also has to cover hidden
    # reasoning tokens, so keep it generous.
    max_tokens: int = 4096
    # Timeout (seconds) for each OpenAI request so a hung call cannot block forever.
    request_timeout: float = 30.0

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
