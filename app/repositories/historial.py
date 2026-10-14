from app.database import llamar_sp


class HistorialRepository:
    """Stored Procedures de la bitácora de movimientos individuales."""

    def obtener(self, cx, id_vehiculo: int) -> list[dict]:
        # El SP devuelve todo el historial, del más reciente al más antiguo.
        return llamar_sp(cx, "sp_obtener_historial", id_vehiculo)

    def registrar(self, cx, id_vehiculo: int, id_comando: int, origen: str) -> None:
        llamar_sp(cx, "sp_registrar_historial", id_vehiculo, id_comando, origen)
