# API IoT Vehículo — Práctica 2.6 (Amazon EC2 + RDS, HTTPS/WSS)

API en **Python + FastAPI** con programación orientada a objetos que controla un vehículo IoT usando los
**21 Stored Procedures** del esquema `vehiculo_iot` en **Amazon RDS** (MySQL). Es la misma solución de la
práctica 2.5 (etiqueta `v2.5-entregada`), ahora **publicada en Amazon EC2** con HTTPS y WebSocket seguro (WSS).

## Servicio público

| Recurso | URL |
|---|---|
| API (HTTPS) | <https://100-63-187-92.sslip.io> |
| Swagger UI | <https://100-63-187-92.sslip.io/docs> |
| Página de control | <https://100-63-187-92.sslip.io/control/> |
| App del examen 2.6 (criterios con pruebas en vivo y evidencias) | <https://100-63-187-92.sslip.io/examen/> |
| WebSocket (WSS) del vehículo 1 | `wss://100-63-187-92.sslip.io/ws/vehiculos/1` |
| Página en GitHub Pages | <https://juanel2804.github.io/vehiculo-iot-api/> (apunta a la API pública) |

## Arquitectura de despliegue

```
Cliente (Thunder Client / Swagger / navegador / futuro ESP32)
        │  HTTPS 443  /  WSS 443
        ▼
Amazon EC2 (Windows Server 2025, IP elástica)
   Caddy  ── certificado Let's Encrypt automático ──►  uvicorn 127.0.0.1:8000  (FastAPI, POO)
        │  MySQL 3306 (solo desde el Security Group de la EC2)
        ▼
Amazon RDS for MySQL  ·  vehiculo_iot  ·  6 tablas + 21 Stored Procedures
```

* **Persistencia:** `deploy/instalar_servicios.ps1` registra dos tareas de inicio de Windows (`IoT-API` y `IoT-Caddy`,
  cuenta SYSTEM, reinicio automático). La API sigue operando con VS Code o la sesión de administración cerrados.
* **HTTPS/WSS:** Caddy (`deploy/Caddyfile.example`) termina TLS y reenvía HTTP y WebSocket a uvicorn, que solo
  escucha en `127.0.0.1`. Puertos públicos: 22 (administración), 80 (validación del certificado) y 443.
* **RDS no queda abierto:** el Security Group de RDS permite MySQL 3306 **solo desde el Security Group de la EC2**,
  y la API se conecta con el usuario `api_iot` (solo `EXECUTE` sobre `vehiculo_iot`, ver `sql/01_usuario_api.sql`).
* **Secretos:** `.env` (credenciales de RDS y `API_KEY`) existe solo en el servidor y está en `.gitignore`.

### Desplegar o actualizar desde GitHub (en la EC2)

```powershell
git clone https://github.com/juanel2804/vehiculo-iot-api.git C:\iot\vehiculo-iot-api
cd C:\iot\vehiculo-iot-api
python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env            # llenar DB_HOST, DB_USER, DB_PASSWORD, API_KEY, CORS_ORIGINS
.\deploy\instalar_servicios.ps1   # una sola vez (Caddy en C:\caddy según deploy\Caddyfile.example)
.\deploy\actualizar.ps1           # en cada actualización: git pull + reinicio de la API
```

## Ejecutar en local (desarrollo)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # llena DB_HOST, DB_USER, DB_PASSWORD y API_KEY
uvicorn app.main:app --reload --port 8000
```

* Swagger UI local: <http://localhost:8000/docs> · Página de control: <http://localhost:8000/control/>
  (botones y teclas W/S/A/D/J/L/R/F/P, estado e historial en vivo, DEMO con barra de progreso y cancelación,
  registro de eventos WebSocket). Escribe la `X-API-Key` arriba a la derecha (se guarda solo en tu navegador).
* `CORS_ORIGINS` lista los sitios web que pueden llamar a la API desde un navegador (por defecto GitHub Pages).
* En local, el Security Group de RDS debe permitir MySQL 3306 desde tu IP.
* `.env` está en `.gitignore`: nunca se sube. `.env.example` no lleva secretos.

## Arquitectura (POO, una responsabilidad por clase)

| Capa | Archivos | Responsabilidad |
|---|---|---|
| Configuración | `app/config.py` | `Settings` lee variables de entorno / `.env` |
| Acceso a RDS | `app/database.py` | `Database` (pool y transacciones), `llamar_sp` (CALL con parámetros enlazados) |
| Repositorios | `app/repositories/*.py` | Una clase por área; **solo** llaman Stored Procedures |
| Servicios | `app/services/*.py` | Reglas de negocio y validaciones (`VehiculoService`, `ComandoService`, `EstadoService`, `MovimientoService`, `DemoService`) |
| Ejecución de DEMO | `app/services/ejecutor_demo.py` | `EjecutorDemo`: corre la DEMO en segundo plano, controla cancelación y concurrencia |
| WebSocket | `app/websocket/manager.py` | `ConnectionManager`: clientes por vehículo y emisión de eventos |
| API | `app/routers/*.py`, `app/main.py` | Endpoints delgados, modelos (`app/schemas.py`), seguridad (`app/security.py`), errores |

## Reglas de negocio

* **Movimiento individual** (`POST /movimientos`): valida vehículo activo y comando activo del mismo vehículo →
  `sp_actualizar_estado` + `sp_registrar_historial` en **una transacción** → commit → evento WebSocket.
  Si se rechaza, no cambia nada ni se emite evento. `conectado` se conserva (no se asume por recibir un POST).
* **DEMO** (`POST /vehiculos/{id}/demos/{id_demo}/iniciar`): lee los N movimientos con `sp_obtener_movimientos_demo`,
  los emite por WebSocket respetando `duracion_ms` y `pausa_ms`, actualiza el estado con `sp_actualizar_estado`
  y **nunca** llama a `sp_registrar_historial`. Solo una DEMO por vehículo a la vez; se puede cancelar.
* **Historial** (`GET /vehiculos/{id}/historial`): máximo los **10** movimientos individuales más recientes.
* Operaciones de escritura = `POST` (también actualizar y eliminar); consultas = `GET` (nunca modifican datos).

## Seguridad

Eliminaciones, `POST /movimientos`, `.../conexion` y el control de DEMO (`iniciar`, `cancelar`) exigen el header
`X-API-Key` (valor de `API_KEY` en `.env`). Sin header → 401; llave incorrecta → 403.

## WebSocket (no aparece en Swagger)

URL pública: `wss://100-63-187-92.sslip.io/ws/vehiculos/{id_vehiculo}` (en local: `ws://localhost:8000/ws/vehiculos/{id_vehiculo}`) — varios clientes por vehículo; cada uno recibe solo eventos de su vehículo.
Al conectarse (o reconectarse) el cliente recibe de inmediato el último estado guardado en RDS (`estado_inicial`).
Se puede enviar el texto `ping` y responde `pong`. Si el vehículo no existe, envía un evento `error` y cierra con código 4404.

Todos los mensajes llevan `tipo`, `id_vehiculo` y `timestamp` (UTC, ISO 8601).

| `tipo` | Cuándo | Campos extra |
|---|---|---|
| `estado_inicial` | Al conectarse | `estado` (último estado o `null`), `demo_en_ejecucion` |
| `movimiento` | Tras registrar un movimiento individual | `comando`, `codigo`, `id_comando`, `origen` |
| `conexion` | Al cambiar `conectado` | `conectado` |
| `demo_inicio` | Arranca una DEMO | `id_demo`, `total_movimientos` |
| `demo_movimiento` | Cada movimiento de la DEMO, en orden | `id_demo`, `orden`, `total_movimientos`, `comando`, `codigo`, `duracion_ms`, `pausa_ms` |
| `demo_fin` | La DEMO terminó | `id_demo`, `total_movimientos` |
| `demo_cancelada` | Se canceló la DEMO | `id_demo`, `estado_detenido` |
| `demo_error` | Falló RDS u otro error | `id_demo`, `detalle` |
| `error` | No se pudo abrir el monitoreo | `detalle` |

Ejemplo:

```json
{"tipo": "demo_movimiento", "id_vehiculo": 1, "id_demo": 1, "orden": 2, "total_movimientos": 5,
 "id_comando": 3, "comando": "Retroceder", "codigo": 2, "duracion_ms": 1500, "pausa_ms": 500,
 "timestamp": "2026-10-14T18:00:00+00:00"}
```

## Los 21 Stored Procedures y dónde se usan

| SP | Endpoint |
|---|---|
| `sp_crear_vehiculo` | `POST /vehiculos` |
| `sp_obtener_vehiculos` | `GET /vehiculos` |
| `sp_obtener_vehiculo` | `GET /vehiculos/{id}` (y validación en casi todo) |
| `sp_actualizar_vehiculo` | `POST /vehiculos/{id}/actualizar` |
| `sp_eliminar_vehiculo` | `POST /vehiculos/{id}/eliminar` |
| `sp_crear_comando` | `POST /vehiculos/{id}/comandos` |
| `sp_obtener_comandos_vehiculo` | `GET /vehiculos/{id}/comandos` |
| `sp_actualizar_comando` | `POST /vehiculos/{id}/comandos/{id_comando}/actualizar` |
| `sp_eliminar_comando` | `POST /vehiculos/{id}/comandos/{id_comando}/eliminar` |
| `sp_actualizar_estado` | `POST /movimientos`, `POST /vehiculos/{id}/conexion`, ejecución de DEMO |
| `sp_obtener_estado` | `GET /vehiculos/{id}/estado` |
| `sp_registrar_historial` | `POST /movimientos` |
| `sp_obtener_historial` | `GET /vehiculos/{id}/historial` |
| `sp_crear_demo` | `POST /vehiculos/{id}/demos` |
| `sp_obtener_demos` | `GET /vehiculos/{id}/demos` |
| `sp_actualizar_demo` | `POST /vehiculos/{id}/demos/{id_demo}/actualizar` |
| `sp_eliminar_demo` | `POST /vehiculos/{id}/demos/{id_demo}/eliminar` |
| `sp_agregar_movimiento_demo` | `POST /vehiculos/{id}/demos/{id_demo}/movimientos` |
| `sp_obtener_movimientos_demo` | `GET .../demos/{id_demo}/movimientos` y `POST .../iniciar` |
| `sp_actualizar_movimiento_demo` | `POST .../movimientos/{id_mov}/actualizar` |
| `sp_eliminar_movimiento_demo` | `POST .../movimientos/{id_mov}/eliminar` |
