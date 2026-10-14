"""Configuración de la API: todo se lee de variables de entorno / archivo .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_host: str
    db_port: int = 3306
    db_name: str = "vehiculo_iot"
    db_user: str
    db_password: str
    db_pool_size: int = 5
    db_connect_timeout: int = 10
    api_key: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
