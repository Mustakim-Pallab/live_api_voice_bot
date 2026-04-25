from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-exp"
    host: str = "0.0.0.0"
    port: int = 8000
    input_audio_rate: int = 16000
    output_audio_rate: int = 24000
    database_url: str = "postgresql://postgres:postgres@localhost:5433/agents_db"
    admin_username: str = "admin"
    admin_password: str = "admin"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
