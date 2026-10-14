"""Prueba integral contra la API corriendo en localhost:8000 (usa RDS real).

Crea un vehículo TEMPORAL, recorre los 21 Stored Procedures a través de la API, valida las reglas
de negocio (transacción, rechazo de comandos ajenos, historial máx. 10, DEMO sin historial,
cancelación, dos clientes WebSocket) y al final elimina el vehículo temporal.

Uso:  python -m tests.prueba_integral        (con la API ya levantada)
"""
import asyncio
import json
import os
import sys

import httpx
import websockets

from app.config import get_settings

BASE = os.getenv("API_URL", "http://localhost:8000")
WS = BASE.replace("http", "ws", 1)
LLAVE = {"X-API-Key": get_settings().api_key}
resultados: list[tuple[str, bool]] = []


def check(nombre: str, condicion: bool, extra="") -> None:
    resultados.append((nombre, condicion))
    print(("OK   " if condicion else "FALLA"), nombre, extra)


async def recibir_hasta(ws, tipo_final: set[str], limite=30.0) -> list[dict]:
    eventos = []
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=limite))
        eventos.append(msg)
        if msg["tipo"] in tipo_final:
            return eventos


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        # ---------- Vehículos ----------
        r = await c.post("/vehiculos", json={"nombre": "Vehiculo PRUEBA", "modelo": "Test", "microcontrolador": "ESP32"})
        check("sp_crear_vehiculo → 201", r.status_code == 201)
        v = r.json()["id"]
        r = await c.get("/vehiculos")
        check("sp_obtener_vehiculos", any(x["id_vehiculo"] == v for x in r.json()))
        r = await c.post(f"/vehiculos/{v}/actualizar", json={"nombre": "Vehiculo PRUEBA 2", "microcontrolador": "ESP8266", "activo": True})
        check("sp_actualizar_vehiculo", r.status_code == 200)
        r = await c.get("/vehiculos/999999")
        check("vehículo inexistente → 404", r.status_code == 404)

        # ---------- Comandos ----------
        ids = {}
        for nombre, codigo in [("AVANZAR", 1), ("RETROCEDER", 2), ("DETENER", 9), ("APAGADO", 50)]:
            r = await c.post(f"/vehiculos/{v}/comandos", json={"nombre": nombre, "codigo": codigo})
            ids[nombre] = r.json()["id"]
        check("sp_crear_comando → 201", r.status_code == 201)
        r = await c.post(f"/vehiculos/{v}/comandos", json={"nombre": "AVANZAR", "codigo": 77})
        check("comando con nombre repetido → 409", r.status_code == 409)
        r = await c.post(f"/vehiculos/{v}/comandos/{ids['APAGADO']}/actualizar", json={"nombre": "APAGADO", "codigo": 50, "activo": False})
        check("sp_actualizar_comando (desactivar)", r.status_code == 200)
        r = await c.get(f"/vehiculos/{v}/comandos")
        check("sp_obtener_comandos_vehiculo", len(r.json()) == 4)

        # ---------- Estado inicial y detalle ----------
        r = await c.get(f"/vehiculos/{v}/estado")
        check("sp_obtener_estado sin estado → 200 null", r.status_code == 200 and r.json() is None)

        # ---------- Movimiento individual ----------
        r = await c.post("/movimientos", json={"id_vehiculo": v, "id_comando": ids["AVANZAR"]})
        check("movimiento sin llave → 401", r.status_code == 401)
        r = await c.post("/movimientos", headers=LLAVE, json={"id_vehiculo": v, "id_comando": 1})
        check("comando de OTRO vehículo → 404", r.status_code == 404, r.json())
        r = await c.post("/movimientos", headers=LLAVE, json={"id_vehiculo": v, "id_comando": ids["APAGADO"]})
        check("comando inactivo → 409", r.status_code == 409)
        h = await c.get(f"/vehiculos/{v}/historial")
        check("rechazos no tocan historial", h.json() == [])

        async with websockets.connect(f"{WS}/ws/vehiculos/{v}") as ws1, websockets.connect(f"{WS}/ws/vehiculos/{v}") as ws2, \
                websockets.connect(f"{WS}/ws/vehiculos/1") as ws_otro:
            ini = [json.loads(await ws.recv()) for ws in (ws1, ws2, ws_otro)]
            check("WebSocket envía estado_inicial", all(m["tipo"] == "estado_inicial" for m in ini))
            r = await c.post("/movimientos", headers=LLAVE, json={"id_vehiculo": v, "codigo": 1, "origen": "PRUEBA"})
            check("sp_actualizar_estado + sp_registrar_historial → 201", r.status_code == 201, r.json())
            check("conectado no se asume verdadero", r.json()["conectado"] is False)
            m1, m2 = json.loads(await ws1.recv()), json.loads(await ws2.recv())
            check("2 clientes reciben el evento movimiento", m1["tipo"] == m2["tipo"] == "movimiento" and m1["codigo"] == 1)
            try:
                await asyncio.wait_for(ws_otro.recv(), timeout=1.5)
                check("cliente de otro vehículo NO recibe el evento", False)
            except asyncio.TimeoutError:
                check("cliente de otro vehículo NO recibe el evento", True)

        r = await c.get(f"/vehiculos/{v}/estado")
        check("estado refleja AVANZAR", r.json()["comando"] == "AVANZAR")
        r = await c.post(f"/vehiculos/{v}/conexion", headers=LLAVE, json={"conectado": True})
        check("conexion conserva comando", r.status_code == 200 and r.json()["conectado"] and r.json()["comando"] == "AVANZAR",
              f"{r.status_code} {r.text[:200]}")

        # 12 movimientos más → historial debe devolver 10
        for i in range(12):
            await c.post("/movimientos", headers=LLAVE, json={"id_vehiculo": v, "codigo": 2 if i % 2 else 1})
        h = (await c.get(f"/vehiculos/{v}/historial")).json()
        ids_h = [x["id_historial"] for x in h]
        check("sp_obtener_historial máx. 10 (hay 13)", len(h) == 10)
        check("historial del más reciente al más antiguo", ids_h == sorted(ids_h, reverse=True))

        # ---------- DEMO ----------
        r = await c.post(f"/vehiculos/{v}/demos", json={"nombre": "Demo prueba"})
        check("sp_crear_demo → 201", r.status_code == 201)
        d = r.json()["id"]
        for orden, (cmd, dur, pau) in enumerate([("AVANZAR", 300, 100), ("RETROCEDER", 200, 100), ("AVANZAR", 200, 0), ("DETENER", 100, 0)], 1):
            r = await c.post(f"/vehiculos/{v}/demos/{d}/movimientos", json={"id_comando": ids[cmd], "orden": orden, "duracion_ms": dur, "pausa_ms": pau})
        check("sp_agregar_movimiento_demo → 201", r.status_code == 201)
        r = await c.post(f"/vehiculos/{v}/demos/{d}/movimientos", json={"id_comando": 1, "orden": 9, "duracion_ms": 100})
        check("movimiento DEMO con comando ajeno → 404", r.status_code == 404)
        movs = (await c.get(f"/vehiculos/{v}/demos/{d}/movimientos")).json()
        check("sp_obtener_movimientos_demo ordenados", [m["orden"] for m in movs] == [1, 2, 3, 4])
        r = await c.post(f"/vehiculos/{v}/demos/{d}/movimientos/{movs[2]['id_demo_movimiento']}/actualizar",
                         json={"id_comando": ids["AVANZAR"], "orden": 3, "duracion_ms": 250, "pausa_ms": 50})
        check("sp_actualizar_movimiento_demo", r.status_code == 200)
        r = await c.post(f"/vehiculos/{v}/demos/{d}/actualizar", json={"nombre": "Demo prueba (editada)", "activo": True})
        check("sp_actualizar_demo", r.status_code == 200)
        r = await c.get(f"/vehiculos/{v}/demos")
        check("sp_obtener_demos", r.json()[0]["nombre"] == "Demo prueba (editada)")

        antes = (await c.get(f"/vehiculos/{v}/historial")).json()
        async with websockets.connect(f"{WS}/ws/vehiculos/{v}") as ws:
            await ws.recv()
            r = await c.post(f"/vehiculos/{v}/demos/{d}/iniciar", headers=LLAVE)
            check("iniciar DEMO → 202", r.status_code == 202, r.json())
            r2 = await c.post(f"/vehiculos/{v}/demos/{d}/iniciar", headers=LLAVE)
            check("segunda DEMO simultánea → 409", r2.status_code == 409)
            r3 = await c.post("/movimientos", headers=LLAVE, json={"id_vehiculo": v, "codigo": 1})
            check("movimiento durante DEMO → 409", r3.status_code == 409)
            eventos = await recibir_hasta(ws, {"demo_fin", "demo_cancelada", "demo_error"})
        tipos = [e["tipo"] for e in eventos]
        check("eventos inicio + 4 movimientos + fin", tipos == ["demo_inicio"] + ["demo_movimiento"] * 4 + ["demo_fin"], tipos)
        check("movimientos con duracion_ms y pausa_ms", all("duracion_ms" in e and "pausa_ms" in e for e in eventos if e["tipo"] == "demo_movimiento"))
        despues = (await c.get(f"/vehiculos/{v}/historial")).json()
        ids_de = lambda h: [x["id_historial"] for x in h] if isinstance(h, list) else h
        check("DEMO NO agrega historial", antes == despues, f"antes={ids_de(antes)} después={ids_de(despues)}")
        r = await c.get(f"/vehiculos/{v}/estado")
        check("DEMO actualizó estado (último = DETENER)", r.json()["comando"] == "DETENER")

        # cancelación
        async with websockets.connect(f"{WS}/ws/vehiculos/{v}") as ws:
            await ws.recv()
            await c.post(f"/vehiculos/{v}/demos/{d}/iniciar", headers=LLAVE)
            await asyncio.sleep(0.2)
            r = await c.post(f"/vehiculos/{v}/demos/cancelar", headers=LLAVE)
            check("cancelar DEMO → 202", r.status_code == 202)
            eventos = await recibir_hasta(ws, {"demo_fin", "demo_cancelada", "demo_error"})
        check("evento demo_cancelada antes de terminar", eventos[-1]["tipo"] == "demo_cancelada" and len(eventos) < 6, [e["tipo"] for e in eventos])
        r = await c.post(f"/vehiculos/{v}/demos/cancelar", headers=LLAVE)
        check("cancelar sin DEMO activa → 404", r.status_code == 404)

        # ---------- Eliminaciones ----------
        r = await c.post(f"/vehiculos/{v}/demos/{d}/movimientos/{movs[3]['id_demo_movimiento']}/eliminar", headers=LLAVE)
        check("sp_eliminar_movimiento_demo", r.status_code == 200)
        r = await c.post(f"/vehiculos/{v}/comandos/{ids['AVANZAR']}/eliminar", headers=LLAVE)
        check("eliminar comando usado por DEMO → 409", r.status_code == 409)
        r = await c.post(f"/vehiculos/{v}/demos/{d}/eliminar", headers=LLAVE)
        check("sp_eliminar_demo", r.status_code == 200)
        r = await c.post(f"/vehiculos/{v}/comandos/{ids['APAGADO']}/eliminar", headers=LLAVE)
        check("sp_eliminar_comando", r.status_code == 200)
        # una DEMO con movimientos debe poder borrarse junto con el vehículo
        d2 = (await c.post(f"/vehiculos/{v}/demos", json={"nombre": "Demo que se queda"})).json()["id"]
        await c.post(f"/vehiculos/{v}/demos/{d2}/movimientos", json={"id_comando": ids["AVANZAR"], "orden": 1, "duracion_ms": 100})
        r = await c.post(f"/vehiculos/{v}/eliminar", headers={"X-API-Key": "mala"})
        check("eliminar con llave inválida → 403", r.status_code == 403)
        r = await c.post(f"/vehiculos/{v}/eliminar", headers=LLAVE)
        check("sp_eliminar_vehiculo con DEMO y movimientos", r.status_code == 200, r.json())
        r = await c.get(f"/vehiculos/{v}")
        check("vehículo temporal ya no existe", r.status_code == 404)

    fallas = [n for n, ok in resultados if not ok]
    print(f"\n{len(resultados) - len(fallas)}/{len(resultados)} verificaciones OK")
    if fallas:
        raise SystemExit("Fallaron: " + "; ".join(fallas))


async def limpiar() -> None:
    """Si la prueba se interrumpe, borra los vehículos temporales que hayan quedado."""
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        for v in (await c.get("/vehiculos")).json():
            if v["nombre"].startswith("Vehiculo PRUEBA"):
                await c.post(f"/vehiculos/{v['id_vehiculo']}/eliminar", headers=LLAVE)
                print("limpieza: vehículo temporal", v["id_vehiculo"], "eliminado")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        asyncio.run(main())
    finally:
        asyncio.run(limpiar())
