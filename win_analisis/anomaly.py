# ============================================================
#  SysWatch Agent — Detector de anomalías
#  Z-score dinámico + reglas fijas + tendencias predictivas
#  Sin IA, sin dependencias externas. ~0 MB RAM adicional.
# ============================================================

import logging
import math
from datetime import datetime, timezone
from collections import deque

import config

logger = logging.getLogger("syswatch.anomaly")


# ------------------------------------------------------------------ #
#  Buffer circular en memoria para baseline por métrica              #
# ------------------------------------------------------------------ #

class BaselineBuffer:
    """
    Mantiene una ventana deslizante de valores para calcular
    media y desviación estándar sin guardar todo en memoria.
    """
    def __init__(self, maxlen: int = 120):
        self._q: deque[float] = deque(maxlen=maxlen)

    def agregar(self, valor: float):
        if valor is not None:
            self._q.append(valor)

    def listo(self) -> bool:
        return len(self._q) >= 10  # mínimo para calcular baseline

    def media(self) -> float:
        return sum(self._q) / len(self._q)

    def desv_std(self) -> float:
        if len(self._q) < 2:
            return 0.0
        m = self.media()
        varianza = sum((x - m) ** 2 for x in self._q) / (len(self._q) - 1)
        return math.sqrt(varianza)

    def z_score(self, valor: float) -> float:
        d = self.desv_std()
        if d == 0:
            return 0.0
        return (valor - self.media()) / d

    def tendencia_por_hora(self) -> float | None:
        """
        Regresión lineal simple sobre los valores del buffer.
        Retorna cuánto cambia la métrica por 'muestra' en promedio.
        Multiplicar por muestras/hora para proyectar.
        """
        n = len(self._q)
        if n < 20:
            return None
        vals = list(self._q)
        xs = list(range(n))
        mx = sum(xs) / n
        my = sum(vals) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, vals))
        den = sum((x - mx) ** 2 for x in xs)
        if den == 0:
            return None
        return num / den  # pendiente por muestra


# ------------------------------------------------------------------ #
#  Estado global de buffers (uno por métrica)                        #
# ------------------------------------------------------------------ #

_buffers: dict[str, BaselineBuffer] = {
    "cpu_pct":   BaselineBuffer(config.ANOMALIA_VENTANA),
    "ram_pct":   BaselineBuffer(config.ANOMALIA_VENTANA),
    "disco_pct": BaselineBuffer(config.ANOMALIA_VENTANA),
    "temp_cpu":  BaselineBuffer(config.ANOMALIA_VENTANA),
}

# Últimas alertas para evitar spam (tipo → timestamp última alerta)
_ultima_alerta: dict[str, float] = {}
COOLDOWN_SEG = 300  # 5 minutos mínimo entre alertas del mismo tipo


def _puede_alertar(tipo: str) -> bool:
    import time
    ahora = time.time()
    ultima = _ultima_alerta.get(tipo, 0)
    if ahora - ultima >= COOLDOWN_SEG:
        _ultima_alerta[tipo] = ahora
        return True
    return False


# ------------------------------------------------------------------ #
#  Función principal de análisis                                     #
# ------------------------------------------------------------------ #

def analizar(metrica: dict) -> list[dict]:
    """
    Recibe un dict de métricas recolectadas.
    Retorna lista de alertas (puede ser vacía).
    Actualiza los buffers de baseline internamente.
    """
    alertas = []
    ts = datetime.now(timezone.utc).isoformat()
    eid = config.EQUIPO_ID

    # --- Actualizar buffers con los valores actuales ---
    for campo, buf in _buffers.items():
        val = metrica.get(campo)
        if val is not None:
            buf.agregar(val)

    # --- Reglas fijas (umbrales absolutos) ---
    alertas += _reglas_temperatura(metrica, ts, eid)
    alertas += _reglas_ram(metrica, ts, eid)
    alertas += _reglas_disco(metrica, ts, eid)
    alertas += _reglas_cpu_sostenido(metrica, ts, eid)

    # --- Z-score dinámico (anomalías relativas al baseline) ---
    alertas += _zscore_alertas(metrica, ts, eid)

    # --- Tendencias predictivas ---
    alertas += _tendencias(ts, eid)

    if alertas:
        logger.warning("Anomalías detectadas: %d alerta(s)", len(alertas))

    return alertas


# ------------------------------------------------------------------ #
#  Reglas fijas                                                      #
# ------------------------------------------------------------------ #

def _reglas_temperatura(m: dict, ts: str, eid: str) -> list[dict]:
    alertas = []
    temp = m.get("temp_cpu")
    if temp is None:
        return alertas

    if temp >= config.TEMP_CRITICA_CPU and _puede_alertar("temp_critica"):
        alertas.append(_alerta(eid, ts, "temperatura", "critical",
            f"Temperatura CPU crítica: {temp}°C (umbral: {config.TEMP_CRITICA_CPU}°C). "
            "Riesgo de apagado por protección térmica.",
            temp, config.TEMP_CRITICA_CPU))

    elif temp >= config.TEMP_WARNING_CPU and _puede_alertar("temp_warning"):
        alertas.append(_alerta(eid, ts, "temperatura", "warning",
            f"Temperatura CPU elevada: {temp}°C (umbral: {config.TEMP_WARNING_CPU}°C). "
            "Revisar ventilación y pasta térmica.",
            temp, config.TEMP_WARNING_CPU))
    return alertas


def _reglas_ram(m: dict, ts: str, eid: str) -> list[dict]:
    alertas = []
    ram = m.get("ram_pct")
    if ram is None:
        return alertas

    if ram >= config.RAM_CRITICA_PCT and _puede_alertar("ram_critica"):
        alertas.append(_alerta(eid, ts, "ram", "critical",
            f"RAM crítica: {ram:.1f}% utilizada. "
            "El sistema puede volverse inestable o crashear.",
            ram, config.RAM_CRITICA_PCT))

    elif ram >= config.RAM_WARNING_PCT and _puede_alertar("ram_warning"):
        alertas.append(_alerta(eid, ts, "ram", "warning",
            f"RAM elevada: {ram:.1f}% utilizada. "
            "Considerar cerrar aplicaciones o agregar memoria.",
            ram, config.RAM_WARNING_PCT))
    return alertas


def _reglas_disco(m: dict, ts: str, eid: str) -> list[dict]:
    alertas = []
    disco = m.get("disco_pct")
    if disco is None:
        return alertas

    if disco >= config.DISCO_CRITICO_PCT and _puede_alertar("disco_critico"):
        alertas.append(_alerta(eid, ts, "disco", "critical",
            f"Disco casi lleno: {disco:.1f}% utilizado. "
            "Liberar espacio inmediatamente para evitar fallos del sistema.",
            disco, config.DISCO_CRITICO_PCT))

    elif disco >= config.DISCO_WARNING_PCT and _puede_alertar("disco_warning"):
        alertas.append(_alerta(eid, ts, "disco", "warning",
            f"Espacio en disco reducido: {disco:.1f}% utilizado.",
            disco, config.DISCO_WARNING_PCT))
    return alertas


def _reglas_cpu_sostenido(m: dict, ts: str, eid: str) -> list[dict]:
    alertas = []
    cpu = m.get("cpu_pct")
    if cpu is None:
        return alertas

    if cpu >= config.CPU_CRITICO_PCT and _puede_alertar("cpu_critico"):
        alertas.append(_alerta(eid, ts, "cpu", "critical",
            f"CPU al {cpu:.1f}% — carga crítica sostenida. "
            "Revisar procesos activos.",
            cpu, config.CPU_CRITICO_PCT))

    elif cpu >= config.CPU_WARNING_PCT and _puede_alertar("cpu_warning"):
        alertas.append(_alerta(eid, ts, "cpu", "warning",
            f"CPU al {cpu:.1f}% — carga elevada.",
            cpu, config.CPU_WARNING_PCT))
    return alertas


# ------------------------------------------------------------------ #
#  Z-score (anomalía relativa al baseline del equipo)               #
# ------------------------------------------------------------------ #

def _zscore_alertas(m: dict, ts: str, eid: str) -> list[dict]:
    alertas = []
    campos_legibles = {
        "cpu_pct":   ("CPU", "%"),
        "ram_pct":   ("RAM", "%"),
        "temp_cpu":  ("Temperatura CPU", "°C"),
    }

    for campo, (nombre, unidad) in campos_legibles.items():
        buf = _buffers.get(campo)
        val = m.get(campo)
        if not buf or val is None or not buf.listo():
            continue

        z = buf.z_score(val)
        if abs(z) >= config.ANOMALIA_Z_UMBRAL and _puede_alertar(f"zscore_{campo}"):
            direccion = "pico inusual" if z > 0 else "caída inusual"
            media = round(buf.media(), 1)
            alertas.append(_alerta(eid, ts, "anomalia", "warning",
                f"{nombre} con {direccion}: {val}{unidad} "
                f"(media normal del equipo: {media}{unidad}, z-score: {z:.1f}). "
                "Comportamiento fuera del patrón habitual de este equipo.",
                val, media))

    return alertas


# ------------------------------------------------------------------ #
#  Tendencias predictivas                                            #
# ------------------------------------------------------------------ #

def _tendencias(ts: str, eid: str) -> list[dict]:
    """
    Proyecta valores futuros basándose en la tendencia del buffer.
    Alerta si el disco se llenará en menos de N días al ritmo actual.
    """
    alertas = []
    buf_disco = _buffers["disco_pct"]

    if not buf_disco.listo():
        return alertas

    pendiente = buf_disco.tendencia_por_hora()
    if pendiente is None or pendiente <= 0:
        return alertas

    # muestras_por_hora ≈ 3600 / INTERVALO_RECOLECCION_SEG
    muestras_hora = 3600 / config.INTERVALO_RECOLECCION_SEG
    cambio_por_hora = pendiente * muestras_hora
    pct_actual = buf_disco.media()
    espacio_libre = 100.0 - pct_actual

    if cambio_por_hora <= 0:
        return alertas

    horas_hasta_lleno = espacio_libre / cambio_por_hora
    dias_hasta_lleno = horas_hasta_lleno / 24

    if dias_hasta_lleno < 3 and _puede_alertar("tendencia_disco_critica"):
        alertas.append(_alerta(eid, ts, "tendencia", "critical",
            f"El disco se llenará en aproximadamente {dias_hasta_lleno:.1f} días "
            f"al ritmo de crecimiento actual ({cambio_por_hora:.2f}%/hora). "
            "Acción urgente requerida.",
            pct_actual, 100.0))

    elif dias_hasta_lleno < 14 and _puede_alertar("tendencia_disco_warning"):
        alertas.append(_alerta(eid, ts, "tendencia", "warning",
            f"Proyección: disco lleno en ~{dias_hasta_lleno:.0f} días "
            f"al ritmo actual. Considerar limpieza.",
            pct_actual, 100.0))

    return alertas


# ------------------------------------------------------------------ #
#  Helper                                                            #
# ------------------------------------------------------------------ #

def _alerta(equipo_id, ts, tipo, severidad, descripcion, valor_actual, valor_umbral) -> dict:
    logger.warning("[%s] %s — %s", severidad.upper(), tipo, descripcion)
    return {
        "equipo_id":    equipo_id,
        "timestamp":    ts,
        "tipo":         tipo,
        "severidad":    severidad,
        "descripcion":  descripcion,
        "valor_actual": valor_actual,
        "valor_umbral": valor_umbral,
    }


def cargar_historial_desde_db():
    """
    Carga el historial de la SQLite local al iniciar el agente
    para que el baseline no empiece desde cero en cada reinicio.
    """
    try:
        import local_db
        for campo, buf in _buffers.items():
            historial = local_db.historial_campo(campo, n=config.ANOMALIA_VENTANA)
            for val in reversed(historial):  # de más antiguo a más reciente
                buf.agregar(val)
        logger.info("Historial de baseline cargado desde DB local")
    except Exception as e:
        logger.warning("No se pudo cargar historial de baseline: %s", e)
