"""Unified configuration loader for NexusDev.

Loads configuration from:
1. Environment variables
2. YAML config files
3. Default values
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration."""
    model_config = SettingsConfigDict(env_prefix="DB_")
    
    url: str = "sqlite+aiosqlite:///./nexusdev.db"
    echo: bool = False


class LLMProviderSettings(BaseSettings):
    """LLM provider configuration."""
    
    name: str = "openai"
    api_key: str = ""
    base_url: str | None = None
    model: str = "gpt-4"
    temperature: float = 0.2
    timeout_seconds: int = 120
    max_retries: int = 3


class RedisSettings(BaseSettings):
    """Redis configuration."""
    model_config = SettingsConfigDict(env_prefix="REDIS_")
    
    url: str | None = None
    enabled: bool = False


class APISettings(BaseSettings):
    """API server configuration."""
    model_config = SettingsConfigDict(env_prefix="API_")
    
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False


class WorkerSettings(BaseSettings):
    """Worker configuration."""
    model_config = SettingsConfigDict(env_prefix="WORKER_")
    
    poll_interval: int = 5
    max_concurrent: int = 4
    stage_timeout_minutes: int = 30


class HITLSettings(BaseSettings):
    """HITL configuration."""
    model_config = SettingsConfigDict(env_prefix="HITL_")
    
    default_timeout_hours: int = 24
    enable_notifications: bool = False


class SOPSettings(BaseSettings):
    """SOP configuration."""
    
    config_path: str = "config/sop/default.yaml"
    auto_approve: bool = False


class Settings(BaseSettings):
    """Unified application settings.
    
    Loads from environment variables and config files.
    """
    model_config = SettingsConfigDict(
        env_file="config/env/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # Application
    app_name: str = "NexusDev"
    version: str = "0.1.0"
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")
    
    # Sub-settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMProviderSettings = Field(default_factory=LLMProviderSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    api: APISettings = Field(defaultFactory=APISettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    hitl: HITLSettings = Field(default_factory=HITLSettings)
    sop: SOPSettings = Field(default_factory=SOPSettings)
    
    # Feature flags
    enable_openclaw: bool = False
    enable_openwork: bool = False
    
    # Paths
    artifacts_path: str = "./artifacts"
    
    @classmethod
    def from_yaml(cls, path: str) -> "Settings":
        """Load settings from YAML file.
        
        Args:
            path: Path to YAML config file
            
        Returns:
            Settings instance
        """
        if not Path(path).exists():
            return cls()
        
        with open(path) as f:
            config = yaml.safe_load(f)
        
        return cls(**config)
    
    def to_yaml(self, path: str) -> None:
        """Save settings to YAML file."""
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance.
    
    Returns:
        Settings instance (cached)
    """
    return Settings()


def load_sop_config(path: str | None = None) -> dict[str, Any]:
    """Load SOP configuration from YAML.
    
    Args:
        path: Path to SOP config file (default from settings)
        
    Returns:
        SOP configuration dictionary
    """
    if path is None:
        path = get_settings().sop.config_path
    
    if not Path(path).exists():
        raise FileNotFoundError(f"SOP config not found: {path}")
    
    with open(path) as f:
        return yaml.safe_load(f)


def load_model_config(path: str = "config/models/default.yaml") -> dict[str, Any]:
    """Load model configuration from YAML.
    
    Args:
        path: Path to model config file
        
    Returns:
        Model configuration dictionary
    """
    if not Path(path).exists():
        return {}
    
    with open(path) as f:
        return yaml.safe_load(f)
