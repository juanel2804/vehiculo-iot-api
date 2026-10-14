from app.database import Database
from app.repositories import EstadoRepository, HistorialRepository
from app.services.vehiculos import VehiculoService

LIMITE_HISTORIAL = 10


class EstadoService:
    """Consultas de estado e historial, y cambio del indicador de conexión."""

    def __init__(self, db: Database, estado: EstadoRepository, historial: HistorialRepository, vehiculos: VehiculoService):
        self._db, self._estado, self._historial, self._vehiculos = db, estado, historial, vehiculos

    def obtener_estado(self, id_vehiculo: int) -> dict | None:
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_existente(cx, id_vehiculo)
            return self._estado.obtener(cx, id_vehiculo)

    def obtener_historial(self, id_vehiculo: int) -> list[dict]:
        """Máximo los 10 movimientos individuales más recientes (el SP ya los ordena de nuevo a antiguo)."""
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_existente(cx, id_vehiculo)
            return self._historial.obtener(cx, id_vehiculo)[:LIMITE_HISTORIAL]

    def cambiar_conexion(self, id_vehiculo: int, conectado: bool) -> dict:
        """Marca al vehículo como conectado/desconectado conservando su último comando."""
        with self._db.transaccion() as cx:
            self._vehiculos.exigir_activo(cx, id_vehiculo)
            actual = self._estado.obtener(cx, id_vehiculo)
            id_comando = actual["id_comando"] if actual else None
            self._estado.actualizar(cx, id_vehiculo, id_comando, conectado)
            return self._estado.obtener(cx, id_vehiculo)
