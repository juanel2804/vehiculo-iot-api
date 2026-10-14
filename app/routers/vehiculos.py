from fastapi import APIRouter, Depends

from app.routers.comunes import RESP_404, RESP_AUTH
from app.schemas import Creado, DetalleVehiculoOut, Mensaje, VehiculoIn, VehiculoOut, VehiculoUpdate
from app.security import exigir_llave
from app.servicios import Servicios, get_servicios

router = APIRouter(prefix="/vehiculos", tags=["Vehículos"])


@router.get("", response_model=list[VehiculoOut], summary="Listar vehículos",
            description="**SP:** `sp_obtener_vehiculos`. Solo lectura.")
def listar(s: Servicios = Depends(get_servicios)):
    return s.vehiculos.listar()


@router.get("/{id_vehiculo}", response_model=DetalleVehiculoOut, responses=RESP_404,
            summary="Detalle de un vehículo con sus comandos, estado y DEMO",
            description="**SP:** `sp_obtener_vehiculo`, `sp_obtener_comandos_vehiculo`, `sp_obtener_estado`, "
                        "`sp_obtener_demos`. Si el vehículo no existe responde 404; si existe pero aún no tiene estado, "
                        "`estado` viene en `null`.")
def detalle(id_vehiculo: int, s: Servicios = Depends(get_servicios)):
    datos = s.vehiculos.detalle(id_vehiculo)
    datos["demo_en_ejecucion"] = s.ejecutor.id_demo_en_curso(id_vehiculo)
    return datos


@router.post("", response_model=Creado, status_code=201, summary="Crear un vehículo",
             description="**SP:** `sp_crear_vehiculo`. Devuelve el id generado.")
def crear(datos: VehiculoIn, s: Servicios = Depends(get_servicios)):
    return {"id": s.vehiculos.crear(datos.nombre, datos.modelo, datos.descripcion, datos.microcontrolador)}


@router.post("/{id_vehiculo}/actualizar", response_model=Mensaje, responses=RESP_404,
             summary="Actualizar un vehículo",
             description="**SP:** `sp_obtener_vehiculo` (valida que exista) y `sp_actualizar_vehiculo`.")
def actualizar(id_vehiculo: int, datos: VehiculoUpdate, s: Servicios = Depends(get_servicios)):
    s.vehiculos.actualizar(id_vehiculo, datos.nombre, datos.modelo, datos.descripcion, datos.microcontrolador, datos.activo)
    return {"mensaje": "Vehículo actualizado"}


@router.post("/{id_vehiculo}/eliminar", response_model=Mensaje, dependencies=[Depends(exigir_llave)],
             responses={**RESP_404, **RESP_AUTH}, summary="Eliminar un vehículo (requiere X-API-Key)",
             description="**SP:** `sp_obtener_vehiculo`, `sp_obtener_demos`, `sp_eliminar_demo` y `sp_eliminar_vehiculo`, en una "
                         "transacción. Primero elimina sus DEMO (sus movimientos bloquearían el borrado de los comandos) y "
                         "después el vehículo, que borra en cascada comandos, estado e historial. Exige el header `X-API-Key`.")
def eliminar(id_vehiculo: int, s: Servicios = Depends(get_servicios)):
    s.vehiculos.eliminar(id_vehiculo)
    return {"mensaje": "Vehículo eliminado"}
