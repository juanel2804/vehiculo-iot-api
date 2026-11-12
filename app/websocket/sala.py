"""Sala de turnos por vehículo: los invitados controlan de uno en uno, sin conocer la X-API-Key.

El administrador (quien sí mandó la llave) abre la sala y recibe un código que va en el QR. Cada invitado
se forma con su nombre; el servidor reparte turnos con cronómetro y solo obedece al que tiene el turno.
Todo vive en memoria: si la API se reinicia, la sala queda cerrada (que es lo seguro).

`Sala` es lógica pura (sin red, con reloj inyectable para probarla). `GestorSalas` la conecta con el
WebSocket: publica el estado, manda DETENER cuando alguien pierde el control y lleva el reloj de turnos.
"""
import asyncio
import logging
import re
import secrets
import time
from dataclasses import dataclass

log = logging.getLogger("iot.sala")

SEGUNDOS_VALIDOS = (30, 60, 90, 120)
MAX_FILA = 40
MAX_TURNO = 600.0        # tope de un turno con tiempo extra (s)
GRACIA_TURNO = 8.0       # si el que tiene el turno se desconecta, se le espera esto (s)
GRACIA_FILA = 45.0       # lugar guardado en la fila a quien se desconecta (s)
GRACIA_ADMIN = 90.0      # sin administrador conectado, la sala se pausa sola (s)
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sin 0/O ni 1/I: se dictan sin confusión
_FICHA = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class SalaError(Exception):
    """Motivo, en español, por el que no se pudo hacer algo en la sala."""


@dataclass
class Jugador:
    ficha: str                        # secreto del teléfono: con él recupera su lugar al reconectarse
    id: str                           # identificador público (lo ven todos)
    nombre: str
    conexiones: int = 0
    desconectado_en: float | None = None


def limpiar_nombre(nombre) -> str:
    texto = re.sub(r"\s+", " ", "".join(c for c in str(nombre or "") if c.isprintable())).strip()[:14]
    return texto or "Jugador"


class Sala:
    def __init__(self, reloj=time.monotonic):
        self._reloj = reloj
        self._marca = reloj()
        self.abierta = False
        self.pausada = False
        self.segundos = 60
        self.codigo = ""
        self.jugadores: dict[str, Jugador] = {}
        self.fila: list[str] = []
        self.turno: str | None = None
        self.restan = 0.0             # segundos que le quedan al turno
        self.total = 0.0              # duración con la que empezó (más el tiempo extra)
        self.expulsados: set[str] = set()
        self.admins = 0
        self._sin_admin: float | None = self._marca
        self.demo_invitado = False    # la DEMO en curso la lanzó un invitado: se cancela al acabar su turno

    # ------------------------------ consultas ------------------------------
    def puede_controlar(self, ficha: str | None) -> bool:
        return bool(ficha) and self.abierta and not self.pausada and self.turno == ficha

    def admin_puede_controlar(self) -> bool:
        return self.turno is None or self.pausada

    def nombre_del_turno(self) -> str:
        return self.jugadores[self.turno].nombre if self.turno else ""

    def _publico(self, ficha: str) -> dict:
        j = self.jugadores[ficha]
        return {"id": j.id, "nombre": j.nombre, "conectado": j.conexiones > 0}

    def estado(self) -> dict:
        turno = None
        if self.turno:
            turno = {**self._publico(self.turno), "restan_ms": max(0, int(self.restan * 1000)), "total_ms": int(self.total * 1000)}
        return {"abierta": self.abierta, "pausada": self.pausada, "segundos": self.segundos, "admin": self.admins > 0,
                "turno": turno, "fila": [self._publico(f) for f in self.fila]}

    # ------------------------------ administrador ------------------------------
    def admin_entra(self) -> None:
        self.admins += 1
        self._sin_admin = None

    def admin_sale(self) -> None:
        self.admins = max(0, self.admins - 1)
        if self.admins == 0:
            self._sin_admin = self._reloj()

    def abrir(self, segundos=None) -> str:
        self.config(segundos)
        if not self.abierta:
            self._vaciar()
            self.abierta = True
            self.codigo = "".join(secrets.choice(ALFABETO) for _ in range(4))
        return self.codigo

    def cerrar(self) -> bool:
        """Cierra y saca a todos. Devuelve True si alguien tenía el turno (hay que detener el vehículo)."""
        habia = self.turno is not None
        self._vaciar()
        self.abierta = False
        self.codigo = ""
        return habia

    def _vaciar(self) -> None:
        self.jugadores.clear()
        self.fila.clear()
        self.expulsados.clear()
        self.turno, self.restan, self.total, self.pausada = None, 0.0, 0.0, False

    def config(self, segundos) -> None:
        try:
            segundos = int(segundos)
        except (TypeError, ValueError):
            return
        if segundos in SEGUNDOS_VALIDOS:
            self.segundos = segundos

    def pausar(self) -> bool:
        self.tick()
        self.pausada = True
        return self.turno is not None

    def reanudar(self) -> None:
        self.tick()
        self.pausada = False
        self.tick()

    def siguiente(self) -> bool:
        return self._fin_turno()

    def mas(self, segundos) -> None:
        try:
            extra = max(0, min(120, int(segundos)))
        except (TypeError, ValueError):
            return
        if self.turno:
            nuevo = min(MAX_TURNO, self.restan + extra)
            self.total += nuevo - self.restan
            self.restan = nuevo

    def _ficha_de(self, id_publico) -> str | None:
        return next((f for f, j in self.jugadores.items() if j.id == id_publico), None)

    def sacar(self, id_publico) -> bool:
        ficha = self._ficha_de(id_publico)
        if not ficha:
            return False
        self.expulsados.add(ficha)
        return self._quitar(ficha)

    def dar(self, id_publico) -> bool:
        """Le da el turno ya a ese jugador (lo pasa al frente y termina el turno actual)."""
        ficha = self._ficha_de(id_publico)
        if not ficha or ficha == self.turno:
            return False
        if ficha in self.fila:
            self.fila.remove(ficha)
        self.fila.insert(0, ficha)
        return self._fin_turno()

    # ------------------------------ invitados ------------------------------
    def unirse(self, ficha, nombre, codigo) -> Jugador:
        if not self.abierta:
            raise SalaError("La sala está cerrada. Pídele al administrador que la abra.")
        if not isinstance(ficha, str) or not _FICHA.match(ficha):
            raise SalaError("Ficha inválida.")
        if not secrets.compare_digest(str(codigo or "").strip().upper().encode(), self.codigo.encode()):
            raise SalaError("Código de sala incorrecto. Escanea otra vez el QR.")
        if ficha in self.expulsados:
            raise SalaError("El administrador te sacó de esta sala.")
        j = self.jugadores.get(ficha)
        if j is None:
            if len(self.fila) >= MAX_FILA:
                raise SalaError("La fila está llena. Intenta en un momento.")
            j = self.jugadores[ficha] = Jugador(ficha, secrets.token_hex(3), limpiar_nombre(nombre))
        else:
            j.nombre = limpiar_nombre(nombre)
        if ficha != self.turno and ficha not in self.fila:
            if len(self.fila) >= MAX_FILA:
                raise SalaError("La fila está llena. Intenta en un momento.")
            self.fila.append(ficha)
        return j

    def conectado(self, ficha: str) -> None:
        """Un socket de ese jugador está en línea (se llama tras `unirse`); si no hay turno, puede tocarle ya."""
        j = self.jugadores.get(ficha)
        if j:
            j.conexiones += 1
            j.desconectado_en = None
            self.tick()

    def desconectado(self, ficha: str) -> bool:
        """Devuelve True si era quien tenía el turno y se quedó sin conexiones (hay que detener el vehículo)."""
        j = self.jugadores.get(ficha)
        if not j:
            return False
        j.conexiones = max(0, j.conexiones - 1)
        if j.conexiones == 0:
            j.desconectado_en = self._reloj()
            return ficha == self.turno
        return False

    def salir(self, ficha: str) -> bool:
        return self._quitar(ficha)

    # ------------------------------ reloj ------------------------------
    def _quitar(self, ficha: str) -> bool:
        if ficha in self.fila:
            self.fila.remove(ficha)
        tenia = ficha == self.turno
        if tenia:
            self._fin_turno()
        self.jugadores.pop(ficha, None)
        return tenia

    def _fin_turno(self) -> bool:
        if not self.turno:
            return False
        self.jugadores.pop(self.turno, None)
        self.turno, self.restan, self.total = None, 0.0, 0.0
        self.tick()
        return True

    def _asignar(self) -> bool:
        for ficha in self.fila:
            if self.jugadores[ficha].conexiones > 0:
                self.fila.remove(ficha)
                self.turno, self.restan, self.total = ficha, float(self.segundos), float(self.segundos)
                return True
        return False

    def tick(self) -> tuple[bool, bool]:
        """Avanza el reloj. Devuelve (cambió el estado, hay que detener el vehículo)."""
        ahora = self._reloj()
        dt, self._marca = ahora - self._marca, ahora
        if not self.abierta:
            return False, False
        cambio = detener = False
        if self.admins == 0 and not self.pausada and self._sin_admin is not None and ahora - self._sin_admin > GRACIA_ADMIN:
            self.pausada = cambio = True          # nadie vigila: se congela
            detener = self.turno is not None
        for ficha in list(self.fila):
            j = self.jugadores[ficha]
            if j.conexiones == 0 and ahora - (j.desconectado_en or ahora) > GRACIA_FILA:
                self.fila.remove(ficha)
                del self.jugadores[ficha]
                cambio = True
        if self.turno and not self.pausada:
            j = self.jugadores[self.turno]
            self.restan -= dt
            if self.restan <= 0 or (j.conexiones == 0 and ahora - (j.desconectado_en or ahora) > GRACIA_TURNO):
                del self.jugadores[self.turno]
                self.turno, self.restan, self.total = None, 0.0, 0.0
                cambio = detener = True
        if self.turno is None and not self.pausada and self._asignar():
            cambio = True
        return cambio, detener


class GestorSalas:
    """Una `Sala` por vehículo, conectada al WebSocket (estado para todos, DETENER y reloj de turnos)."""

    PASO = 0.25              # s entre revisiones del reloj
    REFRESCO = 5.0           # s entre estados repetidos (por si un teléfono perdió alguno)

    def __init__(self, ws, ejecutor):
        self._ws, self._ejecutor = ws, ejecutor
        self._salas: dict[int, Sala] = {}
        self._relojes: dict[int, asyncio.Task] = {}
        self.nombre_detener: dict[int, str] = {}

    def sala(self, id_vehiculo: int) -> Sala:
        if id_vehiculo not in self._salas:
            self._salas[id_vehiculo] = Sala()
        return self._salas[id_vehiculo]

    async def publicar(self, id_vehiculo: int, detener: bool = False) -> None:
        """Tras cualquier cambio: detiene el vehículo si alguien perdió el control y avisa a todos."""
        sala = self.sala(id_vehiculo)
        if detener:
            await self.detener(id_vehiculo)
        await self._ws.emitir(id_vehiculo, "sala", **sala.estado())
        self._vigilar(id_vehiculo)

    async def detener(self, id_vehiculo: int) -> None:
        sala = self.sala(id_vehiculo)
        if sala.demo_invitado and self._ejecutor.en_curso(id_vehiculo):
            try:
                self._ejecutor.cancelar(id_vehiculo)
            except Exception:
                pass
        sala.demo_invitado = False
        await self._ws.emitir(id_vehiculo, "control", comando=self.nombre_detener.get(id_vehiculo, "DETENER"), ms=0, origen="TURNOS")

    def _vigilar(self, id_vehiculo: int) -> None:
        tarea = self._relojes.get(id_vehiculo)
        if self.sala(id_vehiculo).abierta and (tarea is None or tarea.done()):
            self._relojes[id_vehiculo] = asyncio.create_task(self._reloj(id_vehiculo))

    async def _reloj(self, id_vehiculo: int) -> None:
        sala, ultimo = self.sala(id_vehiculo), 0.0
        try:
            while sala.abierta:
                await asyncio.sleep(self.PASO)
                cambio, detener = sala.tick()
                ahora = time.monotonic()
                if detener:
                    await self.detener(id_vehiculo)
                if cambio or ahora - ultimo > self.REFRESCO:
                    ultimo = ahora
                    await self._ws.emitir(id_vehiculo, "sala", **sala.estado())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Falló el reloj de turnos del vehículo %s", id_vehiculo)

    async def cerrar(self) -> None:
        """Apagado de la API."""
        tareas = [t for t in self._relojes.values() if not t.done()]
        for t in tareas:
            t.cancel()
        if tareas:
            await asyncio.gather(*tareas, return_exceptions=True)
