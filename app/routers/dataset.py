"""Fotos para entrenar la IA que reconoce la excavadora desde la cámara cenital (pestaña Ve ahí).

Cada foto llega con su etiqueta (recuadro + punto del frente + punto de atrás, en píxeles de la foto)
y se guarda en disco fuera del repo: <carpeta padre del repo>/dataset/vehiculo_<id>/. El modelo
(YOLO11-pose) se entrena en la lap con iot/2/2.7/entrenamiento/entrenar.py.
"""
import base64
import binascii
import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.comunes import RESP_AUTH
from app.security import exigir_llave

CARPETA = Path(__file__).resolve().parents[3] / "dataset"
MAX_BYTES = 600_000

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/dataset", tags=["Entrenamiento (IA de visión)"])


class FotoIn(BaseModel):
    imagen: str = Field(description="JPEG en base64 (con o sin prefijo data:image/jpeg;base64,)")
    caja: list[float] = Field(min_length=4, max_length=4, description="x1, y1, x2, y2 en píxeles")
    frente: list[float] = Field(min_length=2, max_length=2, description="x, y del frente (pala)")
    atras: list[float] = Field(min_length=2, max_length=2, description="x, y de la parte de atrás")
    origen: str = Field("manual", pattern="^(marcador|manual)$")


def _carpeta(id_vehiculo: int) -> Path:
    return CARPETA / f"vehiculo_{id_vehiculo}"


def _total(carpeta: Path) -> int:
    return sum(1 for _ in carpeta.glob("*.jpg")) if carpeta.exists() else 0


@router.get("", summary="Cuántas fotos de entrenamiento hay")
def contar(id_vehiculo: int):
    return {"total": _total(_carpeta(id_vehiculo))}


@router.post("", dependencies=[Depends(exigir_llave)], responses=RESP_AUTH,
             summary="Guardar una foto etiquetada (requiere X-API-Key)")
def guardar(id_vehiculo: int, foto: FotoIn):
    try:
        jpg = base64.b64decode(foto.imagen.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "La imagen no es base64 válido")
    if len(jpg) > MAX_BYTES or not jpg.startswith(b"\xff\xd8"):
        raise HTTPException(422, "Se espera un JPEG de hasta 600 KB")

    carpeta = _carpeta(id_vehiculo)
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = f"{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 1_000_000:06d}"
    (carpeta / f"{nombre}.jpg").write_bytes(jpg)
    etiqueta = {"caja": foto.caja, "frente": foto.frente, "atras": foto.atras, "origen": foto.origen}
    (carpeta / f"{nombre}.json").write_text(json.dumps(etiqueta), encoding="utf-8")
    return {"guardada": nombre, "total": _total(carpeta)}
