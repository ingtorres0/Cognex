"""Runtime settings loaded from the environment, with local defaults."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Connection settings for Postgres, the camera socket, and CORS.

    Defaults match ``docker-compose.yml`` and the in-process camera mock, so
    the stack runs without an env file. Override by exporting variables or by
    placing a ``.env`` file in the working directory (normally ``backend/``).
    """

    database_url: str = "postgresql+asyncpg://avi:avi_dev_password@localhost:5432/avi"

    cognex_host: str = "169.254.4.28"
    cognex_port: int = 23
    cognex_bind_host: str = "0.0.0.0"
    cognex_trigger_command: str = "SE8"
    cognex_command_timeout: float = 3.0
    cognex_mock_enabled: bool = False

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def _use_async_driver(cls, value: str) -> str:
        # SQLAlchemy's async engine needs the asyncpg driver in the URL.
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cognex_trigger_command")
    @classmethod
    def _normalize_command(cls, value: str) -> str:
        command = value.strip()
        if not command:
            raise ValueError("COGNEX_TRIGGER_COMMAND cannot be empty")
        return command


settings = Settings()
