"""Modelos Pydantic de entrada y salida (validación de tipos, rangos y longitudes)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Id = Field(gt=0, description="Identificador entero positivo")


# ---------- Vehículos ----------
class VehiculoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=80, examples=["Retroexcavadora"])
    modelo: Optional[str] = Field(default=None, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=255)
    microcontrolador: Optional[str] = Field(default=None, max_length=50, examples=["ESP32"])


class VehiculoUpdate(VehiculoIn):
    activo: bool = True


class VehiculoOut(BaseModel):
    id_vehiculo: int
    nombre: str
    modelo: Optional[str] = None
    descripcion: Optional[str] = None
    microcontrolador: Optional[str] = None
    fecha_registro: Optional[datetime] = None
    activo: bool


# ---------- Comandos ----------
class ComandoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=60, examples=["Avanzar"])
    codigo: int = Field(ge=0, le=65535, examples=[1])
    descripcion: Optional[str] = Field(default=None, max_length=255)


class ComandoUpdate(ComandoIn):
    activo: bool = True


class ComandoOut(BaseModel):
    id_comando: int
    id_vehiculo: int
    nombre: str
    codigo: int
    descripcion: Optional[str] = None
    activo: bool


# ---------- Estado e historial ----------
class EstadoOut(BaseModel):
    id_vehiculo: int
    vehiculo: str
    id_comando: Optional[int] = None
    comando: Optional[str] = None
    codigo: Optional[int] = None
    conectado: bool
    fecha_actualizacion: Optional[datetime] = None


class ConexionIn(BaseModel):
    conectado: bool


class HistorialOut(BaseModel):
    id_historial: int
    id_vehiculo: int
    comando: Optional[str] = None
    codigo: Optional[int] = None
    fecha_hora: Optional[datetime] = None
    origen: str


# ---------- Movimiento individual ----------
class MovimientoIn(BaseModel):
    id_vehiculo: int = Id
    id_comando: Optional[int] = Field(default=None, gt=0, description="ID del comando en el catálogo del vehículo")
    codigo: Optional[int] = Field(default=None, ge=0, le=65535, description="Alternativa: código del comando")
    origen: str = Field(default="API", min_length=1, max_length=30, pattern=r"^[A-Za-z0-9_\-\. ]+$")

    @model_validator(mode="after")
    def _uno_de_los_dos(self):
        if (self.id_comando is None) == (self.codigo is None):
            raise ValueError("Envía exactamente uno: id_comando o codigo")
        return self


class MovimientoOut(BaseModel):
    id_vehiculo: int
    id_comando: int
    comando: str
    codigo: int
    origen: str
    conectado: bool
    timestamp: datetime


# ---------- DEMO ----------
class DemoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=255)


class DemoUpdate(DemoIn):
    activo: bool = True


class DemoOut(BaseModel):
    id_demo: int
    id_vehiculo: int
    nombre: str
    descripcion: Optional[str] = None
    activo: bool


class DemoMovimientoIn(BaseModel):
    id_comando: int = Id
    orden: int = Field(ge=1, le=10000)
    duracion_ms: int = Field(ge=0, le=600000)
    pausa_ms: int = Field(default=0, ge=0, le=600000)


class DemoMovimientoOut(BaseModel):
    id_demo_movimiento: int
    orden: int
    id_comando: int
    comando: str
    codigo: int
    duracion_ms: int
    pausa_ms: int


class DemoIniciada(BaseModel):
    id_vehiculo: int
    id_demo: int
    total_movimientos: int
    estado: str = "iniciada"


class DemoCancelada(BaseModel):
    id_vehiculo: int
    id_demo: int
    estado: str = "cancelacion_solicitada"


# ---------- Respuestas genéricas ----------
class Creado(BaseModel):
    id: int


class Mensaje(BaseModel):
    mensaje: str


class ErrorOut(BaseModel):
    detail: str


class DetalleVehiculoOut(VehiculoOut):
    comandos: list[ComandoOut]
    estado: Optional[EstadoOut] = None
    demos: list[DemoOut]
    demo_en_ejecucion: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
