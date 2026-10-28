import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.routers.comunes import RESP_404, RESP_AUTH
from app.security import exigir_llave
from app.servicios import Servicios, get_servicios

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/copiloto", tags=["Copiloto (IA)"])


class OrdenIn(BaseModel):
    texto: str = Field(min_length=1, max_length=300, examples=["haz una zanja: baja la pala, avanza 2 segundos y súbela"])


class PasoOut(BaseModel):
    comando: str
    id_comando: int
    duracion_ms: int


class PlanOut(BaseModel):
    explicacion: str
    pasos: list[PasoOut]
    modelo: str | None = None


@router.get("", summary="¿El copiloto está disponible?")
def disponible(id_vehiculo: int, s: Servicios = Depends(get_servicios)):
    return {"disponible": s.copiloto.disponible}


@router.post("", response_model=PlanOut, dependencies=[Depends(exigir_llave)], responses={**RESP_404, **RESP_AUTH},
             summary="Planear movimientos con lenguaje natural (requiere X-API-Key)",
             description="Claude convierte la orden en una secuencia de comandos del catálogo del vehículo "
                         "(`sp_obtener_comandos_vehiculo`). **No ejecuta nada**: la página manda cada paso con "
                         "`POST /movimientos`, así quedan en el historial y salen por WebSocket como siempre.")
async def planear(id_vehiculo: int, orden: OrdenIn, s: Servicios = Depends(get_servicios)):
    catalogo = await asyncio.to_thread(s.comandos.listar, id_vehiculo)
    return await s.copiloto.planear(orden.texto, catalogo)
