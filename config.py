"""
config.py — Manejo de configuración persistente del agente/servidor CoreWatch.

La configuración se guarda en un archivo JSON dentro del home del usuario,
en una ruta que funciona igual en Windows y Linux:
    ~/.corewatch/config.json

Esto evita que el asistente de primer arranque se repita en cada ejecución.
"""

import json
import os
import platform
import uuid
from pathlib import Path

CONFIG_DIR = Path.home() / ".corewatch"
CONFIG_FILE = CONFIG_DIR / "config.json"


def config_existente():
    """True si ya se configuró este equipo anteriormente."""
    return CONFIG_FILE.exists()


def cargar_config():
    """Carga la configuración guardada. Lanza si no existe (usar config_existente antes)."""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_config(data: dict):
    """Guarda/actualiza la configuración en disco."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def obtener_o_crear_equipo_id(config: dict) -> str:
    """
    El equipo_id debe ser estable entre reinicios (es la PK en la tabla equipos).
    Se genera una sola vez y se persiste en el config local de esta máquina.
    """
    if "equipo_id" not in config:
        config["equipo_id"] = str(uuid.uuid4())
        guardar_config(config)
    return config["equipo_id"]


def _preguntar(pregunta: str, opciones: dict) -> str:
    """
    Helper de CLI: muestra un menú numerado y devuelve la clave elegida.
    opciones = {"1": "servidor", "2": "agente"}
    """
    print(f"\n{pregunta}")
    for clave, etiqueta in opciones.items():
        print(f"  [{clave}] {etiqueta}")
    while True:
        respuesta = input("Selecciona una opción: ").strip()
        if respuesta in opciones:
            return opciones[respuesta]
        print("Opción inválida, intenta de nuevo.")


def asistente_primer_arranque() -> dict:
    """
    Se ejecuta SOLO la primera vez (cuando no existe config.json).
    Pregunta si esta máquina será el servidor coordinador de la LAN,
    o solo un agente que reporta datos a un servidor ya existente.
    """
    print("=" * 60)
    print(" CoreWatch Agent — Configuración inicial")
    print("=" * 60)

    modo = _preguntar(
        "¿Qué rol cumplirá esta computadora?",
        {
            "1": "servidor",
            "2": "agente",
        },
    )

    config = {
        "modo": modo,
        "hostname": platform.node(),
    }

    if modo == "servidor":
        print("\n--- Configuración del servidor (coordinador de la LAN) ---")
        config["db_url"] = input(
            "URL de conexión a PostgreSQL (DATABASE_URL de Railway): "
        ).strip()
        config["cliente_id"] = int(input(
            "ID de cliente (cliente_id) al que pertenece esta red: "
        ).strip())
        config["api_key"] = input(
            "API key compartida (la misma que usarán todos los agentes de este cliente): "
        ).strip()
        puerto = input("Puerto en el que escuchará el servidor [5000]: ").strip()
        config["puerto"] = int(puerto) if puerto else 5000
        config["intervalo_segundos"] = int(
            input("Intervalo de recolección de datos en segundos [60]: ").strip() or "60"
        )
        config["intervalo_escaneo_red_segundos"] = int(
            input("Intervalo de escaneo de red en segundos [300]: ").strip() or "300"
        )

    else:  # agente
        print("\n--- Configuración del agente ---")
        config["server_url"] = input(
            "URL del servidor CoreWatch en esta red (ej: http://192.168.1.10:5000): "
        ).strip().rstrip("/")
        config["api_key"] = input("API key proporcionada por el servidor: ").strip()
        config["intervalo_segundos"] = int(
            input("Intervalo de recolección de datos en segundos [60]: ").strip() or "60"
        )

    obtener_o_crear_equipo_id(config)
    guardar_config(config)

    print("\nConfiguración guardada en:", CONFIG_FILE)
    print("=" * 60)
    return config


def obtener_config() -> dict:
    """Punto de entrada: carga config existente o corre el asistente si es la primera vez."""
    if config_existente():
        config = cargar_config()
        obtener_o_crear_equipo_id(config)
        return config
    return asistente_primer_arranque()
