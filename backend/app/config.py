"""Settings, read from the .env file.

Only what the app uses today is listed here. Each later step adds its own
settings (AI keys, email, etc.) when it needs them.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str  # Supabase connection string, required
    redis_url: str = "redis://redis:6379/0"


settings = Settings()
