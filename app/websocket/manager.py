"""Administra los clientes WebSocket agrupados por vehículo."""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

log = logging.getLogger("iot.ws")


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectionManager:
    def __init__(self) -> None:
        self._clientes: dict[int, set[WebSocket]] = {}
        self._telemetria: dict[int, dict] = {}   # último reporte del ESP32 de cada vehículo (en memoria)

    def guardar_telemetria(self, id_vehiculo: int, datos: dict) -> None:
        self._telemetria[id_vehiculo] = {**datos, "timestamp": ahora_iso()}

    def telemetria(self, id_vehiculo: int) -> dict | None:
        return self._telemetria.get(id_vehiculo)

    def total(self, id_vehiculo: int) -> int:
        return len(self._clientes.get(id_vehiculo, ()))

    async def conectar(self, id_vehiculo: int, ws: WebSocket) -> None:
        await ws.accept()
        self._clientes.setdefault(id_vehiculo, set()).add(ws)

    def desconectar(self, id_vehiculo: int, ws: WebSocket) -> None:
        clientes = self._clientes.get(id_vehiculo)
        if clientes is None:
            return
        clientes.discard(ws)
        if not clientes:
            del self._clientes[id_vehiculo]

    async def _enviar(self, id_vehiculo: int, ws: WebSocket, mensaje: dict) -> None:
        try:
            await ws.send_json(mensaje)
        except Exception:  # cliente caído: se retira sin afectar a los demás
            log.info("Cliente WebSocket retirado del vehículo %s", id_vehiculo)
            self.desconectar(id_vehiculo, ws)

    async def enviar_a(self, ws: WebSocket, mensaje: dict) -> None:
        await ws.send_json(jsonable_encoder(mensaje))

    async def emitir(self, id_vehiculo: int, tipo: str, **datos) -> None:
        """Envía un evento solo a los clientes que monitorean ese vehículo."""
        mensaje = jsonable_encoder({"tipo": tipo, "id_vehiculo": id_vehiculo, **datos, "timestamp": ahora_iso()})
        clientes = list(self._clientes.get(id_vehiculo, ()))
        if clientes:
            await asyncio.gather(*(self._enviar(id_vehiculo, ws, mensaje) for ws in clientes))
