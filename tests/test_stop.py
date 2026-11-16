"""El STOP siempre frena: también una DEMO en curso. Sin RDS ni vehículo (servicios simulados).
Uso:  python -m pytest tests/test_stop.py -q
"""
import asyncio
import time
from contextlib import contextmanager

from app.services.ejecutor_demo import EjecutorDemo
from tests.test_sala import LLAVE, api, es, hasta  # noqa: F401  (api es la fixture del WebSocket)


# ---------------------------------------------- WebSocket: DETENER cancela la DEMO ----------------------------------------------
def test_stop_cancela_la_demo_y_pasa(api):
    cliente, s = api
    with cliente.websocket_connect("/ws/vehiculos/1") as admin:
        admin.send_json({"tipo": "auth", "llave": LLAVE})
        assert hasta(admin, es("auth"))["ok"] is True
        admin.send_json({"tipo": "demo", "id": 7})
        fin = time.monotonic() + 3
        while s.ejecutor.demo != 7 and time.monotonic() < fin:
            time.sleep(.02)
        assert s.ejecutor.demo == 7
        # con la DEMO corriendo, un movimiento se rechaza…
        admin.send_json({"tipo": "control", "c": "AVANZAR", "ms": 0})
        assert "DEMO en ejecución" in hasta(admin, es("error"))["detalle"]
        # …pero el STOP pasa y además cancela la DEMO
        admin.send_json({"tipo": "control", "c": "DETENER", "ms": 0})
        assert hasta(admin, es("control", comando="DETENER"))["origen"] == "WEB-RAPIDO"
        assert s.ejecutor.demo is None and s.ejecutor.cancelaciones == 1


def test_stop_sin_turno_no_cancela_la_demo_de_otro(api):
    cliente, s = api
    s.ejecutor.demo = 3
    with cliente.websocket_connect("/ws/vehiculos/1") as extraño:
        extraño.send_json({"tipo": "control", "c": "DETENER", "ms": 0})
        assert hasta(extraño, es("error"))["detalle"] == "Manda primero tu llave (tipo auth)"
    assert s.ejecutor.demo == 3 and s.ejecutor.cancelaciones == 0


# ---------------------------------------------- Ejecutor real: alto inmediato al cancelar ----------------------------------------------
class WsFalso:
    def __init__(self):
        self.eventos = []

    async def emitir(self, id_vehiculo, tipo, **datos):
        self.eventos.append((time.monotonic(), tipo, datos))


class DbFalsa:
    @contextmanager
    def transaccion(self):
        yield None


class EstadoFalso:
    def obtener(self, cx, i):
        return {"conectado": True}

    def actualizar(self, cx, i, id_comando, conectado):
        time.sleep(.3)          # RDS lento: el alto no debe esperar esta escritura


class ComandosFalsos:
    def listar_por_vehiculo(self, cx, i):
        return [{"id_comando": 9, "nombre": "DETENER", "activo": True}]


MOVS = [{"orden": 1, "id_comando": 1, "comando": "AVANZAR", "codigo": 1, "duracion_ms": 8000, "pausa_ms": 0},
        {"orden": 2, "id_comando": 2, "comando": "RETROCEDER", "codigo": 2, "duracion_ms": 8000, "pausa_ms": 0}]


def test_cancelar_manda_detener_de_inmediato():
    async def caso():
        ws = WsFalso()
        ej = EjecutorDemo(DbFalsa(), EstadoFalso(), ComandosFalsos(), ws)
        ej.iniciar(1, 5, MOVS)
        await asyncio.sleep(.1)
        t0 = time.monotonic()
        ej.cancelar(1)
        while ej.en_curso(1):
            await asyncio.sleep(.01)
        tipos = [t for _, t, _ in ws.eventos]
        assert tipos[:2] == ["demo_inicio", "demo_movimiento"]
        alto = next(e for e in ws.eventos if e[1] == "control")
        assert alto[2]["comando"] == "DETENER" and alto[2]["ms"] == 0 and alto[2]["origen"] == "DEMO"
        assert alto[0] - t0 < .2                               # sin esperar el pulso de 8 s ni la escritura en RDS
        assert tipos.index("control") < tipos.index("demo_cancelada")
        assert "RETROCEDER" not in str(ws.eventos)              # el segundo movimiento nunca sale
    asyncio.run(caso())


def test_demo_completa_no_manda_alto_extra():
    async def caso():
        ws = WsFalso()
        ej = EjecutorDemo(DbFalsa(), EstadoFalso(), ComandosFalsos(), ws)
        ej.iniciar(1, 5, [{**MOVS[0], "duracion_ms": 50}])
        while ej.en_curso(1):
            await asyncio.sleep(.01)
        assert [t for _, t, _ in ws.eventos] == ["demo_inicio", "demo_movimiento", "demo_fin"]
    asyncio.run(caso())
