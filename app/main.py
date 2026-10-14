"""Punto de entrada: ensambla FastAPI, servicios, manejo de errores y routers."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import pymysql
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.exceptions import ErrorDominio
from app.routers import comandos, demos, estado, movimientos, vehiculos, ws
from app.servicios import Servicios

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("iot.api")

DESCRIPCION = """
API local (Dev) para controlar un vehículo IoT. Usa los **21 Stored Procedures** del esquema `vehiculo_iot` en Amazon RDS.

* **Movimiento individual**: `POST /movimientos` → actualiza `estado_vehiculo` + registra `historial_comandos` (una transacción) → evento WebSocket.
* **DEMO**: `POST /vehiculos/{id}/demos/{id_demo}/iniciar` → N movimientos por WebSocket; **no** se agregan al historial.
* **WebSocket**: `ws://localhost:8000/ws/vehiculos/{id_vehiculo}` (Swagger no documenta WebSocket; ver README).
* Las operaciones destructivas y de control exigen el header **X-API-Key** (botón *Authorize*).
"""

ETIQUETAS = [
    {"name": "Vehículos", "description": "CRUD de vehículos."},
    {"name": "Comandos", "description": "Catálogo de comandos de cada vehículo."},
    {"name": "Estado e historial", "description": "Último estado y últimos 10 movimientos individuales."},
    {"name": "Movimientos individuales", "description": "Ejecutar un comando: estado + historial + WebSocket."},
    {"name": "DEMO", "description": "DEMO y sus N movimientos; ejecución y cancelación por WebSocket."},
    {"name": "Sistema", "description": "Salud del servicio."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.servicios = Servicios(settings)
    log.info("API lista. RDS: %s/%s", settings.db_host, settings.db_name)
    yield
    await app.state.servicios.ejecutor.cerrar()
    app.state.servicios.db.cerrar()


app = FastAPI(title="API IoT Vehículo (Dev local)", version="1.0.0", description=DESCRIPCION,
              openapi_tags=ETIQUETAS, lifespan=lifespan)

for modulo in (vehiculos, comandos, estado, movimientos, demos):
    app.include_router(modulo.router)
app.include_router(ws.router)

# Página web de control (HTML + JS que consume esta misma API y el WebSocket)
app.mount("/control", StaticFiles(directory=Path(__file__).resolve().parent.parent / "web", html=True), name="control")


@app.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/control/")


@app.get("/salud", tags=["Sistema"], summary="¿La API está arriba?")
def salud():
    return {"estado": "ok"}


# ---------- Manejo de errores (sin exponer credenciales ni detalles internos) ----------
@app.exception_handler(ErrorDominio)
async def _error_dominio(_: Request, exc: ErrorDominio):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detalle})


@app.exception_handler(pymysql.err.IntegrityError)
async def _integridad(_: Request, exc: pymysql.err.IntegrityError):
    codigo = exc.args[0] if exc.args else 0
    mensajes = {
        1062: "Ya existe un registro con ese valor único (nombre, código u orden repetido)",
        1451: "No se puede eliminar: otros registros dependen de este",
        1452: "Referencia inválida: el registro relacionado no existe",
    }
    return JSONResponse(status_code=409, content={"detail": mensajes.get(codigo, "El dato viola una restricción de la base de datos")})


@app.exception_handler(pymysql.err.OperationalError)
async def _operacional(_: Request, exc: pymysql.err.OperationalError):
    log.error("Error operacional de MySQL: %s", exc.args[:1])
    return JSONResponse(status_code=503, content={"detail": "La base de datos en RDS no está disponible"})


@app.exception_handler(pymysql.err.InterfaceError)
async def _interfaz(_: Request, exc: pymysql.err.InterfaceError):
    return JSONResponse(status_code=503, content={"detail": "La conexión con RDS se interrumpió; reintenta"})


@app.exception_handler(Exception)
async def _inesperado(_: Request, exc: Exception):
    log.exception("Error no controlado")
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})
