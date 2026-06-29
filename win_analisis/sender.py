# ============================================================
#  SysWatch Agent — Emisor HTTP al Hub (Raspberry Pi)
#  Cola offline: guarda en SQLite si no hay red,
#  reenvía pendientes automáticamente al reconectar.
# ============================================================

import logging
import time
import json
from datetime import datetime

import requests

import config
import local_db

logger = logging.getLogger("syswatch.sender")

TIMEOUT_SEG    = 8    # timeout por request
BATCH_SIZE     = 100  # registros por batch de reenvío
MAX_REINTENTOS = 3


def _headers() -> dict:
    return {
        "Content-Type":  "application/json",
        "X-API-Key":     config.HUB_API_KEY,
        "X-Equipo-ID":   config.EQUIPO_ID,
        "X-Equipo-Nombre": config.EQUIPO_NOMBRE,
    }


def _post(endpoint: str, payload: dict | list) -> bool:
    """Intenta un POST al hub. Retorna True si tuvo éxito."""
    url = f"{config.HUB_URL}{endpoint}"
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = requests.post(
                url,
                json=payload,
                headers=_headers(),
                timeout=TIMEOUT_SEG
            )
            if resp.status_code in (200, 201):
                return True
            logger.warning("Hub respondió %d en %s (intento %d)",
                           resp.status_code, endpoint, intento)
        except requests.exceptions.ConnectionError:
            logger.debug("Sin conexión al hub (intento %d/%d)", intento, MAX_REINTENTOS)
        except requests.exceptions.Timeout:
            logger.warning("Timeout conectando al hub (intento %d/%d)", intento, MAX_REINTENTOS)
        except Exception as e:
            logger.error("Error inesperado enviando a hub: %s", e)
            return False

        if intento < MAX_REINTENTOS:
            time.sleep(2 ** intento)  # backoff exponencial

    return False


# ------------------------------------------------------------------ #
#  Envío en tiempo real (tras cada recolección)                      #
# ------------------------------------------------------------------ #

def enviar_metrica(datos: dict) -> bool:
    """
    Intenta enviar una métrica al hub.
    Si falla, se deja en la DB local como pendiente (ya insertada antes).
    """
    ok = _post("/api/metricas", datos)
    if ok:
        logger.debug("Métrica enviada en tiempo real")
    return ok


def enviar_alertas_inmediatas(alertas: list[dict]) -> bool:
    """Las alertas se intentan enviar inmediatamente por su urgencia."""
    if not alertas:
        return True
    ok = _post("/api/alertas/batch", alertas)
    if ok:
        logger.info("Alertas enviadas: %d", len(alertas))
    return ok


# ------------------------------------------------------------------ #
#  Sincronización de pendientes (cola offline)                       #
# ------------------------------------------------------------------ #

def sincronizar_pendientes():
    """
    Envía al hub todos los registros que quedaron pendientes
    mientras no había conexión. Se llama en cada ciclo del agente.
    """
    _sync_tabla(
        tabla="metricas",
        obtener_fn=local_db.obtener_pendientes_metricas,
        endpoint="/api/metricas/batch",
    )
    _sync_tabla(
        tabla="alertas",
        obtener_fn=local_db.obtener_pendientes_alertas,
        endpoint="/api/alertas/batch",
    )
    _sync_tabla(
        tabla="procesos",
        obtener_fn=local_db.obtener_pendientes_procesos,
        endpoint="/api/procesos/batch",
    )


def _sync_tabla(tabla: str, obtener_fn, endpoint: str):
    """Genérico: toma pendientes → envía en batch → marca enviados."""
    pendientes = obtener_fn(limite=BATCH_SIZE)
    if not pendientes:
        return

    logger.info("Sincronizando %d registros pendientes de '%s'...", len(pendientes), tabla)

    ok = _post(endpoint, pendientes)
    if ok:
        ids = [r["id"] for r in pendientes]
        local_db.marcar_enviados(tabla, ids)
        logger.info("Sincronizados %d registros de '%s'", len(ids), tabla)
    else:
        logger.warning(
            "No se pudieron sincronizar pendientes de '%s'. "
            "Se reintentará en el próximo ciclo.", tabla
        )


# ------------------------------------------------------------------ #
#  Heartbeat (registro del equipo en el hub)                        #
# ------------------------------------------------------------------ #

def enviar_heartbeat() -> bool:
    """
    Registra/actualiza el equipo en el hub.
    Se llama al iniciar el agente y periódicamente.
    """
    import platform
    payload = {
        "equipo_id":     config.EQUIPO_ID,
        "nombre":        config.EQUIPO_NOMBRE,
        "os":            platform.system(),
        "os_version":    platform.version(),
        "os_release":    platform.release(),
        "arquitectura":  platform.machine(),
        "timestamp":     datetime.utcnow().isoformat(),
    }
    ok = _post("/api/equipos/heartbeat", payload)
    if ok:
        logger.info("Heartbeat enviado al hub")
    else:
        logger.warning("Hub no disponible — operando en modo offline")
    return ok


def hub_disponible() -> bool:
    """Comprueba si el hub está alcanzable."""
    try:
        resp = requests.get(
            f"{config.HUB_URL}/health",
            headers=_headers(),
            timeout=4
        )
        return resp.status_code == 200
    except Exception:
        return False
