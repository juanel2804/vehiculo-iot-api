"""Respuestas de error reutilizables para la documentación de Swagger."""
from app.schemas import ErrorOut

RESP_404 = {404: {"model": ErrorOut, "description": "El recurso no existe"}}
RESP_409 = {409: {"model": ErrorOut, "description": "Conflicto con las reglas de negocio o con los datos existentes"}}
RESP_AUTH = {
    401: {"model": ErrorOut, "description": "Falta el header X-API-Key"},
    403: {"model": ErrorOut, "description": "X-API-Key inválida"},
}
RESP_503 = {503: {"model": ErrorOut, "description": "No hay conexión con la base de datos en RDS"}}
