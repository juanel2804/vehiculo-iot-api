from app.database import llamar_sp


class DemoRepository:
    """Stored Procedures de DEMO y de sus movimientos."""

    def listar_por_vehiculo(self, cx, id_vehiculo: int) -> list[dict]:
        return llamar_sp(cx, "sp_obtener_demos", id_vehiculo)

    def crear(self, cx, id_vehiculo, nombre, descripcion) -> int:
        return llamar_sp(cx, "sp_crear_demo", id_vehiculo, nombre, descripcion)[0]["id_demo"]

    def actualizar(self, cx, id_demo, nombre, descripcion, activo) -> None:
        llamar_sp(cx, "sp_actualizar_demo", id_demo, nombre, descripcion, activo)

    def eliminar(self, cx, id_demo: int) -> None:
        llamar_sp(cx, "sp_eliminar_demo", id_demo)

    def listar_movimientos(self, cx, id_demo: int) -> list[dict]:
        return llamar_sp(cx, "sp_obtener_movimientos_demo", id_demo)

    def agregar_movimiento(self, cx, id_demo, id_comando, orden, duracion_ms, pausa_ms) -> None:
        llamar_sp(cx, "sp_agregar_movimiento_demo", id_demo, id_comando, orden, duracion_ms, pausa_ms)

    def actualizar_movimiento(self, cx, id_mov, id_comando, orden, duracion_ms, pausa_ms) -> None:
        llamar_sp(cx, "sp_actualizar_movimiento_demo", id_mov, id_comando, orden, duracion_ms, pausa_ms)

    def eliminar_movimiento(self, cx, id_mov: int) -> None:
        llamar_sp(cx, "sp_eliminar_movimiento_demo", id_mov)
