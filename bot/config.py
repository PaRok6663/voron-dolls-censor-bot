import os
import yaml
from typing import List, Optional, Any, Union
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    BOT_TOKEN: str = ""
    ADMIN_IDS: List[int] = []
    LOG_CHAT_ID: Optional[int] = None
    DATABASE_PATH: str = "bot_data.sqlite3"
    
    # Defaults
    DEFAULT_ANTI_PORN: bool = True
    DEFAULT_ANTI_SPAM: bool = True
    DEFAULT_ANTI_FLOOD: bool = True
    DEFAULT_ANTI_LINKS: bool = True
    DEFAULT_ANTI_FOREIGN: bool = True
    DEFAULT_ANTI_PROFANITY: bool = True
    DEFAULT_DELETE_SERVICE: bool = True
    DEFAULT_BLOCK_MEDIA: bool = False
    DEFAULT_ACTION: str = "delete"  # "delete", "warn", "mute", "ban"
    DEFAULT_SILENT_MODE: bool = True  # don't post "message deleted" in comments to avoid clutter
    MAX_WARNINGS: int = 3
    FLOOD_MESSAGES_LIMIT: int = 4
    FLOOD_WINDOW_SECONDS: int = 6

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: Any) -> List[int]:
        if isinstance(v, list):
            return [int(x) for x in v if str(x).strip()]
        if isinstance(v, (int, float)):
            return [int(v)]
        if isinstance(v, str):
            clean = v.strip("[]() ")
            if not clean:
                return []
            return [int(x.strip()) for x in clean.split(",") if x.strip().isdigit()]
        return []

    @field_validator("LOG_CHAT_ID", mode="before")
    @classmethod
    def parse_log_chat_id(cls, v: Any) -> Optional[int]:
        if v is None or v == "" or v == 0 or str(v).strip() == "":
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


def load_config() -> BotSettings:
    # Try loading from .env first
    settings = BotSettings()

    # If config.yaml exists, override or populate defaults
    yaml_path = "config.yaml"
    if os.path.exists(yaml_path):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    if "BOT_TOKEN" in data and (not settings.BOT_TOKEN or settings.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE"):
                        settings.BOT_TOKEN = str(data["BOT_TOKEN"])
                    if "ADMIN_IDS" in data and not settings.ADMIN_IDS:
                        settings.ADMIN_IDS = [int(x) for x in data["ADMIN_IDS"]]
                    if "LOG_CHAT_ID" in data and data["LOG_CHAT_ID"] and not settings.LOG_CHAT_ID:
                        settings.LOG_CHAT_ID = int(data["LOG_CHAT_ID"])
                    if "DATABASE_PATH" in data:
                        settings.DATABASE_PATH = str(data["DATABASE_PATH"])
        except Exception as e:
            print(f"[WARN] Failed to parse config.yaml: {e}")

    return settings
