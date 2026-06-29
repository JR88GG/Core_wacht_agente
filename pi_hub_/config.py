# ============================================================
#  SysWatch Hub — Configuración (Raspberry Pi Zero 2W)
# ============================================================

import os
_BASE = os.path.dirname(os.path.abspath(__file__))

DB_PATH  = os.path.join(_BASE, "data", "hub.db")
LOG_PATH = os.path.join(_BASE, "data", "hub.log")
# --- Servidor ---
HOST        = os.environ.get("SYSWATCH_HOST", "0.0.0.0")
PORT        = int(os.environ.get("SYSWATCH_PORT", "8000"))
API_KEY     = os.environ.get("SYSWATCH_API_KEY", "clave-secreta-cambiar")

# --- SQLite local (caché caliente) ---
DB_RETENER_HORAS    = 48
DB_MAX_ROWS_METRICA = 50_000

# --- PostgreSQL online ---
PG_DSN = os.environ.get(
    "SYSWATCH_PG_DSN",
    "postgresql://postgres:iNSyNVaVGzsXUQMvFfPzvCrwPNzoplCN@zephyr.proxy.rlwy.net:53868/railway"   
    # Neon:     "postgresql://user:pass@ep-xxx.neon.tech/syswatch?sslmode=require"
    # Supabase: "postgresql://postgres:pass@db.xxx.supabase.co:5432/postgres"
)
PG_HABILITADO           = os.environ.get("SYSWATCH_PG_ON", "true").lower() == "true"
PG_SYNC_INTERVALO_HORAS = float(os.environ.get("SYSWATCH_PG_SYNC_H", "2"))
PG_BATCH_SIZE           = 500
PG_TIMEOUT_SEG          = 15

# --- Logging ---
LOG_LEVEL = os.environ.get("SYSWATCH_LOG", "INFO")

# --- CORS ---
CORS_ORIGINS = os.environ.get("SYSWATCH_CORS", "*").split(",")

