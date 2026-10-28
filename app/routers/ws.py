"""WebSocket por vehículo: wss://<dominio>/ws/vehiculos/{id_vehiculo} (ws://localhost:8000 en local) (Swagger no documenta WebSocket; ver README).

Además de recibir eventos, los clientes pueden mandar JSON:
  {"tipo":"auth","llave":"<X-API-Key>"}            → {"tipo":"auth","ok":true|false}
  {"tipo":"control","c":"AVANZAR","ms":0}          → evento "control" a todos (canal rápido del gamepad;
                                                      ms=0 continuo renovado, ms>0 pulso exacto en el ESP32)
  {"tipo":"telemetria","rssi":-50,"ip":"…"}        → evento "telemetria" (lo manda el ESP32)
  {"tipo":"ping","p":123}                          → {"tipo":"pong","p":123}
"control" y "telemetria" exigen haber mandado la llave antes. El historial en RDS se guarda en
segundo plano solo cuando cambia el movimiento, para no frenar el canal con escrituras.
"""
import asyncio
import json
import logging
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.exceptions import ErrorDominio, NoEncontrado

log = logging.getLogger("iot.ws")
router = APIRouter()

MAX_PULSO_MS = 10000
ORIGEN_RAPIDO = "WEB-RAPIDO"


def _guardar_movimiento(s, id_vehiculo: int, id_comando: int) -> None:
    try:
        s.movimientos.ejecutar(id_vehiculo, id_comando, None, ORIGEN_RAPIDO)
    except Exception:  # el control ya llegó al ESP32; un fallo de RDS no lo detiene
        log.warning("No se guardó en el historial el movimiento rápido %s del vehículo %s", id_comando, id_vehiculo)


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
    autorizado = False
    catalogo: dict[str, dict] | None = None
    ultimo_guardado = None
    try:
        await s.ws.enviar_a(ws, {"tipo": "estado_inicial", "id_vehiculo": id_vehiculo, "estado": estado,
                                 "demo_en_ejecucion": s.ejecutor.id_demo_en_curso(id_vehiculo),
                                 "telemetria": s.ws.telemetria(id_vehiculo)})
        while True:
            texto = (await ws.receive_text()).strip()
            if texto.lower() == "ping":
                await s.ws.enviar_a(ws, {"tipo": "pong", "id_vehiculo": id_vehiculo})
                continue
            try:
                m = json.loads(texto)
            except ValueError:
                continue
            if not isinstance(m, dict):
                continue
            tipo = m.get("tipo")

            if tipo == "ping":
                await s.ws.enviar_a(ws, {"tipo": "pong", "p": m.get("p")})

            elif tipo == "auth":
                llave = str(m.get("llave", ""))
                autorizado = secrets.compare_digest(llave.encode(), ws.app.state.settings.api_key.encode())
                if autorizado and catalogo is None:   # se carga aquí para que el primer movimiento no espere a RDS
                    lista = await asyncio.to_thread(s.comandos.listar, id_vehiculo)
                    catalogo = {c["nombre"].upper(): c for c in lista if c["activo"]}
                await s.ws.enviar_a(ws, {"tipo": "auth", "ok": autorizado})

            elif tipo == "control":
                if not autorizado:
                    await s.ws.enviar_a(ws, {"tipo": "error", "detalle": "Manda primero tu llave (tipo auth)"})
                    continue
                if s.ejecutor.en_curso(id_vehiculo):
                    await s.ws.enviar_a(ws, {"tipo": "error", "detalle": "Hay una DEMO en ejecución; cancélala primero"})
                    continue
                if catalogo is None:
                    lista = await asyncio.to_thread(s.comandos.listar, id_vehiculo)
                    catalogo = {c["nombre"].upper(): c for c in lista if c["activo"]}
                comando = catalogo.get(str(m.get("c", "")).upper())
                if not comando:
                    continue
                try:
                    ms = max(0, min(MAX_PULSO_MS, int(m.get("ms", 0))))
                except (TypeError, ValueError):
                    ms = 0
                await s.ws.emitir(id_vehiculo, "control", comando=comando["nombre"], ms=ms, origen=ORIGEN_RAPIDO)
                if comando["id_comando"] != ultimo_guardado:
                    ultimo_guardado = comando["id_comando"]
                    asyncio.create_task(asyncio.to_thread(_guardar_movimiento, s, id_vehiculo, comando["id_comando"]))

            elif tipo == "telemetria" and autorizado:
                datos = {k: m[k] for k in ("rssi", "ip", "comando", "uptime") if k in m}
                s.ws.guardar_telemetria(id_vehiculo, datos)
                await s.ws.emitir(id_vehiculo, "telemetria", **datos)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Error en el WebSocket del vehículo %s", id_vehiculo)
    finally:
        s.ws.desconectar(id_vehiculo, ws)
