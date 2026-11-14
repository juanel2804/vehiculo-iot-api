"""Voz a texto para el control en realidad virtual (Meta Quest).

El navegador del Quest no trae reconocimiento de voz, así que la página graba un audio corto
(MediaRecorder, webm/opus) y lo manda aquí. La API lo pasa a OpenAI (transcripción) y regresa el texto;
la página lo interpreta con las mismas reglas de voz del control (o con el copiloto).
La llave de OpenAI vive SOLO en el .env de la EC2 (OPENAI_API_KEY): nunca llega al navegador.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.routers.comunes import RESP_AUTH
from app.security import exigir_llave

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/voz", tags=["Voz (realidad virtual)"])

MAX_BYTES = 2 * 1024 * 1024          # ~2 MB: de sobra para 10 s de opus
URL_OPENAI = "https://api.openai.com/v1/audio/transcriptions"
PISTA = ("Órdenes para una excavadora de juguete: avanza, reversa, gira a la izquierda o derecha, "
         "rota la cabina, sube o baja la pala, alto, prende, apaga, segundos.")


@router.get("", summary="¿La voz a texto está disponible?")
def disponible(id_vehiculo: int, request: Request):
    return {"disponible": bool(request.app.state.settings.openai_api_key)}


@router.post("", dependencies=[Depends(exigir_llave)], responses={**RESP_AUTH},
             summary="Transcribir una orden de voz (requiere X-API-Key)",
             description="Cuerpo: el audio crudo (`audio/webm`, `audio/ogg` o `audio/mp4`, máx. 2 MB). "
                         "Responde `{\"texto\": \"avanza dos segundos\"}`. **No mueve nada**: la página decide.")
async def transcribir(id_vehiculo: int, request: Request):
    llave = request.app.state.settings.openai_api_key
    if not llave:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Voz no configurada (falta OPENAI_API_KEY en la EC2)")
    tipo = (request.headers.get("content-type") or "audio/webm").split(";")[0].strip()
    if not tipo.startswith("audio/"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Manda el audio con Content-Type audio/…")
    # el límite se revisa ANTES de juntar todo en memoria: primero el Content-Length y luego mientras llega
    demasiado = HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Audio demasiado largo (máx. 2 MB)")
    try:
        if int(request.headers.get("content-length") or 0) > MAX_BYTES:
            raise demasiado
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Content-Length inválido")
    partes, total = [], 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > MAX_BYTES:
            raise demasiado
        partes.append(trozo)
    audio = b"".join(partes)
    if not audio:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Audio vacío")
    ext = {"audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(tipo, "webm")
    modelo = request.app.state.settings.openai_modelo_voz
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post(URL_OPENAI, headers={"Authorization": f"Bearer {llave}"},
                               data={"model": modelo, "language": "es", "prompt": PISTA},
                               files={"file": (f"orden.{ext}", audio, tipo)})
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No se pudo contactar el servicio de voz")
    if r.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"El servicio de voz respondió {r.status_code}")
    return {"texto": (r.json().get("text") or "").strip(), "modelo": modelo}
