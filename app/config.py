from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/central_db"

    # OpenAI
    openai_api_key: str = ""

    # App Settings
    app_env: str = "development"
    max_rows_returned: int = 500
    sql_timeout_seconds: int = 30

    # LLM Model
    # Options: "gpt-5.4-mini" (mini/affordable), "gpt-5.5" (flagship), "gpt-5-mini" (older mini)
    llm_model: str = "gpt-5.4-mini"
    max_tokens: int = 4096

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
