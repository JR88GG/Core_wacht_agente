## ⚡ Escalabilidad (pensando en 10-20+ equipos)

- **Inserciones en lote:** las tablas con listas (`gpu_metricas`, `discos`, `procesos`, `interfaces_red`, `puertos_abiertos`, `perifericos_usb`) pasaron de un `INSERT` por fila a una sola consulta por tabla con `execute_values`; de ~40 consultas por payload a ~11, sin importar cuántos procesos/dispositivos traiga.
- **Pool de conexiones:** subido de 10 a 30 (configurable vía `db_pool_maxconn` en `config.json`), para soportar más agentes reportando en simultáneo.
- **Limpieza/retención automática:** nuevo hilo en segundo plano que corre una vez al día y borra filas más viejas que su período de retención (`agent_payload`: 7 días, `procesos`: 14 días, el resto: 30 días, todos ajustables individualmente vía `config.json`). También limpia filas huérfanas en `network_scan_hosts`.
- **Índices en tablas de series de tiempo** (`indices_series_tiempo.sql`, para correr aparte contra Railway): `(equipo_id, timestamp/fecha DESC)` en `metricas`, `gpu_metricas`, `discos`, `procesos`, `interfaces_red`, `puertos_abiertos`, `perifericos_usb`, `alertas`; más índices de apoyo en `network_scans` y `agent_payload` para la limpieza y el filtro por cliente.

---

# 📦 Archivos entregados en esta etapa

| Archivo | Contenido |
|---------|-----------|
| `corewatch_agent.zip` | Proyecto completo del agente/servidor Python |
| `agregar_clientes_usuarios.sql` | Alta de Jimmy, Wilfredo, Herber, Jason + usuarios ADMIN |
| `indices_series_tiempo.sql` | Índices de rendimiento para las tablas de series de tiempo |
| `migracion_network_scans_equipo_id.sql` | Corrección histórica de `network_scans.equipo_id` (ya reflejada en `base.sql`) |

---

# 📌 Pendientes conocidos (sin implementar todavía)

- Servidor de producción real para Flask (hoy usa el servidor de desarrollo de Werkzeug; funcional a esta escala, no ideal a largo plazo).
- Empaquetado del agente como ejecutable (`.exe`/binario) para no depender de tener Python instalado en cada máquina.
- Cola de reintentos en el agente si el servidor no responde (hoy, ese ciclo de datos simplemente se pierde).
- Cifrado HTTPS entre agente y servidor (hoy es HTTP plano dentro de la LAN).
- Endpoint para que los usuarios nuevos (Jimmy, Wilfredo, etc.) cambien su contraseña temporal.
