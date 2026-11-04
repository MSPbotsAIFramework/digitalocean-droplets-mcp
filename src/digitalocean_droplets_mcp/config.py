"""Non-credential runtime configuration.

Credentials are never configured here -- they arrive per request on HTTP
headers (see middleware.py). This module only covers the HTTP listener and
upstream base URL.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings sourced from environment variables.

    `extra="ignore"` is required: the deployment environment injects
    variables this project does not declare, and strict parsing would crash
    the container on startup.
    """

    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080
    digitalocean_base_url: str = "https://api.digitalocean.com/v2"


settings = Settings()
