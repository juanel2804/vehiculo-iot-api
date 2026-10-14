import asyncio

from fastapi import APIRouter, Depends

from app.routers.comunes import RESP_404, RESP_409, RESP_AUTH
from app.schemas import (Creado, DemoCancelada, DemoIn, DemoIniciada, DemoMovimientoIn, DemoMovimientoOut, DemoOut,
                         DemoUpdate, Mensaje)
from app.security import exigir_llave
from app.servicios import Servicios, get_servicios

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/demos", tags=["DEMO"])
LLAVE = [Depends(exigir_llave)]


# ---------- DEMO ----------
@router.get("", response_model=list[DemoOut], responses=RESP_404, summary="Listar las DEMO del vehículo",
            description="**SP:** `sp_obtener_vehiculo` (valida) y `sp_obtener_demos`.")
def listar(id_vehiculo: int, s: Servicios = Depends(get_servicios)):
    return s.demos.listar(id_vehiculo)


@router.post("", response_model=Creado, status_code=201, responses=RESP_404, summary="Crear una DEMO",
             description="**SP:** `sp_crear_demo`. Crea la DEMO vacía; sus movimientos se agregan con "
                         "`POST /vehiculos/{id}/demos/{id_demo}/movimientos`.")
def crear(id_vehiculo: int, datos: DemoIn, s: Servicios = Depends(get_servicios)):
    return {"id": s.demos.crear(id_vehiculo, datos.nombre, datos.descripcion)}


@router.post("/cancelar", response_model=DemoCancelada, status_code=202, dependencies=LLAVE,
             responses={**RESP_404, **RESP_AUTH}, summary="Cancelar la DEMO en ejecución (requiere X-API-Key)",
             description="Detiene de inmediato la emisión de movimientos posteriores. Si el catálogo tiene un comando "
                         "DETENER, lo deja como último comando con `sp_actualizar_estado`. Emite `demo_cancelada` por WebSocket.")
async def cancelar(id_vehiculo: int, s: Servicios = Depends(get_servicios)):
    id_demo = s.ejecutor.cancelar(id_vehiculo)
    return {"id_vehiculo": id_vehiculo, "id_demo": id_demo}


@router.post("/{id_demo}/actualizar", response_model=Mensaje, responses={**RESP_404, **RESP_409},
             summary="Actualizar una DEMO", description="**SP:** `sp_obtener_demos` (valida) y `sp_actualizar_demo`.")
def actualizar(id_vehiculo: int, id_demo: int, datos: DemoUpdate, s: Servicios = Depends(get_servicios)):
    s.demos.actualizar(id_vehiculo, id_demo, datos.nombre, datos.descripcion, datos.activo)
    return {"mensaje": "DEMO actualizada"}


@router.post("/{id_demo}/eliminar", response_model=Mensaje, dependencies=LLAVE,
             responses={**RESP_404, **RESP_409, **RESP_AUTH}, summary="Eliminar una DEMO (requiere X-API-Key)",
             description="**SP:** `sp_obtener_demos` (valida) y `sp_eliminar_demo`. Borra también sus movimientos. "
                         "Operación destructiva: exige `X-API-Key`.")
def eliminar(id_vehiculo: int, id_demo: int, s: Servicios = Depends(get_servicios)):
    s.demos.eliminar(id_vehiculo, id_demo)
    return {"mensaje": "DEMO eliminada"}


@router.post("/{id_demo}/iniciar", response_model=DemoIniciada, status_code=202, dependencies=LLAVE,
             responses={**RESP_404, **RESP_409, **RESP_AUTH}, summary="Iniciar una DEMO por WebSocket (requiere X-API-Key)",
             description="Valida vehículo activo y DEMO activa que pertenezca al vehículo, lee sus N movimientos de RDS con "
                         "`sp_obtener_movimientos_demo` y los emite por WebSocket en orden, respetando `duracion_ms` y "
                         "`pausa_ms`. Eventos: `demo_inicio`, `demo_movimiento` (N veces), `demo_fin` / `demo_cancelada` / `demo_error`.\n\n"
                         "Actualiza el último comando con `sp_actualizar_estado` pero **NO** llama a `sp_registrar_historial`: "
                         "los movimientos de una DEMO nunca llegan al historial. Responde 202 de inmediato; la secuencia corre en "
                         "segundo plano. 409 si el vehículo ya ejecuta otra DEMO.")
async def iniciar(id_vehiculo: int, id_demo: int, s: Servicios = Depends(get_servicios)):
    movimientos = await asyncio.to_thread(s.demos.preparar_inicio, id_vehiculo, id_demo)
    s.ejecutor.iniciar(id_vehiculo, id_demo, movimientos)
    return {"id_vehiculo": id_vehiculo, "id_demo": id_demo, "total_movimientos": len(movimientos)}


# ---------- Movimientos de la DEMO ----------
@router.get("/{id_demo}/movimientos", response_model=list[DemoMovimientoOut], responses=RESP_404,
            summary="Movimientos ordenados de una DEMO",
            description="**SP:** `sp_obtener_demos` (valida) y `sp_obtener_movimientos_demo`. Ordenados por `orden`.")
def listar_movimientos(id_vehiculo: int, id_demo: int, s: Servicios = Depends(get_servicios)):
    return s.demos.listar_movimientos(id_vehiculo, id_demo)


@router.post("/{id_demo}/movimientos", response_model=Mensaje, status_code=201, responses={**RESP_404, **RESP_409},
             summary="Agregar un movimiento a una DEMO",
             description="**SP:** `sp_obtener_comandos_vehiculo` (el comando debe ser del vehículo) y `sp_agregar_movimiento_demo`. "
                         "`orden` debe ser único dentro de la DEMO (409 si se repite).")
def agregar_movimiento(id_vehiculo: int, id_demo: int, datos: DemoMovimientoIn, s: Servicios = Depends(get_servicios)):
    s.demos.agregar_movimiento(id_vehiculo, id_demo, datos.id_comando, datos.orden, datos.duracion_ms, datos.pausa_ms)
    return {"mensaje": "Movimiento agregado a la DEMO"}


@router.post("/{id_demo}/movimientos/{id_movimiento}/actualizar", response_model=Mensaje,
             responses={**RESP_404, **RESP_409}, summary="Actualizar un movimiento de la DEMO",
             description="**SP:** `sp_obtener_movimientos_demo` (valida), `sp_obtener_comandos_vehiculo` y `sp_actualizar_movimiento_demo`.")
def actualizar_movimiento(id_vehiculo: int, id_demo: int, id_movimiento: int, datos: DemoMovimientoIn,
                          s: Servicios = Depends(get_servicios)):
    s.demos.actualizar_movimiento(id_vehiculo, id_demo, id_movimiento, datos.id_comando, datos.orden,
                                  datos.duracion_ms, datos.pausa_ms)
    return {"mensaje": "Movimiento actualizado"}


@router.post("/{id_demo}/movimientos/{id_movimiento}/eliminar", response_model=Mensaje, dependencies=LLAVE,
             responses={**RESP_404, **RESP_409, **RESP_AUTH}, summary="Eliminar un movimiento de la DEMO (requiere X-API-Key)",
             description="**SP:** `sp_obtener_movimientos_demo` (valida) y `sp_eliminar_movimiento_demo`. Exige `X-API-Key`.")
def eliminar_movimiento(id_vehiculo: int, id_demo: int, id_movimiento: int, s: Servicios = Depends(get_servicios)):
    s.demos.eliminar_movimiento(id_vehiculo, id_demo, id_movimiento)
    return {"mensaje": "Movimiento eliminado"}
