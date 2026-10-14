from app.database import Database
from app.exceptions import NoEncontrado
from app.repositories import ComandoRepository
from app.services.vehiculos import VehiculoService


class ComandoService:
    """Catálogo de comandos: cada vehículo tiene el suyo."""

    def __init__(self, db: Database, comandos: ComandoRepository, vehiculos: VehiculoService):
        self._db, self._comandos, self._vehiculos = db, comandos, vehiculos

    def buscar_en_catalogo(self, cx, id_vehiculo: int, id_comando: int) -> dict:
        for c in self._comandos.listar_por_vehiculo(cx, id_vehiculo):
            if c["id_comando"] == id_comando:
                return c
        raise NoEncontrado(f"El comando {id_comando} no existe en el catálogo del vehículo {id_vehiculo}")

    def buscar_por_codigo(self, cx, id_vehiculo: int, codigo: int) -> dict:
        for c in self._comandos.listar_por_vehiculo(cx, id_vehiculo):
            if c["codigo"] == codigo:
                return c
        raise NoEncontrado(f"El vehículo {id_vehiculo} no tiene un comando con código {codigo}")

    def listar(self, id_vehiculo: int) -> list[dict]:
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_existente(cx, id_vehiculo)
            return self._comandos.listar_por_vehiculo(cx, id_vehiculo)

    def crear(self, id_vehiculo, nombre, codigo, descripcion) -> int:
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_existente(cx, id_vehiculo)
            return self._comandos.crear(cx, id_vehiculo, nombre, codigo, descripcion)

    def actualizar(self, id_vehiculo, id_comando, nombre, codigo, descripcion, activo) -> None:
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_existente(cx, id_vehiculo)
            self.buscar_en_catalogo(cx, id_vehiculo, id_comando)
            self._comandos.actualizar(cx, id_comando, nombre, codigo, descripcion, activo)

    def eliminar(self, id_vehiculo: int, id_comando: int) -> None:
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_existente(cx, id_vehiculo)
            self.buscar_en_catalogo(cx, id_vehiculo, id_comando)
            self._comandos.eliminar(cx, id_comando)
