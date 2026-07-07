# CoreWatch Agent

Agente multiplataforma (Windows + Linux) para el sistema de monitoreo CoreWatch.

## ¿Qué hace?

- **Modo agente**: recolecta datos de la máquina donde corre (CPU, RAM, disco,
  procesos, red, GPU, USB, hardware) y los envía al servidor coordinador de la LAN.
- **Modo servidor**: además de recolectar sus propios datos (igual que un agente),
  recibe los datos de todos los demás agentes de la red, los inserta en PostgreSQL
  (Railway) de forma transaccional, y ejecuta el escaneo TCP periódico de los
  equipos conocidos.

---

## Guía de instalación

### 1. Requisitos previos

- **Python 3.12** (recomendado) o 3.11. Descárgalo de
  [python.org/downloads/windows](https://www.python.org/downloads/windows/) —
  en Windows, marca la casilla **"Add python.exe to PATH"** durante la instalación.
- Verifica que quedó instalado:
  ```bash
  python --version
  ```

### 2. Descomprime el proyecto

Descomprime el `.zip` en la ubicación que prefieras (por ejemplo
`C:\CoreWatch\corewatch_agent` en Windows, o `~/corewatch_agent` en Linux).
Confirma que `main.py`, `requirements.txt` y la carpeta `collectors/` estén
todos en el mismo nivel — si tu gestor de archivos creó una carpeta duplicada
al descomprimir, entra un nivel más hasta encontrarlos juntos.

### 3. Instala las dependencias

Desde una terminal, dentro de la carpeta del proyecto:

```bash
pip install -r requirements.txt
```

Dependiendo del rol y del hardware de esta máquina, instala también:

```bash
# Solo en Windows — necesario para leer hardware y periféricos USB vía WMI:
pip install pywin32 wmi

# Solo si esta máquina tiene GPU NVIDIA dedicada:
pip install nvidia-ml-py
```

### 4. Primer arranque

```bash
python main.py
```

La primera vez te va a preguntar el rol de esta máquina:

- **Servidor** (una sola vez por red/oficina — es el coordinador de la LAN):
  te pedirá la `DATABASE_URL` de PostgreSQL (Railway), el `cliente_id`
  **(debe existir ya en la tabla `clientes` de tu base de datos, o el ingreso
  fallará con un error de foreign key)**, una API key (la misma que usarán
  todos los agentes de este cliente), el puerto donde escuchará (por defecto
  `5000`), y los intervalos de recolección/escaneo.
- **Agente** (para cada PC adicional que quieras monitorear): te pedirá la
  URL del servidor de esta red (ej: `http://192.168.1.10:5000`) y la API key
  que te dio quien configuró el servidor.

La configuración se guarda en `~/.corewatch/config.json` — las siguientes
veces que ejecutes `python main.py`, ya no te preguntará nada, arrancará
directo con lo guardado.

Para reconfigurar una máquina desde cero, borra ese archivo y vuelve a correr
`main.py`.

### 5. Correr como servicio (para que no dependa de una terminal abierta)

**Linux (systemd)** — crea `/etc/systemd/system/corewatch-agent.service`:

```ini
[Unit]
Description=CoreWatch Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /ruta/a/corewatch_agent/main.py
Restart=always
User=tu_usuario

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now corewatch-agent
```

**Windows (Programador de tareas)**:

1. Abre el "Programador de tareas".
2. Crea una tarea nueva → Desencadenador: "Al iniciar sesión" (o "Al iniciar el equipo").
3. Acción: iniciar programa → `python.exe`, con argumento la ruta completa a `main.py`.
4. Marca "Ejecutar tanto si el usuario inició sesión como si no", si aplica.

(Para producción real conviene empaquetar con `pyinstaller` y correrlo como
servicio real de Windows con `nssm` o `pywin32` — no incluido en este proyecto,
ver sección de pendientes más abajo.)

### 6. Verificación rápida

En la máquina servidor, revisa que el endpoint de salud responda:
```bash
curl http://localhost:5000/health
```
Debería devolver `{"status": "ok"}`. Si tienes acceso a la base de datos,
confirma que tu equipo aparece:
```sql
SELECT equipo_id, nombre, hostname, ultimo_visto FROM equipos;
```

---

## Estructura del proyecto

```
corewatch_agent/
├── main.py              # Punto de entrada
├── config.py            # Asistente de primer arranque + persistencia
├── agent_client.py       # Bucle de recolección + envío HTTP
├── server.py             # Servidor Flask + inserción transaccional
├── db.py                 # Pool de conexiones + gestor de transacciones
├── network_scan.py       # Escaneo TCP de los equipos de la LAN
├── collectors/
│   ├── identity.py        # tabla equipos
│   ├── system_metrics.py  # tabla metricas
│   ├── gpu_metrics.py      # tabla gpu_metricas
│   ├── disks.py            # tabla discos
│   ├── processes.py        # tabla procesos
│   ├── network.py          # tablas interfaces_red y puertos_abiertos
│   ├── usb.py               # tabla perifericos_usb
│   └── hardware.py          # tabla hardware
└── requirements.txt
```

---

## Lo que el agente TODAVÍA no hace

Esta sección es una lista honesta de límites conocidos y funcionalidad
pendiente — no cosas rotas, sino trabajo futuro identificado durante el
desarrollo y las pruebas.

### Recolección de datos incompleta o best-effort

- **Temperatura de CPU en Windows**: siempre `NULL`. `psutil` no tiene forma
  confiable de leerla en Windows (sí funciona en Linux, vía sensores del
  kernel). Requeriría una librería específica por fabricante de placa base.
- **SMART de discos** (`estado_smart`, `vida_util`): solo funciona si
  `smartctl` (paquete `smartmontools`) está instalado en el sistema. Si no
  está, se guarda `NULL` en vez de inventar un valor.
- **Serial de disco**: no implementado (queda en `NULL`).
- **Gateway y DNS de interfaces de red**: no implementados (quedan en
  `NULL`) — se podrían agregar con la librería `netifaces` o parseando la
  tabla de rutas del sistema.
- **GPU**: solo tarjetas **NVIDIA**, vía `pynvml`. AMD e Intel no tienen una
  librería multiplataforma confiable y gratuita — no se reportan.
- **Hardware en Linux** (placa base, BIOS, tipo de RAM): requiere
  `dmidecode`, que casi siempre necesita privilegios root. Sin eso, queda
  en `NULL`.
- **Multi-GPU con fabricantes mixtos**: si una máquina tiene una GPU NVIDIA
  y otra integrada (Intel/AMD), solo se reporta la NVIDIA.

### Tablas que el agente no llena (son responsabilidad del backend web)

- **`alertas`, `vulnerabilidades`, `analisis_ia`**: son datos derivados/
  analizados (umbrales, diagnóstico de IA), no recolección cruda de la
  máquina — los genera la lógica de `monitoreo.js`, no el agente.
- **`red_general`**: resumen de red a nivel de `cliente_id`/subred, no por
  equipo individual — se podría calcular en el servidor a partir de los
  resultados del escaneo de red, pero hoy no se inserta.

### Escaneo de red

- **Detección "online" depende de puertos TCP específicos**, no de ping
  ICMP. Un equipo con firewall activo que bloquee los 13 puertos
  verificados aparecerá como "offline" aunque esté encendido y conectado.
  Un fallback con ping ICMP daría una detección más confiable de
  "¿está prendido?" independiente de qué servicios tenga abiertos.

### Arquitectura y operación

- **Un servidor solo admite un `cliente_id`.** Si necesitas monitorear
  varias redes/oficinas separadas del mismo cliente, hoy requeriría una
  instancia de servidor por red.
- **Sin cola de reintentos**: si el agente no logra contactar al servidor
  en un ciclo (red caída, servidor apagado), esos datos de ese ciclo se
  pierden — no se guardan localmente para reenviar después.
- **Sin empaquetado como ejecutable**: hoy se corre con `python main.py`,
  requiere Python instalado en cada máquina. Para distribución más simple
  se podría empaquetar con `PyInstaller` como `.exe`/binario standalone.
- **Sin actualización automática**: cada máquina debe actualizarse
  manualmente (reemplazar los archivos y reiniciar) cuando haya cambios.
- **Comunicación agente→servidor sin cifrar**: usa HTTP plano dentro de la
  LAN, no HTTPS. La API key viaja en texto plano dentro de la red local.
  Aceptable para una LAN confiable, pero no para redes no confiables.
- **Sin rotación de logs**: el logging va solo a consola (`stdout`), no se
  persiste en archivo ni se rota — si corre como servicio, dependes de las
  herramientas del sistema (`journalctl` en Linux, Visor de eventos /
  redirección manual en Windows) para conservar el historial.
- **Validación de `cliente_id`**: el asistente de configuración no verifica
  contra la base de datos que el `cliente_id` ingresado exista — si no
  existe, falla en el primer envío con un error de foreign key (hay que
  crearlo manualmente en `clientes` antes de configurar el servidor).
