"""Ejecuta una DEMO en segundo plano emitiendo cada movimiento por WebSocket.

Regla clave: la DEMO actualiza el último estado (sp_actualizar_estado) pero NUNCA llama a
sp_registrar_historial, así que sus movimientos no aparecen en la bitácora individual.
"""
import asyncio
import logging
from dataclasses import dataclass, field

from app.database import Database
from app.exceptions import Conflicto, NoEncontrado
from app.repositories import ComandoRepository, EstadoRepository
from app.websocket import ConnectionManager

log = logging.getLogger("iot.demo")

NOMBRES_DETENER = {"detener", "stop", "alto", "parar"}


@dataclass
class DemoActiva:
    id_demo: int
    tarea: asyncio.Task | None = None
    cancelar: asyncio.Event = field(default_factory=asyncio.Event)


class EjecutorDemo:
    def __init__(self, db: Database, estado: EstadoRepository, comandos: ComandoRepository, ws: ConnectionManager):
        self._db, self._estado, self._comandos, self._ws = db, estado, comandos, ws
        self._activas: dict[int, DemoActiva] = {}

    # --- consulta ---
    def en_curso(self, id_vehiculo: int) -> bool:
        return id_vehiculo in self._activas

    def id_demo_en_curso(self, id_vehiculo: int) -> int | None:
        activa = self._activas.get(id_vehiculo)
        return activa.id_demo if activa else None

    # --- control ---
    def iniciar(self, id_vehiculo: int, id_demo: int, movimientos: list[dict]) -> None:
        """Registra y lanza la DEMO. Sin await entre la verificación y el registro: no hay carreras."""
        if id_vehiculo in self._activas:
            raise Conflicto(f"El vehículo {id_vehiculo} ya está ejecutando la DEMO {self._activas[id_vehiculo].id_demo}")
        activa = DemoActiva(id_demo)
        self._activas[id_vehiculo] = activa
        activa.tarea = asyncio.create_task(self._correr(id_vehiculo, activa, movimientos))

    def cancelar(self, id_vehiculo: int) -> int:
        activa = self._activas.get(id_vehiculo)
        if activa is None:
            raise NoEncontrado(f"El vehículo {id_vehiculo} no tiene una DEMO en ejecución")
        activa.cancelar.set()
        return activa.id_demo

    async def cerrar(self) -> None:
        """Apagado de la API: cancela todas las DEMO y espera a que terminen."""
        tareas = []
        for activa in list(self._activas.values()):
            activa.cancelar.set()
            if activa.tarea:
                tareas.append(activa.tarea)
        if tareas:
            await asyncio.gather(*tareas, return_exceptions=True)

    # --- ejecución ---
    async def _esperar(self, cancelar: asyncio.Event, ms: int) -> bool:
        """Espera ms milisegundos; devuelve True si se canceló durante la espera."""
        if ms <= 0:
            return cancelar.is_set()
        try:
            await asyncio.wait_for(cancelar.wait(), timeout=ms / 1000)
            return True
        except asyncio.TimeoutError:
            return False

    def _fijar_estado(self, id_vehiculo: int, id_comando: int | None) -> None:
        with self._db.transaccion() as cx:
            actual = self._estado.obtener(cx, id_vehiculo)
            conectado = bool(actual["conectado"]) if actual else False
            self._estado.actualizar(cx, id_vehiculo, id_comando, conectado)

    def _fijar_detener(self, id_vehiculo: int) -> bool:
        """Si el catálogo tiene un comando de DETENER, lo deja como último comando del estado."""
        with self._db.transaccion() as cx:
            for c in self._comandos.listar_por_vehiculo(cx, id_vehiculo):
                if c["activo"] and c["nombre"].strip().lower() in NOMBRES_DETENER:
                    actual = self._estado.obtener(cx, id_vehiculo)
                    conectado = bool(actual["conectado"]) if actual else False
                    self._estado.actualizar(cx, id_vehiculo, c["id_comando"], conectado)
                    return True
        return False

    async def _correr(self, id_vehiculo: int, activa: DemoActiva, movimientos: list[dict]) -> None:
        total = len(movimientos)
        id_demo = activa.id_demo
        try:
            await self._ws.emitir(id_vehiculo, "demo_inicio", id_demo=id_demo, total_movimientos=total)
            for mov in movimientos:
                if activa.cancelar.is_set():
                    break
                await asyncio.to_thread(self._fijar_estado, id_vehiculo, mov["id_comando"])
                await self._ws.emitir(
                    id_vehiculo, "demo_movimiento", id_demo=id_demo, orden=mov["orden"], total_movimientos=total,
                    id_comando=mov["id_comando"], comando=mov["comando"], codigo=mov["codigo"],
                    duracion_ms=mov["duracion_ms"], pausa_ms=mov["pausa_ms"],
                )
                if await self._esperar(activa.cancelar, mov["duracion_ms"]):
                    break
                if await self._esperar(activa.cancelar, mov["pausa_ms"]):
                    break
            if activa.cancelar.is_set():
                detenido = await asyncio.to_thread(self._fijar_detener, id_vehiculo)
                await self._ws.emitir(id_vehiculo, "demo_cancelada", id_demo=id_demo, estado_detenido=detenido)
            else:
                await self._ws.emitir(id_vehiculo, "demo_fin", id_demo=id_demo, total_movimientos=total)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # falla de datos/RDS: se termina de forma controlada
            log.exception("Error en la DEMO %s del vehículo %s", id_demo, id_vehiculo)
            try:
                await asyncio.to_thread(self._fijar_detener, id_vehiculo)
            except Exception:
                log.exception("No se pudo fijar el estado detenido")
            await self._ws.emitir(id_vehiculo, "demo_error", id_demo=id_demo,
                                  detalle="La DEMO terminó por un error interno", tipo_error=type(exc).__name__)
        finally:
            self._activas.pop(id_vehiculo, None)
