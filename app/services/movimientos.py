from typing import Callable

from app.database import Database
from app.exceptions import Conflicto
from app.repositories import EstadoRepository, HistorialRepository
from app.services.comandos import ComandoService
from app.services.vehiculos import VehiculoService


class MovimientoService:
    """Movimiento individual: valida, actualiza el estado y registra el historial en UNA transacción."""

    def __init__(self, db: Database, vehiculos: VehiculoService, comandos: ComandoService,
                 estado: EstadoRepository, historial: HistorialRepository,
                 demo_en_curso: Callable[[int], bool]):
        self._db, self._vehiculos, self._comandos = db, vehiculos, comandos
        self._estado, self._historial = estado, historial
        self._demo_en_curso = demo_en_curso

    def ejecutar(self, id_vehiculo: int, id_comando: int | None, codigo: int | None, origen: str) -> dict:
        if self._demo_en_curso(id_vehiculo):
            raise Conflicto(f"El vehículo {id_vehiculo} está ejecutando una DEMO; cancélala antes de enviar movimientos")
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_activo(cx, id_vehiculo)
            if id_comando is not None:
                comando = self._comandos.buscar_en_catalogo(cx, id_vehiculo, id_comando)
            else:
                comando = self._comandos.buscar_por_codigo(cx, id_vehiculo, codigo)
            if not comando["activo"]:
                raise Conflicto(f"El comando {comando['id_comando']} está inactivo")
            actual = self._estado.obtener(cx, id_vehiculo)
            # conectado lo reporta el vehículo: no se asume verdadero por recibir una solicitud HTTP
            conectado = bool(actual["conectado"]) if actual else False
            self._estado.actualizar(cx, id_vehiculo, comando["id_comando"], conectado)
            self._historial.registrar(cx, id_vehiculo, comando["id_comando"], origen)
        # el commit ocurrió al salir del with: recién ahora se puede notificar por WebSocket
        return {"id_vehiculo": id_vehiculo, "id_comando": comando["id_comando"], "comando": comando["nombre"],
                "codigo": comando["codigo"], "origen": origen, "conectado": conectado}
