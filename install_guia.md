
### Inicio de agente manual
PS C:\Users\ccjun\Desktop\pi88> (Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& c:\Users\ccjun\Desktop\pi88\.venv\Scripts\Activate.ps1)
cd C:\Users\ccjun\Desktop\pi88\win_analisis
& "C:\Users\ccjun\Desktop\pi88\.venv\Scripts\python.exe" agent.py
### Instalación de hub pi88

pip install -r requirements\_hub.txt

\# Editar config.py con PG\_DSN real

sudo cp syswatch-hub.service /etc/systemd/system/

sudo systemctl enable syswatch-hub

sudo systemctl start syswatch-hub

### Iniciar hub
cd /home/herber88/Desktop/pi88/pi_hub
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1

### Endpoints disponibles pi88

GET  /health                        → ping (sin auth, lo usan los agentes)
GET  /api/dashboard                 → resumen de todos los equipos
GET  /api/equipos                   → lista de equipos registrados
POST /api/equipos/heartbeat         → registro/actualización de equipo
POST /api/metricas                  → métrica individual
POST /api/metricas/batch            → batch offline acumulado
GET  /api/metricas/{equipo_id}      → historial reciente
POST /api/alertas/batch             → alertas del agente
GET  /api/alertas                   → alertas activas
POST /api/procesos/batch            → snapshot de procesos
POST /api/sync/forzar               → sync manual a PostgreSQL



### Instalación de sercicio de analisis en windows

pip install psutil requests

\# Editar config.py → poner HUB\_HOST con la IP de la Pi
w2
python agent.py

