"""
main.py — Punto de entrada de CoreWatch Agent.

Uso:
    python main.py

La primera vez, pregunta si esta máquina será el servidor coordinador de
la LAN o un agente que reporta a un servidor ya existente. Las siguientes
veces, usa la configuración guardada en ~/.corewatch/config.json sin
volver a preguntar.
"""

import sys
import threading

from config import obtener_config
from agent_client import correr_bucle_agente


def _correr_modo_servidor(config: dict):
    """
    En modo servidor: arranca el servidor Flask (hilo principal) Y,
    en paralelo, el propio agente de esta máquina reportándose a sí
    misma vía localhost — tal como pediste.
    """
    import server

    hilo_autoreporte = threading.Thread(
        target=correr_bucle_agente,
        args=(config,),
        kwargs={"server_url": f"http://127.0.0.1:{config['puerto']}"},
        daemon=True,
    )
    hilo_autoreporte.start()

    server.iniciar_servidor(config)  # bloquea el hilo principal


def _correr_modo_agente(config: dict):
    correr_bucle_agente(config)


def main():
    config = obtener_config()

    try:
        if config["modo"] == "servidor":
            _correr_modo_servidor(config)
        else:
            _correr_modo_agente(config)
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")
        sys.exit(0)


if __name__ == "__main__":
    main()
