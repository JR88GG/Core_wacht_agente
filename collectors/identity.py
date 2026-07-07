"""
collectors/identity.py — Datos de identidad del equipo (tabla `equipos`).
"""

import platform
import socket
import uuid as uuid_module


def _obtener_ip_local():
    """IP local usada para salir a la red (no depende de tener internet real)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _obtener_mac():
    try:
        mac = uuid_module.getnode()
        return ":".join(f"{(mac >> ele) & 0xff:02x}" for ele in range(40, -8, -8))
    except Exception:
        return None


def recolectar_identidad(equipo_id: str) -> dict:
    """Devuelve el payload que llena la tabla `equipos`."""
    return {
        "equipo_id": equipo_id,
        "nombre": platform.node(),
        "hostname": platform.node(),
        "sistema_operativo": platform.system(),       # Windows / Linux
        "os_version": platform.version(),
        "os_release": platform.release(),
        "arquitectura": platform.machine(),
        "direccion_ip": _obtener_ip_local(),
        "mac_address": _obtener_mac(),
    }
