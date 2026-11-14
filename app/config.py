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
    # Voz a texto para la página de realidad virtual (opcional): sin llave, /voz responde 503
    openai_api_key: str | None = None
    openai_modelo_voz: str = "gpt-4o-mini-transcribe"
    openai_modelo_tts: str = "gpt-4o-mini-tts"     # voz del asistente holográfico (KAI)
    openai_voz_tts: str = "onyx"
    # Sala de turnos con código FIJO (4 letras sin 0/O/1/I): el QR ya no cambia. Vacío = código nuevo cada vez
    sala_codigo: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
