from app.database import llamar_sp


class VehiculoRepository:
    """Stored Procedures de vehículos."""

    def listar(self, cx) -> list[dict]:
        return llamar_sp(cx, "sp_obtener_vehiculos")

    def obtener(self, cx, id_vehiculo: int) -> dict | None:
        filas = llamar_sp(cx, "sp_obtener_vehiculo", id_vehiculo)
        return filas[0] if filas else None

    def crear(self, cx, nombre, modelo, descripcion, microcontrolador) -> int:
        return llamar_sp(cx, "sp_crear_vehiculo", nombre, modelo, descripcion, microcontrolador)[0]["id_vehiculo"]

    def actualizar(self, cx, id_vehiculo, nombre, modelo, descripcion, microcontrolador, activo) -> None:
        llamar_sp(cx, "sp_actualizar_vehiculo", id_vehiculo, nombre, modelo, descripcion, microcontrolador, activo)

    def eliminar(self, cx, id_vehiculo: int) -> None:
        llamar_sp(cx, "sp_eliminar_vehiculo", id_vehiculo)
