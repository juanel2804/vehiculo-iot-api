import asyncio

from fastapi import APIRouter, Depends

from app.routers.comunes import RESP_404, RESP_409, RESP_AUTH
from app.schemas import ConexionIn, EstadoOut, HistorialOut
from app.security import exigir_llave
from app.servicios import Servicios, get_servicios

router = APIRouter(prefix="/vehiculos/{id_vehiculo}", tags=["Estado e historial"])


@router.get("/estado", response_model=EstadoOut | None, responses=RESP_404, summary="Último estado del vehículo",
            description="**SP:** `sp_obtener_vehiculo` (valida) y `sp_obtener_estado`. 404 si el vehículo no existe; "
                        "200 con `null` si existe pero todavía no tiene estado registrado.")
def obtener_estado(id_vehiculo: int, s: Servicios = Depends(get_servicios)):
    return s.estado.obtener_estado(id_vehiculo)


@router.get("/historial", response_model=list[HistorialOut], responses=RESP_404,
            summary="Últimos 10 movimientos individuales",
            description="**SP:** `sp_obtener_vehiculo` (valida) y `sp_obtener_historial`. Devuelve COMO MÁXIMO los 10 "
                        "movimientos individuales más recientes, del más reciente al más antiguo (si hay menos, solo los "
                        "disponibles). Los movimientos de una DEMO nunca aparecen aquí. El historial completo se conserva en RDS.")
def obtener_historial(id_vehiculo: int, s: Servicios = Depends(get_servicios)):
    return s.estado.obtener_historial(id_vehiculo)


@router.post("/conexion", response_model=EstadoOut | None, dependencies=[Depends(exigir_llave)],
             responses={**RESP_404, **RESP_409, **RESP_AUTH}, summary="Marcar el vehículo como conectado/desconectado",
             description="**SP:** `sp_obtener_vehiculo`, `sp_obtener_estado` y `sp_actualizar_estado`. Conserva el último comando. "
                         "Es la forma de indicar que el microcontrolador está en línea: un POST de movimiento no lo asume. "
                         "Exige `X-API-Key`.")
async def cambiar_conexion(id_vehiculo: int, datos: ConexionIn, s: Servicios = Depends(get_servicios)):
    estado = await asyncio.to_thread(s.estado.cambiar_conexion, id_vehiculo, datos.conectado)
    await s.ws.emitir(id_vehiculo, "conexion", conectado=datos.conectado)
    return estado
