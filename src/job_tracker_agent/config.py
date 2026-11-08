"""XDG configuration and token credential management.

Adheres to docs/adr/0003-xdg-configuration-and-credentials.md.
"""

import json
import os
from pathlib import Path
from typing import Any, Optional
import tomllib
import tomli_w
from pydantic import BaseModel, Field


def get_config_dir() -> Path:
    """Return the base XDG configuration directory for job-tracker."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        base_dir = Path(xdg_config_home)
    else:
        base_dir = Path.home() / ".config"
    config_dir = base_dir / "job-tracker"
    config_dir.mkdir(parents=True, exist_ok=True)
    try:
        config_dir.chmod(0o700)
    except Exception:
        pass
    return config_dir


def get_config_path() -> Path:
    """Return the absolute path to config.toml."""
    return get_config_dir() / "config.toml"


def get_tokens_path() -> Path:
    """Return the absolute path to tokens.json."""
    return get_config_dir() / "tokens.json"


def get_database_path() -> Path:
    """Return the absolute path to the local SQLite sync database."""
    return get_config_dir() / "sync.db"


class NotionConfig(BaseModel):
    """Notion API integration settings."""

    api_key: Optional[str] = None
    database_id: Optional[str] = None
    parent_page_id: Optional[str] = None


class LLMConfig(BaseModel):
    """LLM extractor settings (Cloud API default with local Ollama fallback)."""

    provider: str = Field(default="gemini", description="gemini | openai | anthropic | ollama")
    model_name: str = Field(default="gemini-2.5-flash", description="Model identifier")
    api_key: Optional[str] = None
    api_base: Optional[str] = None


class SyncConfig(BaseModel):
    """Synchronization options."""

    backfill_days: int = Field(default=14, description="Default historical window in days on first sync")
    polling_interval_minutes: int = Field(default=30, description="Scheduled cadence for systemd timer")
    desktop_alerts: bool = Field(default=True, description="Enable notify-send desktop notifications")


class AppConfig(BaseModel):
    """Root application configuration."""

    notion: NotionConfig = Field(default_factory=NotionConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)


def load_config() -> AppConfig:
    """Load configuration from config.toml or return default structure."""
    path = get_config_path()
    if not path.exists():
        config = AppConfig()
        save_config(config)
        return config

    with open(path, "rb") as f:
        data = tomllib.load(f)
    return AppConfig.model_validate(data)


def save_config(config: AppConfig) -> None:
    """Serialize and save configuration to config.toml."""
    path = get_config_path()
    data = config.model_dump(mode="json", exclude_none=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
    try:
        path.chmod(0o600)
    except Exception:
        pass


def load_tokens() -> dict[str, Any]:
    """Load OAuth tokens and credentials dictionary from tokens.json."""
    path = get_tokens_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_tokens(tokens: dict[str, Any]) -> None:
    """Save OAuth tokens with strict 0600 file permissions."""
    path = get_tokens_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    try:
        path.chmod(0o600)
    except Exception:
        pass
