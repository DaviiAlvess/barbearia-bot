"""Barbearia Bot: atendimento humanizado com IA para barbearias."""
import logging
import os

__version__ = "2.0.0"


def configurar_log(nivel: str | None = None) -> None:
    logging.basicConfig(
        level=(nivel or os.getenv("LOG_LEVEL", "INFO")).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%d/%m %H:%M:%S",
    )
