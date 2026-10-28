"""Errores de dominio. Los routers no los convierten uno por uno: main.py los traduce a HTTP."""


class ErrorDominio(Exception):
    status_code = 400

    def __init__(self, detalle: str):
        super().__init__(detalle)
        self.detalle = detalle


class NoEncontrado(ErrorDominio):
    status_code = 404


class Conflicto(ErrorDominio):
    status_code = 409


class SolicitudInvalida(ErrorDominio):
    status_code = 400


class ServicioNoDisponible(ErrorDominio):
    status_code = 503


class ErrorExterno(ErrorDominio):
    """Un servicio externo (p. ej. el copiloto con Claude) respondió mal."""
    status_code = 502
