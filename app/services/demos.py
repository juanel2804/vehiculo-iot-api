from typing import Callable

from app.database import Database
from app.exceptions import Conflicto, NoEncontrado
from app.repositories import DemoRepository
from app.services.comandos import ComandoService
from app.services.vehiculos import VehiculoService


class DemoService:
    """Administración de DEMO y de sus N movimientos (catálogo en RDS)."""

    def __init__(self, db: Database, demos: DemoRepository, vehiculos: VehiculoService, comandos: ComandoService,
                 demo_en_curso: Callable[[int], bool]):
        self._db, self._demos, self._vehiculos, self._comandos = db, demos, vehiculos, comandos
        self._demo_en_curso = demo_en_curso

    # --- validaciones ---
    def _exigir_demo(self, cx, id_vehiculo: int, id_demo: int) -> dict:
        """La DEMO debe existir y pertenecer al vehículo indicado."""
        self._vehiculos.exigir_existente(cx, id_vehiculo)
        for d in self._demos.listar_por_vehiculo(cx, id_vehiculo):
            if d["id_demo"] == id_demo:
                return d
        raise NoEncontrado(f"La DEMO {id_demo} no existe en el vehículo {id_vehiculo}")

    def _exigir_movimiento(self, cx, id_demo: int, id_mov: int) -> dict:
        for m in self._demos.listar_movimientos(cx, id_demo):
            if m["id_demo_movimiento"] == id_mov:
                return m
        raise NoEncontrado(f"El movimiento {id_mov} no existe en la DEMO {id_demo}")

    def _no_modificar_en_curso(self, id_vehiculo: int, id_demo: int) -> None:
        if self._demo_en_curso(id_vehiculo):
            raise Conflicto(f"El vehículo {id_vehiculo} está ejecutando una DEMO; no se puede modificar ahora")

    # --- DEMO ---
    def listar(self, id_vehiculo: int) -> list[dict]:
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_existente(cx, id_vehiculo)
            return self._demos.listar_por_vehiculo(cx, id_vehiculo)

    def crear(self, id_vehiculo: int, nombre: str, descripcion: str | None) -> int:
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_existente(cx, id_vehiculo)
            return self._demos.crear(cx, id_vehiculo, nombre, descripcion)

    def actualizar(self, id_vehiculo, id_demo, nombre, descripcion, activo) -> None:
        self._no_modificar_en_curso(id_vehiculo, id_demo)
        with self._db.transaccion() as cx:
            self._exigir_demo(cx, id_vehiculo, id_demo)
            self._demos.actualizar(cx, id_demo, nombre, descripcion, activo)

    def eliminar(self, id_vehiculo: int, id_demo: int) -> None:
        self._no_modificar_en_curso(id_vehiculo, id_demo)
        with self._db.transaccion() as cx:
            self._exigir_demo(cx, id_vehiculo, id_demo)
            self._demos.eliminar(cx, id_demo)

    # --- movimientos de la DEMO ---
    def listar_movimientos(self, id_vehiculo: int, id_demo: int) -> list[dict]:
        with self._db.transaccion() as cx:
            self._exigir_demo(cx, id_vehiculo, id_demo)
            return self._demos.listar_movimientos(cx, id_demo)

    def agregar_movimiento(self, id_vehiculo, id_demo, id_comando, orden, duracion_ms, pausa_ms) -> None:
        self._no_modificar_en_curso(id_vehiculo, id_demo)
        with self._db.transaccion() as cx:
            self._exigir_demo(cx, id_vehiculo, id_demo)
            self._comandos.buscar_en_catalogo(cx, id_vehiculo, id_comando)  # rechaza comandos de otro vehículo
            self._demos.agregar_movimiento(cx, id_demo, id_comando, orden, duracion_ms, pausa_ms)

    def actualizar_movimiento(self, id_vehiculo, id_demo, id_mov, id_comando, orden, duracion_ms, pausa_ms) -> None:
        self._no_modificar_en_curso(id_vehiculo, id_demo)
        with self._db.transaccion() as cx:
            self._exigir_demo(cx, id_vehiculo, id_demo)
            self._exigir_movimiento(cx, id_demo, id_mov)
            self._comandos.buscar_en_catalogo(cx, id_vehiculo, id_comando)
            self._demos.actualizar_movimiento(cx, id_mov, id_comando, orden, duracion_ms, pausa_ms)

    def eliminar_movimiento(self, id_vehiculo: int, id_demo: int, id_mov: int) -> None:
        self._no_modificar_en_curso(id_vehiculo, id_demo)
        with self._db.transaccion() as cx:
            self._exigir_demo(cx, id_vehiculo, id_demo)
            self._exigir_movimiento(cx, id_demo, id_mov)
            self._demos.eliminar_movimiento(cx, id_mov)

    # --- preparación del arranque ---
    def preparar_inicio(self, id_vehiculo: int, id_demo: int) -> list[dict]:
        """Valida vehículo activo, DEMO activa del vehículo y devuelve sus N movimientos ordenados desde RDS."""
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_activo(cx, id_vehiculo)
            demo = self._exigir_demo(cx, id_vehiculo, id_demo)
            if not demo["activo"]:
                raise Conflicto(f"La DEMO {id_demo} está inactiva")
            movimientos = self._demos.listar_movimientos(cx, id_demo)
            if not movimientos:
                raise Conflicto(f"La DEMO {id_demo} no tiene movimientos")
            return movimientos
