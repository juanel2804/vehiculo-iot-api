"""Contenedor de dependencias: arma repositorios y servicios una sola vez al iniciar la API."""
from fastapi import Request

from app.config import Settings
from app.database import Database
from app.repositories import ComandoRepository, DemoRepository, EstadoRepository, HistorialRepository, VehiculoRepository
from app.services.comandos import ComandoService
from app.services.copiloto import CopilotoService
from app.services.demos import DemoService
from app.services.ejecutor_demo import EjecutorDemo
from app.services.estado import EstadoService
from app.services.movimientos import MovimientoService
from app.services.vehiculos import VehiculoService
from app.websocket import ConnectionManager


class Servicios:
    def __init__(self, settings: Settings):
        self.db = Database(settings)
        self.ws = ConnectionManager()

        vehiculos_repo, comandos_repo = VehiculoRepository(), ComandoRepository()
        estado_repo, historial_repo, demos_repo = EstadoRepository(), HistorialRepository(), DemoRepository()

        self.vehiculos = VehiculoService(self.db, vehiculos_repo, comandos_repo, estado_repo, demos_repo)
        self.comandos = ComandoService(self.db, comandos_repo, self.vehiculos)
        self.estado = EstadoService(self.db, estado_repo, historial_repo, self.vehiculos)
        self.ejecutor = EjecutorDemo(self.db, estado_repo, comandos_repo, self.ws)
        self.movimientos = MovimientoService(self.db, self.vehiculos, self.comandos, estado_repo, historial_repo,
                                             self.ejecutor.en_curso)
        self.demos = DemoService(self.db, demos_repo, self.vehiculos, self.comandos, self.ejecutor.en_curso)
        self.copiloto = CopilotoService(settings.anthropic_api_key)


def get_servicios(request: Request) -> Servicios:
    return request.app.state.servicios
