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
    jwt_secret_key: str = "your-super-secret-key-change-in-prod"
    jwt_algorithm: str = "HS256"
    gcs_bucket_name: str = "voice_bot_data_dump"
    gcs_service_account_path: str = "vivasoft-gcp-4210bb348a63.json"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
