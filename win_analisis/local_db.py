# ============================================================
#  SysWatch Agent — Base de datos local (SQLite)
#  Maneja el buffer offline y la cola de envío pendiente
# ============================================================

import sqlite3
import logging
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

import config

logger = logging.getLogger("syswatch.db")


@contextmanager
def get_conn():
    """Context manager para conexiones SQLite seguras."""
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # escrituras concurrentes seguras
    conn.execute("PRAGMA synchronous=NORMAL") # balance velocidad/seguridad
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def inicializar():
    """Crea las tablas si no existen. Llamar al inicio del agente."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS equipo_info (
                clave   TEXT PRIMARY KEY,
                valor   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metricas (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                equipo_id       TEXT    NOT NULL,
                timestamp       TEXT    NOT NULL,
                cpu_pct         REAL,
                cpu_freq_mhz    REAL,
                ram_usada_mb    INTEGER,
                ram_total_mb    INTEGER,
                ram_pct         REAL,
                disco_usado_gb  REAL,
                disco_total_gb  REAL,
                disco_pct       REAL,
                temp_cpu        REAL,
                uptime_horas    REAL,
                total_procesos  INTEGER,
                enviado         INTEGER DEFAULT 0,
                creado_en       TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS procesos (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                equipo_id       TEXT    NOT NULL,
                timestamp       TEXT    NOT NULL,
                nombre          TEXT,
                pid             INTEGER,
                cpu_pct         REAL,
                ram_mb          REAL,
                es_sospechoso   INTEGER DEFAULT 0,
                enviado         INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS alertas (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                equipo_id       TEXT    NOT NULL,
                timestamp       TEXT    NOT NULL,
                tipo            TEXT,
                severidad       TEXT,
                descripcion     TEXT,
                valor_actual    REAL,
                valor_umbral    REAL,
                enviado         INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_metricas_enviado
                ON metricas(enviado, creado_en);

            CREATE INDEX IF NOT EXISTS idx_alertas_enviado
                ON alertas(enviado);
        """)
    logger.info("Base de datos local inicializada: %s", config.DB_PATH)

    # Guardar ID del equipo si no existe aún
    guardar_equipo_id()


def guardar_equipo_id():
    """Persiste el ID del equipo para que sea consistente entre reinicios."""
    with get_conn() as conn:
        existente = conn.execute(
            "SELECT valor FROM equipo_info WHERE clave='equipo_id'"
        ).fetchone()
        if not existente:
            conn.execute(
                "INSERT INTO equipo_info(clave, valor) VALUES('equipo_id', ?)",
                (config.EQUIPO_ID,)
            )
        else:
            # Usar el ID ya guardado (sobrescribe la config para ser consistente)
            config.EQUIPO_ID = existente["valor"]


def insertar_metrica(datos: dict) -> int:
    """Inserta una fila de métricas. Retorna el ID insertado."""
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO metricas (
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
        return cur.lastrowid


def insertar_procesos(lista: list[dict]):
    """Inserta snapshot de procesos top."""
    if not lista:
        return
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO procesos (
                equipo_id, timestamp, nombre, pid,
                cpu_pct, ram_mb, es_sospechoso
            ) VALUES (
                :equipo_id, :timestamp, :nombre, :pid,
                :cpu_pct, :ram_mb, :es_sospechoso
            )
        """, lista)


def insertar_alerta(datos: dict):
    """Inserta una alerta generada por el detector de anomalías."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO alertas (
                equipo_id, timestamp, tipo, severidad,
                descripcion, valor_actual, valor_umbral
            ) VALUES (
                :equipo_id, :timestamp, :tipo, :severidad,
                :descripcion, :valor_actual, :valor_umbral
            )
        """, datos)


def obtener_pendientes_metricas(limite: int = 200) -> list[dict]:
    """Retorna métricas no enviadas al hub, ordenadas cronológicamente."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM metricas
            WHERE enviado = 0
            ORDER BY creado_en ASC
            LIMIT ?
        """, (limite,)).fetchall()
        return [dict(r) for r in rows]


def obtener_pendientes_alertas(limite: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM alertas
            WHERE enviado = 0
            ORDER BY timestamp ASC
            LIMIT ?
        """, (limite,)).fetchall()
        return [dict(r) for r in rows]


def obtener_pendientes_procesos(limite: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM procesos
            WHERE enviado = 0
            ORDER BY timestamp ASC
            LIMIT ?
        """, (limite,)).fetchall()
        return [dict(r) for r in rows]


def marcar_enviados(tabla: str, ids: list[int]):
    """Marca registros como enviados exitosamente al hub."""
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    with get_conn() as conn:
        conn.execute(
            f"UPDATE {tabla} SET enviado=1 WHERE id IN ({placeholders})",
            ids
        )


def limpiar_antiguos():
    """Elimina registros ya enviados más viejos que la retención configurada."""
    corte = (
        datetime.now() - timedelta(hours=config.DB_RETENER_HORAS)
    ).isoformat()

    with get_conn() as conn:
        for tabla in ("metricas", "procesos", "alertas"):
            result = conn.execute(
                f"DELETE FROM {tabla} WHERE enviado=1 AND creado_en < ?",
                (corte,)
            )
            if result.rowcount:
                logger.info("Limpieza %s: %d registros eliminados", tabla, result.rowcount)


def contar_pendientes() -> dict:
    """Retorna cuántos registros hay pendientes de envío."""
    with get_conn() as conn:
        return {
            "metricas":  conn.execute("SELECT COUNT(*) FROM metricas WHERE enviado=0").fetchone()[0],
            "alertas":   conn.execute("SELECT COUNT(*) FROM alertas WHERE enviado=0").fetchone()[0],
            "procesos":  conn.execute("SELECT COUNT(*) FROM procesos WHERE enviado=0").fetchone()[0],
        }


def ultimas_metricas(n: int = 120) -> list[float]:
    """Retorna los últimos N valores de CPU para el baseline del detector."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT cpu_pct FROM metricas
            ORDER BY id DESC LIMIT ?
        """, (n,)).fetchall()
        return [r[0] for r in rows if r[0] is not None]


def historial_campo(campo: str, n: int = 120) -> list[float]:
    """Retorna historial de cualquier campo numérico de métricas."""
    campos_validos = {
        "cpu_pct", "ram_pct", "disco_pct", "temp_cpu",
        "cpu_freq_mhz", "uptime_horas"
    }
    if campo not in campos_validos:
        raise ValueError(f"Campo no permitido: {campo}")
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {campo} FROM metricas ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [r[0] for r in rows if r[0] is not None]
