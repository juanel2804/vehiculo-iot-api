import asyncio

from fastapi import APIRouter, Depends

from app.routers.comunes import RESP_404, RESP_409, RESP_AUTH
from app.schemas import MovimientoIn, MovimientoOut
from app.security import exigir_llave
from app.servicios import Servicios, get_servicios
from app.websocket.manager import ahora_iso

router = APIRouter(prefix="/movimientos", tags=["Movimientos individuales"])


@router.post("", response_model=MovimientoOut, status_code=201, dependencies=[Depends(exigir_llave)],
             responses={**RESP_404, **RESP_409, **RESP_AUTH},
             summary="Registrar un movimiento individual (requiere X-API-Key)",
             description="Flujo: valida que el vehículo exista y esté activo, y que el comando exista, esté activo y "
                         "pertenezca a ese vehículo → `sp_actualizar_estado` + `sp_registrar_historial` en UNA transacción "
                         "→ commit en RDS → notificación `movimiento` por WebSocket.\n\n"
                         "**SP:** `sp_obtener_vehiculo`, `sp_obtener_comandos_vehiculo`, `sp_obtener_estado`, "
                         "`sp_actualizar_estado`, `sp_registrar_historial`.\n\n"
                         "Si se rechaza (404/409/422) no cambia el estado ni el historial y no se emite ningún evento. "
                         "Envía `id_comando` **o** `codigo`.")
async def registrar_movimiento(datos: MovimientoIn, s: Servicios = Depends(get_servicios)):
    resultado = await asyncio.to_thread(s.movimientos.ejecutar, datos.id_vehiculo, datos.id_comando, datos.codigo, datos.origen)
    await s.ws.emitir(datos.id_vehiculo, "movimiento", comando=resultado["comando"], codigo=resultado["codigo"],
                      id_comando=resultado["id_comando"], origen=resultado["origen"])
    return {**resultado, "timestamp": ahora_iso()}
