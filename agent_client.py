"""
agent_client.py — Bucle de recolección + envío al servidor.

Corre tanto en máquinas "agente puro" como en la máquina "servidor"
(que también debe reportar su propia información, como pediste).
"""

import time
import logging

import requests

from collectors import (
    identity,
    system_metrics,
    disks,
    processes,
    network,
    gpu_metrics,
    usb,
    hardware,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [agent] %(message)s")
log = logging.getLogger("corewatch.agent")


def armar_payload(equipo_id: str) -> dict:
    """Arma el payload completo de un ciclo de recolección."""
    return {
        "equipo": identity.recolectar_identidad(equipo_id),
        "metricas": system_metrics.recolectar_metricas(equipo_id),
        "discos": disks.recolectar_discos(equipo_id),
        "procesos": processes.recolectar_procesos(equipo_id),
        "interfaces_red": network.recolectar_interfaces_red(equipo_id),
        "puertos_abiertos": network.recolectar_puertos_abiertos(equipo_id),
        "gpu_metricas": gpu_metrics.recolectar_gpu_metricas(equipo_id),
        "perifericos_usb": usb.recolectar_perifericos_usb(equipo_id),
        "hardware": hardware.recolectar_hardware(equipo_id),
    }


def enviar_payload(server_url: str, api_key: str, payload: dict, timeout=30) -> bool:
    """POST del payload al endpoint /ingest del servidor. Devuelve True si tuvo éxito."""
    try:
        respuesta = requests.post(
            f"{server_url}/ingest",
            json=payload,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )
        if respuesta.status_code == 200:
            log.info("Datos enviados correctamente.")
            return True

        log.warning(
            "El servidor respondió %s: %s",
            respuesta.status_code, respuesta.text[:300],
        )
        return False
    except requests.RequestException as error:
        log.warning("No se pudo contactar al servidor (%s). Se reintentará en el próximo ciclo.", error)
        return False


def correr_bucle_agente(config: dict, server_url: str = None):
    """
    Bucle infinito de recolección + envío.
    server_url permite forzar un destino (usado por el propio servidor para
    reportarse a sí mismo vía localhost, sin depender de config["server_url"]).
    """
    equipo_id = config["equipo_id"]
    api_key = config["api_key"]
    intervalo = config.get("intervalo_segundos", 60)
    destino = server_url or config.get("server_url")

    if not destino:
        raise RuntimeError("No hay server_url configurado para este agente.")

    log.info("Agente iniciado. equipo_id=%s destino=%s intervalo=%ss", equipo_id, destino, intervalo)

    while True:
        try:
            payload = armar_payload(equipo_id)
            enviar_payload(destino, api_key, payload)
        except Exception as error:
            log.error("Error inesperado en el ciclo de recolección: %s", error)

        time.sleep(intervalo)
