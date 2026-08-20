from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_user: str = Field(default="argus")
    database_password: str = Field(default="argus")
    database_host: str = Field(default="localhost")
    database_port: int = Field(default=5432)

    target_service_url: str = Field(default="http://localhost:8080")

    read_mcp_host: str = Field(default="localhost")
    read_mcp_port: int = Field(default=8090)

    mitigate_threshold: float = Field(default=0.75)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/argus"
        )

    @property
    def read_mcp_url(self) -> str:
        return f"http://{self.read_mcp_host}:{self.read_mcp_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
