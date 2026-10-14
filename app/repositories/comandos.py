from app.database import llamar_sp


class ComandoRepository:
    """Stored Procedures del catálogo de comandos de cada vehículo."""

    def listar_por_vehiculo(self, cx, id_vehiculo: int) -> list[dict]:
        return llamar_sp(cx, "sp_obtener_comandos_vehiculo", id_vehiculo)

    def crear(self, cx, id_vehiculo, nombre, codigo, descripcion) -> int:
        return llamar_sp(cx, "sp_crear_comando", id_vehiculo, nombre, codigo, descripcion)[0]["id_comando"]

    def actualizar(self, cx, id_comando, nombre, codigo, descripcion, activo) -> None:
        llamar_sp(cx, "sp_actualizar_comando", id_comando, nombre, codigo, descripcion, activo)

    def eliminar(self, cx, id_comando: int) -> None:
        llamar_sp(cx, "sp_eliminar_comando", id_comando)
