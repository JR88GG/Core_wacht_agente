# ============================================================
#  SysWatch Hub — Base de datos local SQLite
#  Cache caliente: datos recientes + cola sync a PostgreSQL
# ============================================================

import sqlite3
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager

import config

logger = logging.getLogger("syswatch.hub.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
    conn.execute("PRAGMA temp_store=MEMORY")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def inicializar():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS equipos (
                equipo_id    TEXT PRIMARY KEY,
                nombre       TEXT,
                os           TEXT,
                os_version   TEXT,
                os_release   TEXT,
                arquitectura TEXT,
                ip           TEXT,
                ultimo_visto TEXT,
                activo       INTEGER DEFAULT 1,
                pg_sync      INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS metricas (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                equipo_id      TEXT NOT NULL,
                timestamp      TEXT NOT NULL,
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
                recibido_en    TEXT DEFAULT (datetime('now')),
                pg_sync        INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS procesos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                equipo_id     TEXT NOT NULL,
                timestamp     TEXT NOT NULL,
                nombre        TEXT,
                pid           INTEGER,
                cpu_pct       REAL,
                ram_mb        REAL,
                es_sospechoso INTEGER DEFAULT 0,
                recibido_en   TEXT DEFAULT (datetime('now')),
                pg_sync       INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS alertas (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                equipo_id    TEXT NOT NULL,
                timestamp    TEXT NOT NULL,
                tipo         TEXT,
                severidad    TEXT,
                descripcion  TEXT,
                valor_actual REAL,
                valor_umbral REAL,
                resuelta     INTEGER DEFAULT 0,
                recibido_en  TEXT DEFAULT (datetime('now')),
                pg_sync      INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_m_equipo_ts ON metricas(equipo_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_m_pgsync    ON metricas(pg_sync, recibido_en);
            CREATE INDEX IF NOT EXISTS idx_a_pgsync    ON alertas(pg_sync);
            CREATE INDEX IF NOT EXISTS idx_p_pgsync    ON procesos(pg_sync);
            CREATE INDEX IF NOT EXISTS idx_a_equipo    ON alertas(equipo_id, timestamp DESC);
        """)
    logger.info("SQLite hub inicializada: %s", config.DB_PATH)


# --- Escritura ---

def upsert_equipo(datos: dict, ip: str = None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO equipos (equipo_id, nombre, os, os_version, os_release,
                                 arquitectura, ip, ultimo_visto)
            VALUES (:equipo_id, :nombre, :os, :os_version, :os_release,
                    :arquitectura, :ip, :ultimo_visto)
            ON CONFLICT(equipo_id) DO UPDATE SET
                nombre=excluded.nombre, os=excluded.os, os_version=excluded.os_version,
                ip=excluded.ip, ultimo_visto=excluded.ultimo_visto, activo=1
        """, {**datos, "ip": ip, "ultimo_visto": datetime.utcnow().isoformat()})


def insertar_metrica(datos: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO metricas (
                equipo_id, timestamp, cpu_pct, cpu_freq_mhz,
                ram_usada_mb, ram_total_mb, ram_pct,
                disco_usado_gb, disco_total_gb, disco_pct,
                temp_cpu, uptime_horas, total_procesos
            ) VALUES (
                :equipo_id, :timestamp, :cpu_pct, :cpu_freq_mhz,
                :ram_usada_mb, :ram_total_mb, :ram_pct,
                :disco_usado_gb, :disco_total_gb, :disco_pct,
                :temp_cpu, :uptime_horas, :total_procesos
            )
        """, datos)


def insertar_metricas_batch(lista: list):
    if not lista:
        return
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO metricas (
                equipo_id, timestamp, cpu_pct, cpu_freq_mhz,
                ram_usada_mb, ram_total_mb, ram_pct,
                disco_usado_gb, disco_total_gb, disco_pct,
                temp_cpu, uptime_horas, total_procesos
            ) VALUES (
                :equipo_id, :timestamp, :cpu_pct, :cpu_freq_mhz,
                :ram_usada_mb, :ram_total_mb, :ram_pct,
                :disco_usado_gb, :disco_total_gb, :disco_pct,
                :temp_cpu, :uptime_horas, :total_procesos
            )
        """, lista)


def insertar_alertas_batch(lista: list):
    if not lista:
        return
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO alertas (
                equipo_id, timestamp, tipo, severidad,
                descripcion, valor_actual, valor_umbral
            ) VALUES (
                :equipo_id, :timestamp, :tipo, :severidad,
                :descripcion, :valor_actual, :valor_umbral
            )
        """, lista)


def insertar_procesos_batch(lista: list):
    if not lista:
        return
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO procesos (
                equipo_id, timestamp, nombre, pid,
                cpu_pct, ram_mb, es_sospechoso
            ) VALUES (
                :equipo_id, :timestamp, :nombre, :pid,
                :cpu_pct, :ram_mb, :es_sospechoso
            )
        """, lista)


# --- Lectura para el portal ---

def obtener_equipos() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM equipos ORDER BY ultimo_visto DESC"
        ).fetchall()]


def obtener_metricas_recientes(equipo_id: str, limite: int = 60) -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT * FROM metricas WHERE equipo_id=?
            ORDER BY timestamp DESC LIMIT ?
        """, (equipo_id, limite)).fetchall()]


def obtener_alertas_activas(equipo_id: str = None, limite: int = 50) -> list:
    with get_conn() as conn:
        if equipo_id:
            rows = conn.execute("""
                SELECT a.*, e.nombre as equipo_nombre FROM alertas a
                JOIN equipos e USING(equipo_id)
                WHERE a.equipo_id=? AND a.resuelta=0
                ORDER BY a.timestamp DESC LIMIT ?
            """, (equipo_id, limite)).fetchall()
        else:
            rows = conn.execute("""
                SELECT a.*, e.nombre as equipo_nombre FROM alertas a
                JOIN equipos e USING(equipo_id)
                WHERE a.resuelta=0
                ORDER BY a.timestamp DESC LIMIT ?
            """, (limite,)).fetchall()
        return [dict(r) for r in rows]


def dashboard_resumen() -> list:
    """Una fila por equipo con su última métrica. Para el panel principal."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT e.equipo_id, e.nombre, e.os, e.ip, e.ultimo_visto,
                   m.cpu_pct, m.ram_pct, m.disco_pct, m.temp_cpu,
                   m.uptime_horas, m.total_procesos, m.timestamp as metrica_ts,
                   (SELECT COUNT(*) FROM alertas a
                    WHERE a.equipo_id=e.equipo_id AND a.resuelta=0) as alertas_activas
            FROM equipos e
            LEFT JOIN metricas m ON m.id = (
                SELECT id FROM metricas WHERE equipo_id=e.equipo_id
                ORDER BY timestamp DESC LIMIT 1
            )
            ORDER BY e.ultimo_visto DESC
        """).fetchall()]


def resolver_alerta(alerta_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE alertas SET resuelta=1 WHERE id=?", (alerta_id,))


# --- Para el sync con PostgreSQL ---

def obtener_no_sync(tabla: str, limite: int) -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {tabla} WHERE pg_sync=0 ORDER BY id ASC LIMIT ?",
            (limite,)
        ).fetchall()]


def marcar_pg_sync(tabla: str, ids: list):
    if not ids:
        return
    ph = ",".join("?" * len(ids))
    with get_conn() as conn:
        conn.execute(f"UPDATE {tabla} SET pg_sync=1 WHERE id IN ({ph})", ids)


def purgar_sincronizados():
    corte = (datetime.utcnow() - timedelta(hours=config.DB_RETENER_HORAS)).isoformat()
    with get_conn() as conn:
        for tabla in ("metricas", "procesos", "alertas"):
            r = conn.execute(
                f"DELETE FROM {tabla} WHERE pg_sync=1 AND recibido_en < ?", (corte,)
            )
            if r.rowcount:
                logger.info("Purge %s: %d filas", tabla, r.rowcount)


def stats_db() -> dict:
    with get_conn() as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("equipos", "metricas", "alertas", "procesos")}
