from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    access_token: str = Field(default="", alias="M365_ACCESS_TOKEN")
    time_zone: str = Field(default="", alias="M365_TIME_ZONE")
    model_alias: str = Field(default="m365-copilot", alias="M365_MODEL_ALIAS")
    work_mode: bool = Field(default=True, alias="M365_WORK_MODE")
    read_only_tools: str = Field(default="read,glob,grep,list,ls", alias="M365_READ_ONLY_TOOLS")
    max_observation_chars: int = Field(default=12000, alias="M365_MAX_OBSERVATION_CHARS")
    max_reasks: int = Field(default=2, alias="M365_MAX_REASKS")

    @property
    def read_only_tool_names(self) -> frozenset[str]:
        return frozenset(
            name.strip().lower() for name in self.read_only_tools.split(",") if name.strip()
        )
