# ============================================================
#  SysWatch Agent — Configuración
#  Editar este archivo antes de desplegar en cada equipo
# ============================================================


import os

# --- Identidad del equipo ---
EQUIPO_ID   = "LAPTOP-008"   # Se coloca manualemnte
EQUIPO_NOMBRE = os.environ.get("SYSWATCH_NOMBRE", "HERBER88-PC01")

# --- Conexión al Hub (Raspberry Pi) ---
HUB_HOST    = os.environ.get("SYSWATCH_HUB_HOST", "pi88.local")#192.168.1.7
HUB_PORT    = int(os.environ.get("SYSWATCH_HUB_PORT", "8000"))
HUB_URL     = f"http://{HUB_HOST}:{HUB_PORT}"
HUB_API_KEY = os.environ.get("SYSWATCH_API_KEY", "clave-secreta-cambiar")

# --- Intervalos de tiempo ---
INTERVALO_RECOLECCION_SEG = 30     # cada cuánto recolecta métricas
INTERVALO_ENVIO_SEG       = 30     # cada cuánto intenta enviar al hub
INTERVALO_LIMPIEZA_HORAS  = 24    # cada cuánto limpia registros viejos enviados

# --- Base de datos local (SQLite) ---
_BASE   = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SYSWATCH_DB", os.path.join(_BASE, "syswatch_local.db"))
DB_RETENER_HORAS      = 168       # guardar máx 7 días localmente
DB_MAX_PENDIENTES     = 5000      # máx registros pendientes antes de alertar

# --- Detección de anomalías ---
ANOMALIA_VENTANA      = 60        # cuántos registros para calcular baseline
ANOMALIA_Z_UMBRAL     = 2.8       # z-score para considerar anomalía
TEMP_CRITICA_CPU      = 85.0      # °C
TEMP_WARNING_CPU      = 75.0      # °C
RAM_WARNING_PCT       = 85.0      # %
RAM_CRITICA_PCT       = 95.0      # %
DISCO_WARNING_PCT     = 80.0      # %
DISCO_CRITICO_PCT     = 90.0      # %
CPU_WARNING_PCT       = 85.0      # % sostenido
CPU_CRITICO_PCT       = 95.0      # %

# --- Procesos sospechosos (lista negra base) ---
PROCESOS_LISTA_NEGRA = {
    "cryptominer.exe", "xmrig.exe", "minerd.exe",
    "netcat.exe", "nc.exe", "mimikatz.exe",
    "pwdump.exe", "fgdump.exe", "wce.exe",
}

# --- Logging ---
LOG_PATH    = "syswatch_agent.log"
LOG_LEVEL   = "INFO"    # DEBUG, INFO, WARNING, ERROR
