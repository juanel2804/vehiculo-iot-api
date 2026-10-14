from app.database import llamar_sp


class EstadoRepository:
    """Stored Procedures del último estado del vehículo."""

    def obtener(self, cx, id_vehiculo: int) -> dict | None:
        filas = llamar_sp(cx, "sp_obtener_estado", id_vehiculo)
        return filas[0] if filas else None

    def actualizar(self, cx, id_vehiculo: int, id_comando: int | None, conectado: bool) -> None:
        llamar_sp(cx, "sp_actualizar_estado", id_vehiculo, id_comando, conectado)
