"""Acceso a Amazon RDS: pool pequeño de conexiones y ejecución de Stored Procedures.

Todo el SQL de la aplicación son llamadas CALL con parámetros enlazados; nunca se
concatenan valores externos.
"""
import queue
from contextlib import contextmanager
from typing import Any, Iterator

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from app.config import Settings
from app.exceptions import ServicioNoDisponible


class Database:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._pool: queue.Queue[Connection] = queue.Queue(maxsize=settings.db_pool_size)

    def _nueva_conexion(self) -> Connection:
        s = self._settings
        return pymysql.connect(
            host=s.db_host,
            port=s.db_port,
            user=s.db_user,
            password=s.db_password,
            database=s.db_name,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=s.db_connect_timeout,
        )

    def _tomar(self) -> Connection:
        try:
            cx = self._pool.get_nowait()
            cx.ping(reconnect=True)
            return cx
        except queue.Empty:
            return self._nueva_conexion()
        except pymysql.err.Error:
            return self._nueva_conexion()

    def _devolver(self, cx: Connection) -> None:
        try:
            self._pool.put_nowait(cx)
        except queue.Full:
            cx.close()

    @contextmanager
    def transaccion(self) -> Iterator[Connection]:
        """Entrega una conexión; hace commit al salir bien y rollback si hay excepción."""
        try:
            cx = self._tomar()
        except pymysql.err.OperationalError as exc:
            raise ServicioNoDisponible("No se pudo conectar con la base de datos en RDS") from exc
        try:
            yield cx
            cx.commit()
        except BaseException:
            try:
                cx.rollback()
            except pymysql.err.Error:
                pass
            raise
        finally:
            self._devolver(cx)

    def cerrar(self) -> None:
        while True:
            try:
                self._pool.get_nowait().close()
            except queue.Empty:
                break
            except pymysql.err.Error:
                pass


def llamar_sp(cx: Connection, nombre: str, *args: Any) -> list[dict]:
    """Ejecuta un Stored Procedure y devuelve las filas de su primer result set."""
    with cx.cursor() as cur:
        cur.callproc(nombre, args)
        filas = list(cur.fetchall())
        while cur.nextset():  # vaciar los result sets restantes (incluido el OK final)
            pass
    return filas
