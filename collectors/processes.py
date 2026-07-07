"""
collectors/processes.py — Procesos activos (tabla `procesos`).

Se reportan los procesos con mayor consumo de CPU/RAM (no todos, para no
saturar la BD en cada ciclo). "es_sospechoso" usa una heurística simple y
conservadora, pensada para dar una señal, no un veredicto de seguridad.
"""

import psutil

LIMITE_PROCESOS_REPORTADOS = 25

NOMBRES_SOSPECHOSOS = {
    "mimikatz", "psexec", "netcat", "nc.exe", "ncat",
}

# Caché de objetos Process entre ciclos. psutil necesita DOS lecturas en el
# tiempo para calcular cpu_percent de un proceso; si se crea el objeto de
# cero en cada ciclo, siempre devuelve 0.0 (no hay punto de referencia
# anterior). Guardamos el objeto Process entre llamadas para que la
# siguiente lectura sí tenga con qué comparar.
_cache_procesos = {}


def _es_sospechoso(nombre: str, cpu_pct: float) -> bool:
    nombre_lower = (nombre or "").lower()
    if any(sospechoso in nombre_lower for sospechoso in NOMBRES_SOSPECHOSOS):
        return True
    if cpu_pct is not None and cpu_pct > 90:
        return True
    return False


def recolectar_procesos(equipo_id: str) -> list:
    """Devuelve el top de procesos por consumo, para la tabla `procesos`."""
    pids_actuales = set(psutil.pids())

    # Limpiar del caché los procesos que ya no existen
    for pid_viejo in list(_cache_procesos.keys()):
        if pid_viejo not in pids_actuales:
            del _cache_procesos[pid_viejo]

    procesos = []

    for pid in pids_actuales:
        try:
            if pid not in _cache_procesos:
                proceso_obj = psutil.Process(pid)
                proceso_obj.cpu_percent(interval=None)  # llamada "de calentamiento"
                _cache_procesos[pid] = proceso_obj
                continue  # esta primera vez no tiene lectura previa confiable, se reporta en el próximo ciclo

            proceso_obj = _cache_procesos[pid]
            cpu_pct = proceso_obj.cpu_percent(interval=None)  # % desde la última lectura (~intervalo del agente)
            ram_mb = proceso_obj.memory_info().rss / (1024 ** 2)
            nombre = proceso_obj.name()

            procesos.append({
                "equipo_id": equipo_id,
                "nombre": nombre,
                "pid": pid,
                "cpu_pct": round(cpu_pct, 2),
                "ram_mb": round(ram_mb, 2),
                "es_sospechoso": _es_sospechoso(nombre, cpu_pct),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            _cache_procesos.pop(pid, None)
            continue

    procesos.sort(key=lambda p: (p["cpu_pct"], p["ram_mb"]), reverse=True)
    return procesos[:LIMITE_PROCESOS_REPORTADOS]
