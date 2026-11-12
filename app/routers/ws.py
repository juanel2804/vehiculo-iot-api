"""WebSocket por vehículo: wss://<dominio>/ws/vehiculos/{id_vehiculo} (ws://localhost:8000 en local) (Swagger no documenta WebSocket; ver README).

Además de recibir eventos, los clientes pueden mandar JSON:
  {"tipo":"auth","llave":"<X-API-Key>"}            → {"tipo":"auth","ok":true|false}
  {"tipo":"control","c":"AVANZAR","ms":0}          → evento "control" a todos (canal rápido del gamepad;
                                                      ms=0 continuo renovado, ms>0 pulso exacto en el ESP32)
  {"tipo":"telemetria","rssi":-50,"ip":"…"}        → evento "telemetria" (lo manda el ESP32)
  {"tipo":"ping","p":123}                          → {"tipo":"pong","p":123}
"control" y "telemetria" exigen haber mandado la llave antes. El historial en RDS se guarda en
segundo plano solo cuando cambia el movimiento, para no frenar el canal con escrituras.

Sala de turnos (invitados sin llave, de uno en uno; ver app/websocket/sala.py):
  {"tipo":"sala","accion":"abrir","segundos":60}   → solo administrador (ya mandó la llave). Acciones: ver, abrir,
                                                      cerrar, config, pausar, reanudar, siguiente, mas, sacar, dar.
                                                      Responde {"tipo":"sala_admin","codigo":"ABCD"} (va en el QR).
  {"tipo":"unirse","nombre":"Ana","ficha":"<secreto del teléfono>","codigo":"ABCD"} → {"tipo":"unido","id":…}
  {"tipo":"salir"}                                  → deja la fila o su turno
  {"tipo":"demo","id":3} · {"tipo":"demo_cancelar"} → DEMO por el WebSocket (administrador o quien tiene el turno)
Todos reciben {"tipo":"sala", abierta, pausada, segundos, admin, turno:{id,nombre,restan_ms,total_ms}, fila:[…]}.
Con la sala abierta, "control" se obedece solo a quien tiene el turno; el administrador mueve cuando no hay
turno o la sala está en pausa (su DETENER pasa siempre). Con la sala cerrada todo funciona como antes.
"""
import asyncio
import json
import logging
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.exceptions import ErrorDominio, NoEncontrado
from app.services.ejecutor_demo import NOMBRES_DETENER
from app.websocket.sala import SEGUNDOS_VALIDOS, SalaError

log = logging.getLogger("iot.ws")
router = APIRouter()

MAX_PULSO_MS = 10000
ORIGEN_RAPIDO = "WEB-RAPIDO"
MAX_FALLOS_CODIGO = 8      # intentos de entrar con un código equivocado antes de cerrar la conexión


def _accion_sala(sala, m: dict) -> bool:
    """Aplica una acción del administrador. Devuelve True si hay que detener el vehículo."""
    accion = m.get("accion")
    if accion == "abrir":
        sala.abrir(m.get("segundos"))
    elif accion == "cerrar":
        return sala.cerrar()
    elif accion == "config":
        sala.config(m.get("segundos"))
    elif accion == "pausar":
        return sala.pausar()
    elif accion == "reanudar":
        sala.reanudar()
    elif accion == "siguiente":
        return sala.siguiente()
    elif accion == "mas":
        sala.mas(m.get("segundos"))
    elif accion == "sacar":
        return sala.sacar(m.get("id"))
    elif accion == "dar":
        return sala.dar(m.get("id"))
    return False


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
    sala = s.salas.sala(id_vehiculo)
    es_admin = False              # ya usó el panel de la sala (cuenta como administrador presente)
    ficha, jugador = None, None   # invitado: su lugar en la sala
    fallos, ultimo_rechazo = 0, 0.0

    async def cargar_catalogo() -> dict[str, dict]:
        lista = await asyncio.to_thread(s.comandos.listar, id_vehiculo)
        cat = {c["nombre"].upper(): c for c in lista if c["activo"]}
        detener = next((n for n in cat if n.strip().lower() in NOMBRES_DETENER), None)
        if detener:
            s.salas.nombre_detener[id_vehiculo] = cat[detener]["nombre"]
        return cat

    def tiene_control() -> bool:
        return autorizado or (jugador is not None and sala.jugadores.get(ficha) is jugador and sala.puede_controlar(ficha))

    try:
        await s.ws.enviar_a(ws, {"tipo": "estado_inicial", "id_vehiculo": id_vehiculo, "estado": estado,
                                 "demo_en_ejecucion": s.ejecutor.id_demo_en_curso(id_vehiculo),
                                 "telemetria": s.ws.telemetria(id_vehiculo), "sala": sala.estado()})
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
                    catalogo = await cargar_catalogo()
                await s.ws.enviar_a(ws, {"tipo": "auth", "ok": autorizado})

            elif tipo == "sala":
                if not autorizado:
                    await s.ws.enviar_a(ws, {"tipo": "error", "detalle": "Solo el administrador maneja la sala"})
                    continue
                if not es_admin:
                    es_admin = True
                    sala.admin_entra()
                detener = _accion_sala(sala, m)
                await s.salas.publicar(id_vehiculo, detener)
                await s.ws.enviar_a(ws, {"tipo": "sala_admin", "codigo": sala.codigo, "segundos_validos": list(SEGUNDOS_VALIDOS)})

            elif tipo == "unirse":
                try:
                    nuevo = sala.unirse(m.get("ficha"), m.get("nombre"), m.get("codigo"))
                except SalaError as exc:
                    fallos += 1
                    await s.ws.enviar_a(ws, {"tipo": "sala_error", "detalle": str(exc)})
                    if fallos >= MAX_FALLOS_CODIGO:
                        await ws.close(code=4429)
                        break
                    continue
                if nuevo is not jugador:
                    if jugador is not None and sala.jugadores.get(ficha) is jugador and sala.desconectado(ficha):
                        await s.salas.detener(id_vehiculo)
                    ficha, jugador = nuevo.ficha, nuevo
                    sala.conectado(ficha)
                await s.ws.enviar_a(ws, {"tipo": "unido", "id": jugador.id, "nombre": jugador.nombre})
                await s.salas.publicar(id_vehiculo)

            elif tipo == "salir":
                if jugador is not None and sala.jugadores.get(ficha) is jugador:
                    detener = sala.salir(ficha)
                    ficha, jugador = None, None
                    await s.salas.publicar(id_vehiculo, detener)

            elif tipo in ("demo", "demo_cancelar"):
                if not tiene_control():
                    await s.ws.enviar_a(ws, {"tipo": "error", "detalle": "No es tu turno"})
                    continue
                try:
                    if tipo == "demo_cancelar":
                        s.ejecutor.cancelar(id_vehiculo)
                        continue
                    id_demo = int(m.get("id"))
                    movimientos = await asyncio.to_thread(s.demos.preparar_inicio, id_vehiculo, id_demo)
                    if tiene_control():       # el turno pudo acabarse mientras se leía la DEMO de RDS
                        s.ejecutor.iniciar(id_vehiculo, id_demo, movimientos)
                        sala.demo_invitado = not autorizado
                except ErrorDominio as exc:
                    await s.ws.enviar_a(ws, {"tipo": "error", "detalle": exc.detalle})
                except (TypeError, ValueError):
                    continue

            elif tipo == "control":
                nombre = str(m.get("c", "")).upper()
                if autorizado:
                    if not sala.admin_puede_controlar() and nombre.strip().lower() not in NOMBRES_DETENER:
                        ahora = asyncio.get_running_loop().time()
                        if ahora - ultimo_rechazo > 1:      # el control continuo se renueva 4 veces por segundo: un aviso basta
                            ultimo_rechazo = ahora
                            await s.ws.enviar_a(ws, {"tipo": "error", "detalle": f"{sala.nombre_del_turno()} tiene el turno. Pausa la sala para tomar el control."})
                        continue
                elif not tiene_control():
                    ahora = asyncio.get_running_loop().time()
                    if ahora - ultimo_rechazo > 1:
                        ultimo_rechazo = ahora
                        detalle = "No es tu turno" if sala.abierta else "Manda primero tu llave (tipo auth)"
                        await s.ws.enviar_a(ws, {"tipo": "error", "detalle": detalle})
                    continue
                if s.ejecutor.en_curso(id_vehiculo):
                    await s.ws.enviar_a(ws, {"tipo": "error", "detalle": "Hay una DEMO en ejecución; cancélala primero"})
                    continue
                if catalogo is None:
                    catalogo = await cargar_catalogo()
                    if not tiene_control():   # el turno pudo acabarse mientras se leía el catálogo
                        continue
                comando = catalogo.get(nombre)
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
        try:
            if es_admin:
                sala.admin_sale()
            if jugador is not None and sala.jugadores.get(ficha) is jugador:
                await s.salas.publicar(id_vehiculo, sala.desconectado(ficha))
        except Exception:
            log.exception("No se pudo actualizar la sala al desconectarse un cliente del vehículo %s", id_vehiculo)
