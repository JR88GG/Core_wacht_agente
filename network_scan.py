"""
network_scan.py — Escaneo TCP centralizado de los equipos de la LAN.

Corre en el servidor coordinador (no en la nube), porque es la única
máquina con ruta de red real hacia las IPs privadas de los demás equipos.
Usa exclusivamente el módulo estándar `socket` — sin invocar el shell del
sistema operativo, igual que el diseño original en Node.js.
"""

import logging
import socket
import time
from datetime import datetime, timezone

log = logging.getLogger("corewatch.network_scan")

PUERTOS_A_VERIFICAR = [
    ("ssh", 22), ("dns", 53), ("http", 80), ("rpc", 135), ("netbios", 139),
    ("https", 443), ("smb", 445), ("mysql", 3306), ("rdp", 3389),
    ("vnc", 5900), ("winrm", 5985), ("http-alt", 8080), ("https-alt", 8443),
]


def probar_puerto_tcp(host: str, puerto: int, timeout_s: float = 1.2) -> dict:
    """Intenta conectar a un puerto TCP. Nunca lanza excepción: siempre devuelve un resultado."""
    inicio = time.time()
    try:
        with socket.create_connection((host, puerto), timeout=timeout_s):
            return {
                "puerto": puerto, "abierto": True, "estado": "abierto",
                "latencia_ms": round((time.time() - inicio) * 1000, 1),
            }
    except socket.timeout:
        return {"puerto": puerto, "abierto": False, "estado": "timeout", "latencia_ms": None}
    except OSError:
        return {"puerto": puerto, "abierto": False, "estado": "cerrado", "latencia_ms": None}


def escanear_host(ip: str, hostname: str = None, timeout_s: float = 1.2) -> dict:
    """Escanea los puertos de PUERTOS_A_VERIFICAR contra un solo host, EN PARALELO."""
    from concurrent.futures import ThreadPoolExecutor

    def _probar(item):
        nombre, puerto = item
        resultado = probar_puerto_tcp(ip, puerto, timeout_s)
        resultado["nombre"] = nombre
        return resultado

    with ThreadPoolExecutor(max_workers=len(PUERTOS_A_VERIFICAR)) as executor:
        resultados = list(executor.map(_probar, PUERTOS_A_VERIFICAR))

    puertos_abiertos = [r for r in resultados if r["abierto"]]
    latencias = [r["latencia_ms"] for r in puertos_abiertos if r["latencia_ms"] is not None]

    return {
        "ip": ip,
        "hostname": hostname,
        "online": len(puertos_abiertos) > 0,
        "latency_ms": round(sum(latencias) / len(latencias), 1) if latencias else None,
        "puertos_abiertos": puertos_abiertos,
        "resultados": resultados,
    }


def escanear_equipos(equipos: list, timeout_s: float = 1.2) -> dict:
    """
    equipos: lista de dicts con al menos {"equipo_id", "direccion_ip", "hostname"}.
    Devuelve el resumen + detalle listo para insertar en network_scans/network_scan_hosts.
    Escanea los equipos EN PARALELO entre sí (cada uno ya escanea sus puertos en paralelo).
    """
    from concurrent.futures import ThreadPoolExecutor

    objetivos = [e for e in equipos if e.get("direccion_ip")]

    def _escanear(equipo):
        resultado = escanear_host(equipo["direccion_ip"], equipo.get("hostname"), timeout_s)
        resultado["equipo_id"] = equipo.get("equipo_id")
        return resultado

    if not objetivos:
        resultados = []
    else:
        with ThreadPoolExecutor(max_workers=min(10, len(objetivos))) as executor:
            resultados = list(executor.map(_escanear, objetivos))

    online = sum(1 for r in resultados if r["online"])
    offline = len(resultados) - online

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "resumen": {"online": online, "offline": offline},
        "resultados": resultados,
    }
