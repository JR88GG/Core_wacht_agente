"""
collectors/system_metrics.py — Métricas generales de CPU/RAM/Disco (tabla `metricas`).
"""

import time

import psutil

_INICIO_PROCESO = time.time()


def _temperatura_cpu():
    """
    Best-effort: la temperatura de CPU NO tiene una API uniforme entre
    Windows y Linux. En Linux suele funcionar vía psutil (si el kernel
    expone sensores). En Windows psutil no lo soporta en la mayoría de
    los casos (requeriría WMI + hardware específico del fabricante), así
    que devolvemos None en vez de inventar un dato.
    """
    if not hasattr(psutil, "sensors_temperatures"):
        return None
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None

    for etiquetas_posibles in ("coretemp", "k10temp", "cpu_thermal", "cpu-thermal"):
        if etiquetas_posibles in temps and temps[etiquetas_posibles]:
            return round(temps[etiquetas_posibles][0].current, 1)

    # Si no encontramos una etiqueta conocida, tomamos la primera disponible
    for lecturas in temps.values():
        if lecturas:
            return round(lecturas[0].current, 1)
    return None


def _uptime_horas():
    return round((time.time() - psutil.boot_time()) / 3600, 2)


def recolectar_metricas(equipo_id: str) -> dict:
    """Devuelve el payload que llena la tabla `metricas`."""
    cpu_pct = psutil.cpu_percent(interval=1)  # bloquea 1s, da una lectura real
    cpu_freq = psutil.cpu_freq()
    ram = psutil.virtual_memory()
    disco = psutil.disk_usage("/" if not _es_windows() else "C:\\")
    procesos = len(psutil.pids())

    return {
        "equipo_id": equipo_id,
        "cpu_pct": round(cpu_pct, 2),
        "cpu_freq_mhz": round(cpu_freq.current, 2) if cpu_freq else None,
        "ram_usada_mb": round(ram.used / (1024 ** 2)),
        "ram_total_mb": round(ram.total / (1024 ** 2)),
        "ram_pct": round(ram.percent, 2),
        "disco_usado_gb": round(disco.used / (1024 ** 3), 2),
        "disco_total_gb": round(disco.total / (1024 ** 3), 2),
        "disco_pct": round(disco.percent, 2),
        "temp_cpu": _temperatura_cpu(),
        "uptime_horas": _uptime_horas(),
        "total_procesos": procesos,
    }


def _es_windows():
    import platform
    return platform.system().lower() == "windows"
