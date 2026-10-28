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
    # Orígenes web que pueden llamar a la API desde el navegador (la página publicada en GitHub Pages)
    cors_origins: str = "https://juanel2804.github.io"
    # Copiloto con Claude (opcional): sin llave, el endpoint /copiloto responde 503
    anthropic_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
