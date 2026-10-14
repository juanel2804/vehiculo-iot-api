# API IoT Vehículo — Práctica 2.5 (entorno Dev local)

API en **Python + FastAPI** con programación orientada a objetos que controla un vehículo IoT usando los
**21 Stored Procedures** del esquema `vehiculo_iot` en **Amazon RDS** (MySQL). Corre solo en
`http://localhost:8000`; el despliegue público (EC2, HTTPS/WSS) es de la práctica 2.6.

## Ejecutar en local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # llena DB_HOST, DB_USER, DB_PASSWORD y API_KEY
uvicorn app.main:app --reload --port 8000
```

* Swagger UI: <http://localhost:8000/docs>
* Página de control: <http://localhost:8000/control/> — botones (y teclas W/S/A/D/J/L/R/F/P) para mover el vehículo,
  estado e historial en vivo, DEMO con barra de progreso y cancelación, y registro de eventos WebSocket.
  Escribe la `X-API-Key` arriba a la derecha (se guarda solo en tu navegador).
* El Security Group de RDS debe permitir MySQL TCP 3306 desde tu IP (My IP).
* Se recomienda un usuario con privilegios mínimos: `sql/01_usuario_api.sql` crea `api_iot` solo con `EXECUTE`.
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

URL: `ws://localhost:8000/ws/vehiculos/{id_vehiculo}` — varios clientes por vehículo; cada uno recibe solo eventos de su vehículo.
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
