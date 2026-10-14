from fastapi import APIRouter, Depends

from app.routers.comunes import RESP_404, RESP_409, RESP_AUTH
from app.schemas import ComandoIn, ComandoOut, ComandoUpdate, Creado, Mensaje
from app.security import exigir_llave
from app.servicios import Servicios, get_servicios

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/comandos", tags=["Comandos"])


@router.get("", response_model=list[ComandoOut], responses=RESP_404, summary="Catálogo de comandos del vehículo",
            description="**SP:** `sp_obtener_vehiculo` (valida) y `sp_obtener_comandos_vehiculo`. Ordenado por código.")
def listar(id_vehiculo: int, s: Servicios = Depends(get_servicios)):
    return s.comandos.listar(id_vehiculo)


@router.post("", response_model=Creado, status_code=201, responses={**RESP_404, **RESP_409},
             summary="Crear un comando en el catálogo",
             description="**SP:** `sp_crear_comando`. Esto agrega un comando al catálogo; NO ejecuta ningún movimiento. "
                         "Nombre y código deben ser únicos dentro del vehículo (409 si se repiten).")
def crear(id_vehiculo: int, datos: ComandoIn, s: Servicios = Depends(get_servicios)):
    return {"id": s.comandos.crear(id_vehiculo, datos.nombre, datos.codigo, datos.descripcion)}


@router.post("/{id_comando}/actualizar", response_model=Mensaje, responses={**RESP_404, **RESP_409},
             summary="Actualizar un comando",
             description="**SP:** `sp_obtener_comandos_vehiculo` (valida que pertenezca al vehículo) y `sp_actualizar_comando`.")
def actualizar(id_vehiculo: int, id_comando: int, datos: ComandoUpdate, s: Servicios = Depends(get_servicios)):
    s.comandos.actualizar(id_vehiculo, id_comando, datos.nombre, datos.codigo, datos.descripcion, datos.activo)
    return {"mensaje": "Comando actualizado"}


@router.post("/{id_comando}/eliminar", response_model=Mensaje, dependencies=[Depends(exigir_llave)],
             responses={**RESP_404, **RESP_409, **RESP_AUTH}, summary="Eliminar un comando (requiere X-API-Key)",
             description="**SP:** `sp_obtener_comandos_vehiculo` (valida) y `sp_eliminar_comando`. Responde 409 si una DEMO "
                         "todavía usa el comando. Operación destructiva: exige `X-API-Key`.")
def eliminar(id_vehiculo: int, id_comando: int, s: Servicios = Depends(get_servicios)):
    s.comandos.eliminar(id_vehiculo, id_comando)
    return {"mensaje": "Comando eliminado"}
