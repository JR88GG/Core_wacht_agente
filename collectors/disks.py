"""
collectors/disks.py — Estado de discos (tabla `discos`).

Nota honesta sobre límites: la salud SMART (`estado_smart`, `vida_util`)
requiere herramientas específicas (smartctl / WMI MSStorageDriver_*) que no
siempre están instaladas ni accesibles sin permisos elevados. Se intenta
best-effort y se deja en None si no se puede leer, en vez de inventar datos.
"""

import platform

import psutil


def _intentar_smart(device_path):
    """
    Intento best-effort de leer estado SMART.
    Requiere que 'smartctl' (smartmontools) esté instalado en el sistema.
    Si no está disponible, devuelve (None, None) sin fallar.
    """
    import shutil
    import subprocess
    import json as json_module

    if shutil.which("smartctl") is None:
        return None, None

    try:
        salida = subprocess.run(
            ["smartctl", "-a", "-j", device_path],
            capture_output=True, text=True, timeout=5
        )
        data = json_module.loads(salida.stdout)
        estado = "OK" if data.get("smart_status", {}).get("passed") else "FALLA"
        vida_util = None
        for attr in data.get("ata_smart_attributes", {}).get("table", []):
            if attr.get("name") in ("Percent_Lifetime_Remain", "Media_Wearout_Indicator"):
                vida_util = attr.get("value")
        return estado, vida_util
    except Exception:
        return None, None


def recolectar_discos(equipo_id: str) -> list:
    """Devuelve una lista de payloads, uno por partición, para la tabla `discos`."""
    resultados = []

    for particion in psutil.disk_partitions(all=False):
        try:
            uso = psutil.disk_usage(particion.mountpoint)
        except (PermissionError, OSError):
            continue

        estado_smart, vida_util = _intentar_smart(particion.device)

        resultados.append({
            "equipo_id": equipo_id,
            "nombre": particion.mountpoint,
            "tipo": particion.fstype or None,
            "capacidad_gb": round(uso.total / (1024 ** 3), 2),
            "espacio_libre_gb": round(uso.free / (1024 ** 3), 2),
            "porcentaje_usado": round(uso.percent, 2),
            "temperatura": None,  # requiere smartctl -A, se deja para una v2
            "serial": None,       # requiere WMI (Windows) / udevadm (Linux)
            "estado_smart": estado_smart,
            "vida_util": vida_util,
        })

    return resultados
