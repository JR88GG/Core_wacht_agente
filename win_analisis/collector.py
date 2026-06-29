# ============================================================
#  SysWatch Agent — Recolector de métricas (Windows)
#  Temperatura CPU via LibreHardwareMonitor servidor web local
#  El resto de métricas via psutil
# ============================================================

import json
import logging
import platform
import time
import urllib.request
from datetime import datetime, timezone

import psutil

import config

logger = logging.getLogger("syswatch.collector")

# ------------------------------------------------------------------ #
#  Temperatura CPU via LibreHardwareMonitor Web Server               #
#  Requiere LibreHardwareMonitor corriendo con:                      #
#    Options → Run As Administrator    ✅                            #
#    Options → Run On Windows Startup  ✅                            #
#    Options → Remote Web Server → Run ✅  (puerto 8085)            #
# ------------------------------------------------------------------ #

_LHM_URL     = "http://localhost:8085/data.json"
_LHM_TIMEOUT = 2   # segundos — si no responde, no bloquear el ciclo
_lhm_ok      = None  # None=no probado, True=disponible, False=no disponible


def _verificar_lhm() -> bool:
    """Verifica si LibreHardwareMonitor está corriendo. Solo al iniciar."""
    global _lhm_ok
    if _lhm_ok is not None:
        return _lhm_ok
    try:
        urllib.request.urlopen(_LHM_URL, timeout=_LHM_TIMEOUT)
        _lhm_ok = True
        logger.info(
            "LibreHardwareMonitor detectado en localhost:8085 — "
            "temperatura CPU disponible"
        )
    except Exception:
        _lhm_ok = False
        logger.warning(
            "LibreHardwareMonitor no detectado en localhost:8085. "
            "Temperatura CPU no disponible. "
            "Para habilitarla: abrir LibreHardwareMonitor como administrador "
            "y activar Options → Remote Web Server → Run"
        )
    return _lhm_ok


def _buscar_temp_cpu(nodo: dict) -> float | None:
    """
    Recorre recursivamente el árbol JSON de LibreHardwareMonitor
    buscando sensores de temperatura del CPU.
    El árbol tiene esta estructura:
      Children[0] → Equipo
        Children[N] → CPU
          Children[M] → Temperatures
            Children[K] → sensor individual (Value: "65,0 °C")
    """
    texto = nodo.get("Text", "")

    # Nodo de temperatura individual — intentar parsear el valor
    valor_str = nodo.get("Value", "")
    if "°C" in valor_str:
        try:
            # Formato: "65,0 °C" o "65.0 °C"
            num = valor_str.replace("°C", "").replace(",", ".").strip()
            temp = float(num)
            # Validar rango razonable
            if 20 < temp < 110:
                # Solo si el nodo padre es CPU Package o CPU Total
                if any(k in texto for k in ("Package", "Core", "CPU")):
                    return temp
        except ValueError:
            pass

    # Recorrer hijos recursivamente
    for hijo in nodo.get("Children", []):
        resultado = _buscar_temp_cpu(hijo)
        if resultado is not None:
            return resultado

    return None


def _temp_via_lhm() -> float | None:
    """Lee temperatura CPU desde el servidor web de LibreHardwareMonitor."""
    try:
        with urllib.request.urlopen(_LHM_URL, timeout=_LHM_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Buscar específicamente nodos de CPU primero
        def buscar_cpu_temp(nodo: dict, en_cpu: bool = False) -> float | None:
            texto = nodo.get("Text", "")
            # Detectar si estamos en un nodo CPU
            es_cpu = en_cpu or any(k in texto for k in ("CPU", "Processor", "Ryzen", "Intel", "Core"))

            valor_str = nodo.get("Value", "")
            if es_cpu and "°C" in valor_str:
                try:
                    num = valor_str.replace("°C", "").replace(",", ".").strip()
                    temp = float(num)
                    if 20 < temp < 110:
                        return temp
                except ValueError:
                    pass

            # Priorizar "CPU Package" o "CPU Total" que dan la temp global
            if "Package" in texto or "Total" in texto:
                if "°C" in valor_str:
                    try:
                        num = valor_str.replace("°C", "").replace(",", ".").strip()
                        temp = float(num)
                        if 20 < temp < 110:
                            return temp
                    except ValueError:
                        pass

            temps_hijos = []
            for hijo in nodo.get("Children", []):
                r = buscar_cpu_temp(hijo, es_cpu)
                if r is not None:
                    temps_hijos.append(r)

            # Retornar el máximo de los cores (más representativo)
            return max(temps_hijos) if temps_hijos else None

        temp = buscar_cpu_temp(data)
        if temp is not None:
            return round(temp, 1)

    except urllib.error.URLError:
        # LibreHardwareMonitor se cerró o no está disponible
        global _lhm_ok
        _lhm_ok = False
        logger.debug("LibreHardwareMonitor no responde — temp_cpu = None")
    except Exception as e:
        logger.debug("Error leyendo temp desde LHM: %s", e)

    return None


def _temp_via_psutil() -> float | None:
    """Fallback para Linux/Mac via psutil."""
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return None
        for clave in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if clave in temps:
                valores = [e.current for e in temps[clave] if e.current and e.current > 0]
                if valores:
                    return round(max(valores), 1)
        for entradas in temps.values():
            for e in entradas:
                if e.current and 20 < e.current < 110:
                    return round(e.current, 1)
    except Exception:
        pass
    return None


def obtener_temperatura_cpu() -> float | None:
    """
    Obtiene temperatura CPU según el sistema operativo:
      Windows → LibreHardwareMonitor Web Server (localhost:8085)
      Linux   → psutil sensors
    """
    if platform.system() == "Windows":
        if not _verificar_lhm():
            return None
        return _temp_via_lhm()
    return _temp_via_psutil()


# ------------------------------------------------------------------ #
#  Uptime                                                             #
# ------------------------------------------------------------------ #

def obtener_uptime_horas() -> float:
    boot_ts    = psutil.boot_time()
    uptime_seg = time.time() - boot_ts
    return round(uptime_seg / 3600, 2)


# ------------------------------------------------------------------ #
#  Métricas principales                                               #
# ------------------------------------------------------------------ #

def recolectar() -> dict:
    """
    Recolecta todas las métricas del sistema en un snapshot.
    Retorna un dict listo para insertar en la base de datos local.
    """
    ts = datetime.now(timezone.utc).isoformat()

    # CPU
    cpu_pct  = psutil.cpu_percent(interval=1)
    cpu_freq = psutil.cpu_freq()
    freq_mhz = round(cpu_freq.current, 1) if cpu_freq else None

    # RAM
    ram = psutil.virtual_memory()

    # Disco — C: en Windows, / en Linux
    disco_path = "C:\\" if platform.system() == "Windows" else "/"
    try:
        disco          = psutil.disk_usage(disco_path)
        disco_usado_gb = round(disco.used  / (1024**3), 2)
        disco_total_gb = round(disco.total / (1024**3), 2)
        disco_pct      = disco.percent
    except Exception:
        disco_usado_gb = disco_total_gb = disco_pct = None

    return {
        "equipo_id":      config.EQUIPO_ID,
        "timestamp":      ts,
        "cpu_pct":        round(cpu_pct, 1),
        "cpu_freq_mhz":   freq_mhz,
        "ram_usada_mb":   ram.used  // (1024**2),
        "ram_total_mb":   ram.total // (1024**2),
        "ram_pct":        ram.percent,
        "disco_usado_gb": disco_usado_gb,
        "disco_total_gb": disco_total_gb,
        "disco_pct":      disco_pct,
        "temp_cpu":       obtener_temperatura_cpu(),
        "uptime_horas":   obtener_uptime_horas(),
        "total_procesos": len(psutil.pids()),
    }


# ------------------------------------------------------------------ #
#  Snapshot de procesos                                               #
# ------------------------------------------------------------------ #

def recolectar_procesos(top_n: int = 15) -> list[dict]:
    """
    Retorna los top_n procesos por CPU + todos los de lista negra.
    """
    ts       = datetime.now(timezone.utc).isoformat()
    snapshot = []

    for proc in psutil.process_iter(
        attrs=["pid", "name", "cpu_percent", "memory_info", "status"]
    ):
        try:
            info = proc.info
            if info["status"] == psutil.STATUS_ZOMBIE:
                continue

            nombre = (info["name"] or "").lower()
            ram_mb = round(
                (info["memory_info"].rss if info["memory_info"] else 0) / (1024**2), 2
            )
            es_sospechoso = nombre in config.PROCESOS_LISTA_NEGRA

            snapshot.append({
                "equipo_id":     config.EQUIPO_ID,
                "timestamp":     ts,
                "nombre":        info["name"],
                "pid":           info["pid"],
                "cpu_pct":       info["cpu_percent"] or 0.0,
                "ram_mb":        ram_mb,
                "es_sospechoso": 1 if es_sospechoso else 0,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    snapshot.sort(key=lambda x: x["cpu_pct"], reverse=True)

    sospechosos = [p for p in snapshot if p["es_sospechoso"]]
    top         = snapshot[:top_n]

    vistos    = set()
    resultado = []
    for p in sospechosos + top:
        if p["pid"] not in vistos:
            vistos.add(p["pid"])
            resultado.append(p)

    return resultado
