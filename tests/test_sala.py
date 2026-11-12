"""Pruebas de la sala de turnos. No usan RDS ni el vehículo: la lógica con un reloj falso y el
WebSocket con servicios simulados.   Uso:  python -m pytest tests/test_sala.py -q
"""
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.exceptions import NoEncontrado
from app.routers import ws as ws_router
from app.websocket import ConnectionManager
from app.websocket.sala import GRACIA_ADMIN, GRACIA_FILA, GRACIA_TURNO, GestorSalas, Sala, SalaError, limpiar_nombre

LLAVE = "llave-de-prueba"
F1, F2, F3 = "ficha-ana-0001", "ficha-beto-0002", "ficha-caro-0003"


# ====================================================== lógica pura ======================================================
class Reloj:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def abierta(segundos=60):
    r = Reloj()
    s = Sala(r)
    s.admin_entra()
    return s, r, s.abrir(segundos)


def entra(s, ficha, nombre, codigo):
    j = s.unirse(ficha, nombre, codigo)
    s.conectado(ficha)
    return j


def test_cerrada_por_defecto_y_codigo():
    s = Sala(Reloj())
    with pytest.raises(SalaError):
        s.unirse(F1, "Ana", "AAAA")
    codigo = s.abrir(90)
    assert len(codigo) == 4 and s.segundos == 90 and s.abrir(30) == codigo and s.segundos == 30
    with pytest.raises(SalaError):
        s.unirse(F1, "Ana", "ZZZZ" if codigo != "ZZZZ" else "YYYY")
    with pytest.raises(SalaError):
        s.unirse("corta", "Ana", codigo)
    assert s.unirse(F1, "Ana", codigo.lower()).nombre == "Ana"


def test_un_solo_turno_a_la_vez_y_fila_en_orden():
    s, r, c = abierta(60)
    entra(s, F1, "Ana", c), entra(s, F2, "Beto", c), entra(s, F3, "Caro", c)
    assert s.turno == F1 and s.fila == [F2, F3]
    assert s.puede_controlar(F1) and not s.puede_controlar(F2) and not s.puede_controlar(None)
    assert not s.admin_puede_controlar()
    r.t += 59
    assert s.tick() == (False, False) and s.turno == F1
    r.t += 2
    assert s.tick() == (True, True)          # se acabó: detener y pasa Beto
    assert s.turno == F2 and s.fila == [F3] and F1 not in s.jugadores
    assert s.estado()["turno"]["restan_ms"] == 60000
    entra(s, F1, "Ana", c)                   # Ana se vuelve a formar: va al final
    assert s.fila == [F3, F1]


def test_pausa_congela_el_reloj_y_da_el_control_al_admin():
    s, r, c = abierta(30)
    entra(s, F1, "Ana", c)
    r.t += 10
    assert s.pausar() is True
    assert not s.puede_controlar(F1) and s.admin_puede_controlar()
    r.t += 500
    s.tick()
    assert s.turno == F1 and 19.9 < s.restan < 20.1
    s.reanudar()
    assert s.puede_controlar(F1)
    r.t += 21
    assert s.tick() == (True, True) and s.turno is None


def test_admin_siguiente_sacar_dar_y_mas():
    s, r, c = abierta(60)
    a, b, d = entra(s, F1, "Ana", c), entra(s, F2, "Beto", c), entra(s, F3, "Caro", c)
    assert s.dar(d.id) is True and s.turno == F3 and s.fila == [F2]      # Caro se salta la fila
    s.mas(30)
    assert s.restan == 90 and s.estado()["turno"]["total_ms"] == 90000
    assert s.siguiente() is True and s.turno == F2
    assert s.sacar(b.id) is True and s.turno is None
    with pytest.raises(SalaError):
        s.unirse(F2, "Beto", c)              # expulsado: no vuelve a entrar
    assert s.sacar("no-existe") is False
    assert s.cerrar() is False and not s.abierta and s.codigo == ""


def test_desconexiones():
    s, r, c = abierta(60)
    entra(s, F1, "Ana", c), entra(s, F2, "Beto", c), entra(s, F3, "Caro", c)
    assert s.desconectado(F1) is True        # tenía el turno: hay que detener ya
    r.t += GRACIA_TURNO - 1
    assert s.tick() == (False, False)
    s.conectado(F1)                          # regresó a tiempo: conserva su turno
    assert s.turno == F1
    assert s.desconectado(F2) is False       # Beto se va estando en la fila
    s.desconectado(F1)
    r.t += GRACIA_TURNO + 1
    assert s.tick() == (True, True)
    assert s.turno == F3 and s.fila == [F2]  # a Beto (sin conexión) se le brinca, pero se le guarda el lugar
    r.t += GRACIA_FILA + 1
    s.tick()
    assert s.fila == [] and F2 not in s.jugadores


def test_sin_admin_se_pausa_sola():
    s, r, c = abierta(120)
    entra(s, F1, "Ana", c)
    s.admin_sale()
    r.t += GRACIA_ADMIN - 1
    assert s.tick() == (False, False)
    r.t += 2
    assert s.tick() == (True, True) and s.pausada and s.estado()["admin"] is False


def test_nombres():
    assert limpiar_nombre("  Juan   Pérez\n\t ") == "Juan Pérez"
    assert limpiar_nombre("") == "Jugador" and len(limpiar_nombre("x" * 50)) == 14


# ====================================================== WebSocket ======================================================
class EjecutorFalso:
    def __init__(self):
        self.demo = None
        self.cancelaciones = 0

    def en_curso(self, _):
        return self.demo is not None

    def id_demo_en_curso(self, _):
        return self.demo

    def iniciar(self, _, id_demo, movimientos):
        self.demo = id_demo

    def cancelar(self, _):
        if self.demo is None:
            raise NoEncontrado("No hay DEMO")
        self.demo, self.cancelaciones = None, self.cancelaciones + 1


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(ws_router.router)
    manager, ejecutor = ConnectionManager(), EjecutorFalso()
    comandos = [{"id_comando": i, "nombre": n, "activo": True} for i, n in enumerate(["AVANZAR", "RETROCEDER", "DETENER"], 1)]
    app.state.settings = SimpleNamespace(api_key=LLAVE)
    app.state.servicios = SimpleNamespace(
        ws=manager, ejecutor=ejecutor, salas=GestorSalas(manager, ejecutor),
        estado=SimpleNamespace(obtener_estado=lambda i: {"comando": "DETENER"}),
        comandos=SimpleNamespace(listar=lambda i: comandos),
        movimientos=SimpleNamespace(ejecutar=lambda *a: None),
        demos=SimpleNamespace(preparar_inicio=lambda i, d: [{"orden": 1}]))
    with TestClient(app) as cliente:
        yield cliente, app.state.servicios


def hasta(ws, cond, limite=5.0):
    """Lee mensajes hasta el primero que cumpla `cond`."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        m = ws.receive_json()
        if cond(m):
            return m
    raise AssertionError("No llegó el mensaje esperado")


def es(tipo, **campos):
    return lambda m: m.get("tipo") == tipo and all(m.get(k) == v for k, v in campos.items())


def test_ws_compatibilidad_sin_sala(api):
    cliente, _ = api
    with cliente.websocket_connect("/ws/vehiculos/1") as w:
        inicial = w.receive_json()
        assert inicial["tipo"] == "estado_inicial" and inicial["sala"]["abierta"] is False
        w.send_json({"tipo": "control", "c": "AVANZAR", "ms": 0})
        assert hasta(w, es("error"))["detalle"] == "Manda primero tu llave (tipo auth)"
        w.send_json({"tipo": "sala", "accion": "abrir"})
        assert hasta(w, es("error"))["detalle"] == "Solo el administrador maneja la sala"
        w.send_json({"tipo": "auth", "llave": LLAVE})
        assert hasta(w, es("auth"))["ok"] is True
        w.send_json({"tipo": "control", "c": "AVANZAR", "ms": 300})
        m = hasta(w, es("control"))
        assert m["comando"] == "AVANZAR" and m["ms"] == 300 and m["origen"] == "WEB-RAPIDO"


def test_ws_turnos_de_punta_a_punta(api):
    cliente, s = api
    sala = s.salas.sala(1)
    with cliente.websocket_connect("/ws/vehiculos/1") as admin, \
         cliente.websocket_connect("/ws/vehiculos/1") as ana, \
         cliente.websocket_connect("/ws/vehiculos/1") as beto:
        admin.send_json({"tipo": "auth", "llave": LLAVE})
        admin.send_json({"tipo": "sala", "accion": "abrir", "segundos": 30})
        codigo = hasta(admin, es("sala_admin"))["codigo"]
        assert len(codigo) == 4

        ana.send_json({"tipo": "unirse", "nombre": "Ana", "ficha": F1, "codigo": "MAL0"})
        assert "incorrecto" in hasta(ana, es("sala_error"))["detalle"]
        ana.send_json({"tipo": "unirse", "nombre": "Ana", "ficha": F1, "codigo": codigo})
        id_ana = hasta(ana, es("unido"))["id"]
        beto.send_json({"tipo": "unirse", "nombre": "Beto", "ficha": F2, "codigo": codigo})
        id_beto = hasta(beto, es("unido"))["id"]
        estado = hasta(beto, lambda m: m["tipo"] == "sala" and m["fila"])
        assert estado["turno"]["id"] == id_ana and estado["fila"][0]["id"] == id_beto
        assert "codigo" not in estado and "ficha" not in str(estado)      # nada secreto en el estado público

        # Beto no tiene el turno: se le rechaza. Ana sí mueve. El admin no puede (salvo DETENER).
        beto.send_json({"tipo": "control", "c": "AVANZAR", "ms": 0})
        assert hasta(beto, es("error"))["detalle"] == "No es tu turno"
        ana.send_json({"tipo": "control", "c": "AVANZAR", "ms": 0})
        assert hasta(ana, es("control"))["comando"] == "AVANZAR"
        admin.send_json({"tipo": "control", "c": "RETROCEDER", "ms": 0})
        assert "Ana tiene el turno" in hasta(admin, es("error"))["detalle"]
        admin.send_json({"tipo": "control", "c": "DETENER", "ms": 0})
        assert hasta(admin, es("control", comando="DETENER"))["origen"] == "WEB-RAPIDO"

        # Pausa: el servidor detiene el vehículo, Ana pierde el control y el admin lo toma.
        admin.send_json({"tipo": "sala", "accion": "pausar"})
        assert hasta(ana, es("control", comando="DETENER", origen="TURNOS"))
        assert hasta(ana, es("sala"))["pausada"] is True
        ana.send_json({"tipo": "control", "c": "AVANZAR", "ms": 0})
        assert hasta(ana, es("error"))["detalle"] == "No es tu turno"
        admin.send_json({"tipo": "control", "c": "RETROCEDER", "ms": 0})
        assert hasta(admin, es("control", comando="RETROCEDER"))
        admin.send_json({"tipo": "sala", "accion": "reanudar"})
        hasta(ana, es("sala", pausada=False))

        # DEMO lanzada por Ana: se cancela sola cuando se le acaba el turno, y entra Beto.
        ana.send_json({"tipo": "demo", "id": 7})
        fin = time.monotonic() + 3
        while s.ejecutor.demo != 7 and time.monotonic() < fin:
            time.sleep(.02)
        assert s.ejecutor.demo == 7 and sala.demo_invitado
        sala.restan = 0.2                                   # que el turno de Ana se acabe ya
        m = hasta(beto, lambda m: m["tipo"] == "sala" and m["turno"] and m["turno"]["id"] == id_beto)
        assert m["fila"] == [] and s.ejecutor.cancelaciones == 1
        beto.send_json({"tipo": "control", "c": "AVANZAR", "ms": 0})
        assert hasta(beto, es("control", comando="AVANZAR"))

        # Sacar a Beto: pierde el turno y ya no puede volver a entrar.
        admin.send_json({"tipo": "sala", "accion": "sacar", "id": id_beto})
        hasta(beto, lambda m: m["tipo"] == "sala" and m["turno"] is None)
        beto.send_json({"tipo": "unirse", "nombre": "Beto", "ficha": F2, "codigo": codigo})
        assert "sacó" in hasta(beto, es("sala_error"))["detalle"]

    assert sala.abierta and sala.admins == 0      # el admin se fue: la sala sigue abierta pero se pausará sola


def test_ws_se_desconecta_quien_tiene_el_turno(api):
    cliente, s = api
    with cliente.websocket_connect("/ws/vehiculos/1") as admin:
        admin.send_json({"tipo": "auth", "llave": LLAVE})
        admin.send_json({"tipo": "sala", "accion": "abrir", "segundos": 60})
        codigo = hasta(admin, es("sala_admin"))["codigo"]
        with cliente.websocket_connect("/ws/vehiculos/1") as ana:
            ana.send_json({"tipo": "unirse", "nombre": "Ana", "ficha": F1, "codigo": codigo})
            hasta(ana, es("unido"))
            hasta(admin, lambda m: m["tipo"] == "sala" and m["turno"])
        # Ana cerró: DETENER inmediato y su turno aparece como desconectado
        assert hasta(admin, es("control", comando="DETENER", origen="TURNOS"))
        assert hasta(admin, lambda m: m["tipo"] == "sala" and m["turno"])["turno"]["conectado"] is False
        admin.send_json({"tipo": "sala", "accion": "cerrar"})
        assert hasta(admin, es("sala", abierta=False))["turno"] is None
