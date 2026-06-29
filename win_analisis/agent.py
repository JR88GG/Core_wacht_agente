# ============================================================
#  SysWatch Agent — Loop principal
#  Orquesta: recolección → detección → almacenamiento → envío
#
#  Instalación de dependencias:
#    pip install psutil requests
#
#  Ejecutar:
#    python agent.py
#
#  Como tarea programada (recomendado para producción):
#    Programador de tareas → Nueva tarea
#    → Acción: python.exe  Argumento: C:\syswatch\agent.py
#    → Desencadenador: Al iniciar el equipo
#
#  Como servicio Windows (usando NSSM):
#    nssm install SysWatchAgent "C:\Python311\python.exe" "C:\syswatch\agent.py"
#    nssm start SysWatchAgent
# ============================================================

import logging
import signal
import sys
import time
from datetime import datetime, timezone

import config
import local_db
import collector
import anomaly
import sender


# ------------------------------------------------------------------ #
#  Logging                                                           #
# ------------------------------------------------------------------ #

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("syswatch.main")


# ------------------------------------------------------------------ #
#  Control de ciclo                                                  #
# ------------------------------------------------------------------ #

_corriendo = True

def _handle_signal(sig, frame):
    global _corriendo
    logger.info("Señal %d recibida — cerrando agente...", sig)
    _corriendo = False

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ------------------------------------------------------------------ #
#  Ciclo principal                                                   #
# ------------------------------------------------------------------ #

def ciclo_principal():
    logger.info("=" * 55)
    logger.info("  SysWatch Agent iniciando")
    logger.info("  Equipo: %s  |  ID: %s", config.EQUIPO_NOMBRE, config.EQUIPO_ID)
    logger.info("  Hub: %s", config.HUB_URL)
    logger.info("=" * 55)

    # 1. Inicializar base de datos local
    local_db.inicializar()

    # 2. Cargar historial para baseline (no empezar desde cero)
    anomaly.cargar_historial_desde_db()

    # 3. Primer heartbeat al hub
    sender.enviar_heartbeat()

    # Contadores para tareas periódicas
    ciclos           = 0
    ciclos_limpieza  = int(config.INTERVALO_LIMPIEZA_HORAS * 3600 / config.INTERVALO_RECOLECCION_SEG)
    ciclos_heartbeat = int(300 / config.INTERVALO_RECOLECCION_SEG)

    while _corriendo:
        t_inicio = time.monotonic()
        ciclos  += 1

        try:
            _ejecutar_ciclo(ciclos, ciclos_limpieza, ciclos_heartbeat)
        except Exception as e:
            logger.error("Error en ciclo principal: %s", e, exc_info=True)

        elapsed = time.monotonic() - t_inicio
        espera  = max(0, config.INTERVALO_RECOLECCION_SEG - elapsed)
        time.sleep(espera)

    logger.info("SysWatch Agent detenido correctamente.")


def _ejecutar_ciclo(ciclos: int, ciclos_limpieza: int, ciclos_heartbeat: int):
    """Un ciclo completo de recolección → análisis → almacenamiento → envío."""

    # --- A. Recolectar métricas ---
    metricas = collector.recolectar()
    logger.debug(
        "CPU %.1f%%  RAM %.1f%%  Disco %.1f%%  Temp %s°C",
        metricas["cpu_pct"],
        metricas["ram_pct"],
        metricas.get("disco_pct", 0),
        metricas.get("temp_cpu", "N/A"),
    )

    # --- B. Detectar anomalías ---
    alertas = anomaly.analizar(metricas)

    # --- C. Guardar en DB local (siempre, independiente de la red) ---
    local_db.insertar_metrica(metricas)

    if alertas:
        for a in alertas:
            local_db.insertar_alerta(a)

    # --- D. Recolectar procesos (cada 5 ciclos para aliviar la carga) ---
    if ciclos % 5 == 0:
        procesos = collector.recolectar_procesos(top_n=15)
        local_db.insertar_procesos(procesos)

        sospechosos = [p for p in procesos if p["es_sospechoso"]]
        if sospechosos:
            logger.warning(
                "Procesos sospechosos detectados: %s",
                [p["nombre"] for p in sospechosos]
            )

    # --- E. Intentar enviar en tiempo real ---
    exito_metrica = sender.enviar_metrica(metricas)

    if exito_metrica:
        sender.sincronizar_pendientes()

    if alertas:
        sender.enviar_alertas_inmediatas(alertas)

    # --- F. Heartbeat periódico ---
    if ciclos % ciclos_heartbeat == 0:
        sender.enviar_heartbeat()

    # --- G. Limpieza periódica de DB ---
    if ciclos % ciclos_limpieza == 0:
        local_db.limpiar_antiguos()
        pendientes = local_db.contar_pendientes()
        logger.info("Pendientes en DB local: %s", pendientes)

        if pendientes["metricas"] > config.DB_MAX_PENDIENTES:
            logger.warning(
                "Cola de pendientes muy grande (%d métricas). "
                "El hub lleva mucho tiempo sin responder.",
                pendientes["metricas"]
            )


# ------------------------------------------------------------------ #
#  Entry point                                                       #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    ciclo_principal()
