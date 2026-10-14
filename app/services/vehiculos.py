from app.database import Database
from app.exceptions import Conflicto, NoEncontrado
from app.repositories import ComandoRepository, DemoRepository, EstadoRepository, VehiculoRepository


class VehiculoService:
    """Reglas de negocio de vehículos. Es también quien valida que un vehículo exista/esté activo."""

    def __init__(self, db: Database, vehiculos: VehiculoRepository, comandos: ComandoRepository,
                 estado: EstadoRepository, demos: DemoRepository):
        self._db, self._vehiculos, self._comandos, self._estado, self._demos = db, vehiculos, comandos, estado, demos

    # --- validaciones reutilizables (reciben la conexión para participar en la misma transacción) ---
    def exigir_existente(self, cx, id_vehiculo: int) -> dict:
        v = self._vehiculos.obtener(cx, id_vehiculo)
        if v is None:
            raise NoEncontrado(f"El vehículo {id_vehiculo} no existe")
        return v

    def exigir_activo(self, cx, id_vehiculo: int) -> dict:
        v = self.exigir_existente(cx, id_vehiculo)
        if not v["activo"]:
            raise Conflicto(f"El vehículo {id_vehiculo} está inactivo")
        return v

    # --- casos de uso ---
    def listar(self) -> list[dict]:
        with self._db.transaccion() as cx:
            return self._vehiculos.listar(cx)

    def detalle(self, id_vehiculo: int) -> dict:
        with self._db.transaccion() as cx:
            v = self.exigir_existente(cx, id_vehiculo)
            v["comandos"] = self._comandos.listar_por_vehiculo(cx, id_vehiculo)
            v["estado"] = self._estado.obtener(cx, id_vehiculo)
            v["demos"] = self._demos.listar_por_vehiculo(cx, id_vehiculo)
            return v

    def crear(self, nombre, modelo, descripcion, microcontrolador) -> int:
        with self._db.transaccion() as cx:
            return self._vehiculos.crear(cx, nombre, modelo, descripcion, microcontrolador)

    def actualizar(self, id_vehiculo, nombre, modelo, descripcion, microcontrolador, activo) -> None:
        with self._db.transaccion() as cx:
            self.exigir_existente(cx, id_vehiculo)
            self._vehiculos.actualizar(cx, id_vehiculo, nombre, modelo, descripcion, microcontrolador, activo)

    def eliminar(self, id_vehiculo: int) -> None:
        with self._db.transaccion() as cx:
            self.exigir_existente(cx, id_vehiculo)
            # demo_movimientos -> comandos es ON DELETE RESTRICT: si la cascada borra primero los comandos,
            # MySQL rechaza el DELETE. Se eliminan antes las DEMO (y con ellas sus movimientos).
            for demo in self._demos.listar_por_vehiculo(cx, id_vehiculo):
                self._demos.eliminar(cx, demo["id_demo"])
            self._vehiculos.eliminar(cx, id_vehiculo)
