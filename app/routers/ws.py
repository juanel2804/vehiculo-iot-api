"""WebSocket por vehículo: wss://<dominio>/ws/vehiculos/{id_vehiculo} (ws://localhost:8000 en local) (Swagger no documenta WebSocket; ver README)."""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.exceptions import ErrorDominio, NoEncontrado

log = logging.getLogger("iot.ws")
router = APIRouter()


@router.websocket("/ws/vehiculos/{id_vehiculo}")
async def monitorear_vehiculo(ws: WebSocket, id_vehiculo: int):
    s = ws.app.state.servicios
    try:
        estado = await asyncio.to_thread(s.estado.obtener_estado, id_vehiculo)
    except NoEncontrado as exc:
        await ws.accept()
        await s.ws.enviar_a(ws, {"tipo": "error", "id_vehiculo": id_vehiculo, "detalle": exc.detalle})
        await ws.close(code=4404)
        return
    except ErrorDominio as exc:  # RDS no disponible
        await ws.accept()
        await s.ws.enviar_a(ws, {"tipo": "error", "id_vehiculo": id_vehiculo, "detalle": exc.detalle})
        await ws.close(code=1013)
        return

    await s.ws.conectar(id_vehiculo, ws)
    try:
        await s.ws.enviar_a(ws, {"tipo": "estado_inicial", "id_vehiculo": id_vehiculo, "estado": estado,
                                 "demo_en_ejecucion": s.ejecutor.id_demo_en_curso(id_vehiculo)})
        while True:
            texto = await ws.receive_text()  # solo para detectar la desconexión; "ping" responde "pong"
            if texto.strip().lower() == "ping":
                await s.ws.enviar_a(ws, {"tipo": "pong", "id_vehiculo": id_vehiculo})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Error en el WebSocket del vehículo %s", id_vehiculo)
    finally:
        s.ws.desconectar(id_vehiculo, ws)
