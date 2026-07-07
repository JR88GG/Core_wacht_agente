"""
db.py — Conexión a PostgreSQL y gestor de transacciones ACID para el servidor.

Equivalente en Python de `withTransaction()` en tu database.js: abre BEGIN,
ejecuta el trabajo, hace COMMIT o ROLLBACK, y siempre libera la conexión.
"""

import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool

log = logging.getLogger("corewatch.db")

_pool: SimpleConnectionPool = None


def inicializar_pool(db_url: str, minconn=1, maxconn=10):
    global _pool
    _pool = SimpleConnectionPool(minconn, maxconn, dsn=db_url)
    log.info("Pool de conexiones a PostgreSQL inicializado.")


@contextmanager
def with_transaction():
    """
    Uso:
        with with_transaction() as cur:
            cur.execute("INSERT INTO ...")
            cur.execute("INSERT INTO ...")
        # COMMIT automático si no hubo excepciones.
        # ROLLBACK automático si algo falló, y la excepción se relanza.
    """
    conexion = _pool.getconn()
    try:
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cursor
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        _pool.putconn(conexion)


@contextmanager
def solo_lectura():
    """Para queries de SELECT que no necesitan transacción explícita."""
    conexion = _pool.getconn()
    try:
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cursor
    finally:
        _pool.putconn(conexion)
