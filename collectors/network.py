"""
collectors/network.py — Interfaces de red y puertos abiertos
(tablas `interfaces_red` y `puertos_abiertos`).
"""

import socket

import psutil


def _es_interfaz_relevante(ip: str, stats) -> bool:
    """
    Filtra interfaces "ruido": sin IP asignada, direcciones APIPA
    (169.254.x.x — Windows las asigna cuando no hay DHCP real), y loopback.
    """
    if not ip:
        return False
    if ip.startswith("169.254.") or ip.startswith("127."):
        return False
    return True


def recolectar_interfaces_red(equipo_id: str) -> list:
    """Devuelve el payload para la tabla `interfaces_red`, solo interfaces con conexión real."""
    resultados = []
    direcciones = psutil.net_if_addrs()
    estadisticas = psutil.net_if_stats()

    for nombre_interfaz, direcciones_lista in direcciones.items():
        ip = None
        mac = None
        for direccion in direcciones_lista:
            if direccion.family == socket.AF_INET:
                ip = direccion.address
            elif direccion.family == psutil.AF_LINK:
                mac = direccion.address

        stats = estadisticas.get(nombre_interfaz)

        if not _es_interfaz_relevante(ip, stats):
            continue

        resultados.append({
            "equipo_id": equipo_id,
            "nombre": nombre_interfaz,
            "mac": mac,
            "ip": ip,
            "gateway": None,  # requiere netifaces o parseo de rutas; se deja para v2
            "dns": None,
            "velocidad": stats.speed if stats else None,
            "estado": stats.isup if stats else None,
        })

    return resultados


def recolectar_puertos_abiertos(equipo_id: str) -> list:
    """
    Devuelve el payload para la tabla `puertos_abiertos`.
    Solo reporta puertos en estado LISTEN (los que realmente exponen un
    servicio), no todas las conexiones activas (eso saturaría la tabla).
    """
    resultados = []

    try:
        conexiones = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        # En Linux, listar conexiones de TODOS los procesos suele requerir
        # privilegios elevados. Si no los tenemos, devolvemos lista vacía
        # en vez de fallar todo el ciclo de recolección.
        return resultados

    for conexion in conexiones:
        if conexion.status != psutil.CONN_LISTEN:
            continue

        nombre_proceso = None
        if conexion.pid:
            try:
                nombre_proceso = psutil.Process(conexion.pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        resultados.append({
            "equipo_id": equipo_id,
            "puerto": conexion.laddr.port if conexion.laddr else None,
            "protocolo": "tcp" if conexion.type == socket.SOCK_STREAM else "udp",
            "servicio": None,  # se podría mapear puerto->servicio conocido en v2
            "estado": "LISTEN",
            "proceso": nombre_proceso,
            "pid": conexion.pid,
        })

    return resultados
