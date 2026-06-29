# ============================================================
#  SysWatch Hub — API Principal (FastAPI)
#  Corre en la Raspberry Pi Zero 2W
#
#  Instalar dependencias:
#    pip install fastapi uvicorn[standard] psycopg2-binary
#
#  Iniciar:
#    uvicorn main:app --host 0.0.0.0 --port 8000
#
#  Como servicio (systemd):
#    ver syswatch-hub.service en este directorio
# ============================================================

import logging
import sys
from datetime import datetime
from typing import Optional
import led_status 

from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import config
import database as db
import pg_sync

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
logger = logging.getLogger("syswatch.hub")

# ------------------------------------------------------------------ #
#  App                                                               #
# ------------------------------------------------------------------ #

app = FastAPI(
    title="SysWatch Hub",
    description="Hub central de monitoreo — Raspberry Pi Zero 2W",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    logger.info("SysWatch Hub arrancando...")
    db.inicializar()
    pg_sync.iniciar_hilo_sync()
    led_status.controlador.inicializar() 
    logger.info("Hub listo en %s:%d", config.HOST, config.PORT)


@app.on_event("shutdown")
def shutdown():
    pg_sync.detener_hilo_sync()
    led_status.controlador.apagar_todo()
    logger.info("Hub detenido")


# ------------------------------------------------------------------ #
#  Autenticación por API Key                                         #
# ------------------------------------------------------------------ #

def verificar_api_key(x_api_key: str = Header(...)):
    if x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="API Key inválida")
    return x_api_key


# ------------------------------------------------------------------ #
#  Schemas Pydantic (validación de entrada)                          #
# ------------------------------------------------------------------ #

class HeartbeatSchema(BaseModel):
    equipo_id:    str
    nombre:       str
    os:           str
    os_version:   Optional[str] = None
    os_release:   Optional[str] = None
    arquitectura: Optional[str] = None
    timestamp:    Optional[str] = None


class MetricaSchema(BaseModel):
    equipo_id:      str
    timestamp:      str
    cpu_pct:        Optional[float] = None
    cpu_freq_mhz:   Optional[float] = None
    ram_usada_mb:   Optional[int]   = None
    ram_total_mb:   Optional[int]   = None
    ram_pct:        Optional[float] = None
    disco_usado_gb: Optional[float] = None
    disco_total_gb: Optional[float] = None
    disco_pct:      Optional[float] = None
    temp_cpu:       Optional[float] = None
    uptime_horas:   Optional[float] = None
    total_procesos: Optional[int]   = None


class AlertaSchema(BaseModel):
    equipo_id:    str
    timestamp:    str
    tipo:         str
    severidad:    str
    descripcion:  str
    valor_actual: Optional[float] = None
    valor_umbral: Optional[float] = None


class ProcesoSchema(BaseModel):
    equipo_id:     str
    timestamp:     str
    nombre:        Optional[str]   = None
    pid:           Optional[int]   = None
    cpu_pct:       Optional[float] = None
    ram_mb:        Optional[float] = None
    es_sospechoso: Optional[int]   = 0


# ------------------------------------------------------------------ #
#  Endpoints de salud                                                #
# ------------------------------------------------------------------ #

@app.get("/health", tags=["Sistema"])
def health():
    """Ping rápido. Los agentes lo usan para verificar conectividad."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }


@app.get("/api/status", tags=["Sistema"])
def status(_key=Depends(verificar_api_key)):
    """Estado detallado del hub: DB, sync, equipos."""
    stats = db.stats_db()
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "db_stats": stats,
        "pg_sync_habilitado": config.PG_HABILITADO,
        "pg_sync_intervalo_horas": config.PG_SYNC_INTERVALO_HORAS,
    }


# ------------------------------------------------------------------ #
#  Registro de equipos                                               #
# ------------------------------------------------------------------ #

@app.post("/api/equipos/heartbeat", status_code=200, tags=["Equipos"])
def heartbeat(payload: HeartbeatSchema, request: Request, _key=Depends(verificar_api_key)):
    """El agente llama esto al iniciar y periódicamente."""
    ip = request.client.host if request.client else None
    db.upsert_equipo(payload.dict(), ip=ip)
    logger.info("Heartbeat: %s (%s) desde %s", payload.nombre, payload.equipo_id[:8], ip)
    return {"ok": True}


@app.get("/api/equipos", tags=["Equipos"])
def listar_equipos(_key=Depends(verificar_api_key)):
    return db.obtener_equipos()


# ------------------------------------------------------------------ #
#  Recepción de métricas                                             #
# ------------------------------------------------------------------ #

@app.post("/api/metricas", status_code=201, tags=["Métricas"])
def recibir_metrica(payload: MetricaSchema, _key=Depends(verificar_api_key)):
    """Métrica individual en tiempo real."""
    db.insertar_metrica(payload.dict())
    led_status.controlador.actualizar(db.dashboard_resumen())
    return {"ok": True}


@app.post("/api/metricas/batch", status_code=201, tags=["Métricas"])
def recibir_metricas_batch(payload: list[MetricaSchema], _key=Depends(verificar_api_key)):
    """Batch de métricas acumuladas offline."""
    db.insertar_metricas_batch([p.dict() for p in payload])
    logger.info("Batch métricas recibido: %d registros", len(payload))
    return {"ok": True, "insertados": len(payload)}


@app.get("/api/metricas/{equipo_id}", tags=["Métricas"])
def obtener_metricas(equipo_id: str, limite: int = 60, _key=Depends(verificar_api_key)):
    return db.obtener_metricas_recientes(equipo_id, limite)


# ------------------------------------------------------------------ #
#  Alertas                                                           #
# ------------------------------------------------------------------ #

@app.post("/api/alertas/batch", status_code=201, tags=["Alertas"])
def recibir_alertas(payload: list[AlertaSchema], _key=Depends(verificar_api_key)):
    db.insertar_alertas_batch([p.dict() for p in payload])
    logger.warning("Alertas recibidas: %d", len(payload))
    return {"ok": True, "insertadas": len(payload)}


@app.get("/api/alertas", tags=["Alertas"])
def listar_alertas(equipo_id: Optional[str] = None, _key=Depends(verificar_api_key)):
    return db.obtener_alertas_activas(equipo_id)


@app.patch("/api/alertas/{alerta_id}/resolver", tags=["Alertas"])
def resolver_alerta(alerta_id: int, _key=Depends(verificar_api_key)):
    db.resolver_alerta(alerta_id)
    return {"ok": True}


# ------------------------------------------------------------------ #
#  Procesos                                                          #
# ------------------------------------------------------------------ #

@app.post("/api/procesos/batch", status_code=201, tags=["Procesos"])
def recibir_procesos(payload: list[ProcesoSchema], _key=Depends(verificar_api_key)):
    db.insertar_procesos_batch([p.dict() for p in payload])
    return {"ok": True, "insertados": len(payload)}


# ------------------------------------------------------------------ #
#  Dashboard — endpoint principal del portal web                    #
# ------------------------------------------------------------------ #

@app.get("/api/dashboard", tags=["Dashboard"])
def dashboard(_key=Depends(verificar_api_key)):
    """
    Resumen completo: último estado de cada equipo + alertas activas.
    El portal web llama esto cada 30 seg para actualizar el panel.
    """
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "equipos":   db.dashboard_resumen(),
        "alertas":   db.obtener_alertas_activas(limite=20),
    }


# ------------------------------------------------------------------ #
#  Forzar sync manual (para debug/demostración)                     #
# ------------------------------------------------------------------ #

@app.post("/api/sync/forzar", tags=["Sistema"])
def forzar_sync(_key=Depends(verificar_api_key)):
    """Fuerza una sincronización inmediata a PostgreSQL."""
    import threading
    t = threading.Thread(target=pg_sync.sincronizar, daemon=True)
    t.start()
    return {"ok": True, "mensaje": "Sincronización iniciada en background"}


# ------------------------------------------------------------------ #
#  Entry point directo                                               #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        log_level=config.LOG_LEVEL.lower(),
        workers=1,          # 1 worker en la Pi Zero para ahorrar RAM
        loop="asyncio",
    )
