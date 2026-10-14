"""Autorización por llave: protege eliminaciones y operaciones de control."""
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

_encabezado = APIKeyHeader(name="X-API-Key", auto_error=False, description="Llave requerida en operaciones de control y eliminación")


def exigir_llave(request: Request, llave: str | None = Depends(_encabezado)) -> None:
    if not llave:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el header X-API-Key")
    esperada = request.app.state.settings.api_key
    if not secrets.compare_digest(llave.encode(), esperada.encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "X-API-Key inválida")
