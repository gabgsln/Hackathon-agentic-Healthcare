from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic
    anthropic_api_key: str = ""

    # App
    app_env: str = "development"
    app_port: int = 8000
    log_level: str = "INFO"

    # Storage
    storage_backend: str = "local"
    data_dir: Path = Path("./data")

    # Models
    agent_model: str = "claude-sonnet-4-6"
    vision_model: str = "claude-sonnet-4-6"

    # PDF
    pdf_engine: str = "weasyprint"

    # Pipeline
    pipeline_version: str = "0.1.0"

    # Orthanc DICOM server
    orthanc_url: str = "http://10.0.1.215:8042"
    orthanc_user: str = "unboxed"
    orthanc_pass: str = "unboxed2026"

    @property
    def samples_dir(self) -> Path:
        return self.data_dir / "samples"

    @property
    def templates_dir(self) -> Path:
        return Path(__file__).parent.parent / "reporting" / "templates"


settings = Settings()
