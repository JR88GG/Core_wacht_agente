# ============================================================
#  SysWatch Hub — Sincronizador hacia PostgreSQL
#  Corre en hilo de fondo cada X horas.
#  Envia datos en batches para no saturar la Pi ni la red.
# ============================================================

import logging
import threading
import time
from datetime import datetime

import config
import database as db

logger = logging.getLogger("syswatch.hub.sync")

# psycopg2 es opcional; si no está instalado, sync queda deshabilitado
try:
    import psycopg2
    import psycopg2.extras
    _PG_DISPONIBLE = True
except ImportError:
    _PG_DISPONIBLE = False
    logger.warning("psycopg2 no instalado — sync a PostgreSQL deshabilitado")


def _get_pg():
    return psycopg2.connect(config.PG_DSN, connect_timeout=config.PG_TIMEOUT_SEG)


# ------------------------------------------------------------------ #
#  Inicializar schema en PostgreSQL (se llama una sola vez al inicio)#
# ------------------------------------------------------------------ #

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS equipos (
    equipo_id    TEXT PRIMARY KEY,
    nombre       TEXT,
    os           TEXT,
    os_version   TEXT,
    os_release   TEXT,
    arquitectura TEXT,
    ip           TEXT,
    ultimo_visto TIMESTAMPTZ,
    activo       BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS metricas (
    id             BIGSERIAL PRIMARY KEY,
    equipo_id      TEXT REFERENCES equipos(equipo_id) ON DELETE CASCADE,
    timestamp      TIMESTAMPTZ NOT NULL,
    cpu_pct        REAL,
    cpu_freq_mhz   REAL,
    ram_usada_mb   INTEGER,
    ram_total_mb   INTEGER,
    ram_pct        REAL,
    disco_usado_gb REAL,
    disco_total_gb REAL,
    disco_pct      REAL,
    temp_cpu       REAL,
    uptime_horas   REAL,
    total_procesos INTEGER,
    recibido_en    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS procesos (
    id            BIGSERIAL PRIMARY KEY,
    equipo_id     TEXT,
    timestamp     TIMESTAMPTZ NOT NULL,
    nombre        TEXT,
    pid           INTEGER,
    cpu_pct       REAL,
    ram_mb        REAL,
    es_sospechoso BOOLEAN DEFAULT FALSE,
    recibido_en   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alertas (
    id           BIGSERIAL PRIMARY KEY,
    equipo_id    TEXT,
    timestamp    TIMESTAMPTZ NOT NULL,
    tipo         TEXT,
    severidad    TEXT,
    descripcion  TEXT,
    valor_actual REAL,
    valor_umbral REAL,
    resuelta     BOOLEAN DEFAULT FALSE,
    recibido_en  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pg_m_equipo ON metricas(equipo_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_pg_a_equipo ON alertas(equipo_id, resuelta);
"""


def inicializar_pg():
    if not _PG_DISPONIBLE or not config.PG_HABILITADO:
        return
    try:
        with _get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()
        logger.info("Schema PostgreSQL verificado/creado correctamente")
    except Exception as e:
        logger.error("No se pudo inicializar PostgreSQL: %s", e)


# ------------------------------------------------------------------ #
#  Sincronización batch                                              #
# ------------------------------------------------------------------ #

def sincronizar():
    """
    Sincroniza tablas pendientes de SQLite → PostgreSQL.
    Equipos → Métricas → Procesos → Alertas (en ese orden para FKs).
    """
    if not _PG_DISPONIBLE or not config.PG_HABILITADO:
        return

    try:
        import led_status
        led_status.controlador._pantalla._disp_backup = led_status.controlador._pantalla._disp
        led_status.controlador._pantalla._disp = None
        logger.info("Pantalla pausada durante sync")
    except Exception:
        pass
    logger.info("Iniciando sincronización a PostgreSQL...")
    inicio = time.monotonic()

    try:
        with _get_pg() as pg_conn:
            _sync_equipos(pg_conn)
            total_m = _sync_tabla(
                pg_conn, "metricas",
                """INSERT INTO metricas (
                       equipo_id, timestamp, cpu_pct, cpu_freq_mhz,
                       ram_usada_mb, ram_total_mb, ram_pct,
                       disco_usado_gb, disco_total_gb, disco_pct,
                       temp_cpu, uptime_horas, total_procesos
                   ) VALUES %s ON CONFLICT DO NOTHING""",
                lambda r: (
                    r["equipo_id"], r["timestamp"], r["cpu_pct"], r["cpu_freq_mhz"],
                    r["ram_usada_mb"], r["ram_total_mb"], r["ram_pct"],
                    r["disco_usado_gb"], r["disco_total_gb"], r["disco_pct"],
                    r["temp_cpu"], r["uptime_horas"], r["total_procesos"]
                )
            )
            total_p = _sync_tabla(
                pg_conn, "procesos",
                """INSERT INTO procesos (
                       equipo_id, timestamp, nombre, pid,
                       cpu_pct, ram_mb, es_sospechoso
                   ) VALUES %s ON CONFLICT DO NOTHING""",
                lambda r: (
                    r["equipo_id"], r["timestamp"], r["nombre"], r["pid"],
                    r["cpu_pct"], r["ram_mb"], bool(r["es_sospechoso"])
                )
            )
            total_a = _sync_tabla(
                pg_conn, "alertas",
                """INSERT INTO alertas (
                       equipo_id, timestamp, tipo, severidad,
                       descripcion, valor_actual, valor_umbral
                   ) VALUES %s ON CONFLICT DO NOTHING""",
                lambda r: (
                    r["equipo_id"], r["timestamp"], r["tipo"], r["severidad"],
                    r["descripcion"], r["valor_actual"], r["valor_umbral"]
                )
            )
            pg_conn.commit()

        db.purgar_sincronizados()

        elapsed = time.monotonic() - inicio
        logger.info(
            "Sync completado en %.1fs — métricas: %d, procesos: %d, alertas: %d",
            elapsed, total_m, total_p, total_a
        )

    except Exception as e:
        logger.error("Error en sync a PostgreSQL: %s", e)
    try:
        import led_status
        led_status.controlador._pantalla._disp = led_status.controlador._pantalla._disp_backup
        logger.info("Pantalla reinicializada post-sync")
    except Exception:
        pass


def _sync_equipos(pg_conn):
    """Upsert de todos los equipos conocidos en la SQLite hacia PG."""
    equipos = db.obtener_equipos()
    if not equipos:
        return
    with pg_conn.cursor() as cur:
        for eq in equipos:
            cur.execute("""
                INSERT INTO equipos (equipo_id, nombre, os, os_version,
                                     os_release, arquitectura, ip, ultimo_visto)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(equipo_id) DO UPDATE SET
                    nombre=EXCLUDED.nombre, os=EXCLUDED.os,
                    ip=EXCLUDED.ip, ultimo_visto=EXCLUDED.ultimo_visto
            """, (
                eq["equipo_id"], eq["nombre"], eq["os"], eq["os_version"],
                eq["os_release"], eq["arquitectura"], eq["ip"], eq["ultimo_visto"]
            ))


def _sync_tabla(pg_conn, tabla: str, sql_template: str, row_fn) -> int:
    """
    Sincroniza una tabla completa en batches.
    Retorna total de filas sincronizadas.
    """
    total = 0
    while True:
        filas = db.obtener_no_sync(tabla, config.PG_BATCH_SIZE)
        if not filas:
            break

        valores = [row_fn(r) for r in filas]
        with pg_conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql_template, valores, page_size=200)

        ids = [r["id"] for r in filas]
        db.marcar_pg_sync(tabla, ids)
        total += len(ids)
        logger.debug("Batch sync %s: %d filas", tabla, len(ids))

        if len(filas) < config.PG_BATCH_SIZE:
            break   # no hay más pendientes

    return total


# ------------------------------------------------------------------ #
#  Hilo de fondo                                                     #
# ------------------------------------------------------------------ #

_hilo_sync: threading.Thread | None = None
_stop_event = threading.Event()


def iniciar_hilo_sync():
    """Inicia el hilo daemon de sincronización periódica."""
    global _hilo_sync
    if not _PG_DISPONIBLE or not config.PG_HABILITADO:
        logger.info("Sync a PostgreSQL deshabilitado")
        return

    inicializar_pg()

    def _loop():
        # Primera sync 60 seg después de arrancar (dar tiempo al hub de iniciar)
        time.sleep(60)
        while not _stop_event.is_set():
            sincronizar()
            intervalo = config.PG_SYNC_INTERVALO_HORAS * 3600
            _stop_event.wait(timeout=intervalo)

    _hilo_sync = threading.Thread(target=_loop, name="pg-sync", daemon=True)
    _hilo_sync.start()
    logger.info(
        "Hilo de sync iniciado — intervalo: %.1f horas",
        config.PG_SYNC_INTERVALO_HORAS
    )


def detener_hilo_sync():
    _stop_event.set()
