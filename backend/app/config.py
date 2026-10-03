"""Settings, read from the .env file.

Only what the app uses today is listed here. Each later step adds its own
settings (email, Google Sheet, etc.) when it needs them.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str  # Supabase connection string, required
    redis_url: str = "redis://redis:6379/0"
    site_base_url: str = "https://itcybx.co.uk"

    # AI models. SecretStr keeps keys out of logs and error messages.
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5-5"
    mistral_api_key: SecretStr = SecretStr("")
    mistral_model: str = "mistral-large-latest"
    llm_timeout_seconds: float = 20
    max_output_tokens: int = 400

    # Lead alerts: email (Hostinger SMTP) and Google Sheet
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    lead_email_to: str = "info@itcybx.co.uk"
    google_sheet_id: str = ""
    google_service_account_json: str = ""

    # Contact buttons. A button is hidden while its link is empty.
    calendly_url: str = ""
    whatsapp_url: str = "https://wa.me/923104887999"
    contact_email: str = "info@itcybx.co.uk"
    contact_page_url: str = "https://itcybx.co.uk/contact/"


settings = Settings()
