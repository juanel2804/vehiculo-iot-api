"""Copiloto con Claude: convierte una orden en lenguaje natural en una secuencia de movimientos.

No ejecuta nada: devuelve los pasos y la página los manda uno por uno con POST /movimientos,
así cada movimiento pasa por las mismas validaciones, el historial y el WebSocket de siempre.
"""
import json
import logging

import anthropic
from pydantic import BaseModel, Field, ValidationError

from app.exceptions import ErrorExterno, ServicioNoDisponible

log = logging.getLogger("iot.copiloto")

MODELO = "claude-opus-5-5"
MAX_PASOS = 12
DURACION_MIN_MS, DURACION_MAX_MS = 200, 10000

SISTEMA = """Eres el copiloto de una retroexcavadora IoT a escala. El usuario te da órdenes en español \
(a veces informales o con errores de dictado) y tú las conviertes en una secuencia de movimientos.

Reglas:
- Usa solo los comandos del catálogo que se te da. Nunca inventes comandos.
- Cada paso tiene un comando y una duración en milisegundos (200 a 10000). Si el usuario no dice \
cuánto tiempo, usa 1000 ms para tracción y cabina, y 800 ms para la pala.
- Una acción compuesta (por ejemplo "haz una zanja" o "recoge tierra") se descompone en pasos \
sensatos: bajar pala, avanzar, subir pala, etc. Máximo 12 pasos.
- No agregues DETENER entre pasos: la app detiene la máquina al terminar cada uno.
- Si la orden es pararse, responde un solo paso DETENER con duración 200.
- Si la orden no tiene que ver con mover la máquina o es peligrosa/ambigua, responde sin pasos y \
explica en una frase corta qué puede pedir.
- "explicacion" es una frase corta, en español de México, de lo que vas a hacer."""


class Paso(BaseModel):
    comando: str
    duracion_ms: int = Field(ge=DURACION_MIN_MS, le=DURACION_MAX_MS)


class Plan(BaseModel):
    explicacion: str
    pasos: list[Paso] = Field(max_length=MAX_PASOS)


def _esquema(nombres: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "explicacion": {"type": "string"},
            "pasos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "comando": {"type": "string", "enum": nombres},
                        "duracion_ms": {"type": "integer"},
                    },
                    "required": ["comando", "duracion_ms"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["explicacion", "pasos"],
        "additionalProperties": False,
    }


class CopilotoService:
    def __init__(self, api_key: str | None):
        self._cliente = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0, max_retries=1) if api_key else None

    @property
    def disponible(self) -> bool:
        return self._cliente is not None

    async def planear(self, texto: str, catalogo: list[dict]) -> dict:
        if not self._cliente:
            raise ServicioNoDisponible("El copiloto no está configurado (falta ANTHROPIC_API_KEY en el servidor)")

        activos = [c for c in catalogo if c["activo"]]
        nombres = [c["nombre"] for c in activos]
        lista = "\n".join(f"- {c['nombre']}: {c.get('descripcion') or ''}".rstrip(": ") for c in activos)

        try:
            r = await self._cliente.beta.messages.create(
                model=MODELO,
                max_tokens=4000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=SISTEMA,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": _esquema(nombres)}},
                messages=[{"role": "user", "content": f"Catálogo de comandos:\n{lista}\n\nOrden: {texto}"}],
            )
        except anthropic.RateLimitError:
            raise ServicioNoDisponible("El copiloto está saturado; intenta en unos segundos")
        except anthropic.APIStatusError as exc:
            log.error("Claude respondió %s: %s", exc.status_code, exc.message)
            raise ErrorExterno("El copiloto no pudo responder")
        except anthropic.APIConnectionError:
            raise ServicioNoDisponible("No hay conexión con el copiloto")

        if r.stop_reason == "refusal":
            return {"explicacion": "No puedo ayudar con esa orden.", "pasos": []}

        texto_json = next((b.text for b in r.content if b.type == "text"), "")
        try:
            datos = json.loads(texto_json)
            # recorta duraciones fuera de rango antes de validar (el esquema JSON no limita números)
            for p in datos.get("pasos", []):
                p["duracion_ms"] = max(DURACION_MIN_MS, min(DURACION_MAX_MS, int(p.get("duracion_ms", 1000))))
            datos["pasos"] = datos.get("pasos", [])[:MAX_PASOS]
            plan = Plan.model_validate(datos)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            log.exception("Respuesta del copiloto no válida")
            raise ErrorExterno("El copiloto dio una respuesta no válida; repite la orden")

        por_nombre = {c["nombre"]: c for c in activos}
        return {
            "explicacion": plan.explicacion,
            "pasos": [{"comando": p.comando, "id_comando": por_nombre[p.comando]["id_comando"], "duracion_ms": p.duracion_ms}
                      for p in plan.pasos if p.comando in por_nombre],
            "modelo": r.model,
        }
