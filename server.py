"""
server.py — Servidor coordinador de la LAN.

Recibe los payloads de todos los agentes (incluido el suyo propio) por
HTTP, valida la API key compartida, e inserta todo dentro de una sola
transacción ACID (ver db.with_transaction). Además corre en segundo plano
el escaneo TCP de los equipos conocidos, algo que solo tiene sentido desde
aquí (ver network_scan.py).
"""

import json
import logging
import threading
import time

from flask import Flask, request, jsonify

import db
import network_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s [server] %(message)s")
log = logging.getLogger("corewatch.server")

app = Flask(__name__)

_config = {}


# ======================================================
# INSERCIÓN TRANSACCIONAL DE UN PAYLOAD DE AGENTE
# ======================================================

def _clave_periferico(p: dict) -> tuple:
    """Identidad de un periférico: mismo dispositivo físico entre ciclos."""
    return (p.get("nombre"), p.get("vendor_id"), p.get("product_id"))


def _sincronizar_perifericos_usb(cur, equipo_id: str, perifericos_actuales: list):
    """
    Compara los periféricos reportados en este ciclo contra el último estado
    conocido en la BD, e inserta SOLO lo que cambió:
      - Dispositivo nuevo (no estaba conectado antes) -> insertar conectado=true
      - Dispositivo que ya no aparece (estaba conectado antes) -> insertar conectado=false
      - Dispositivo sin cambios -> no se toca, se evita crecer la tabla sin necesidad
    """
    cur.execute("""
        SELECT DISTINCT ON (nombre, vendor_id, product_id)
            nombre, vendor_id, product_id, conectado
        FROM perifericos_usb
        WHERE equipo_id = %s
        ORDER BY nombre, vendor_id, product_id, fecha DESC;
    """, (equipo_id,))
    estado_previo = {
        (fila["nombre"], fila["vendor_id"], fila["product_id"]): fila["conectado"]
        for fila in cur.fetchall()
    }

    claves_actuales = set()

    for periferico in perifericos_actuales:
        clave = _clave_periferico(periferico)
        claves_actuales.add(clave)

        estaba_conectado = estado_previo.get(clave)
        if estaba_conectado is True:
            continue  # sin cambios, no insertar de nuevo

        cur.execute("""
            INSERT INTO perifericos_usb (
                equipo_id, nombre, tipo, fabricante, vendor_id, product_id,
                serial, bus, direccion_dispositivo, ubicacion_puerto, velocidad, conectado
            ) VALUES (
                %(equipo_id)s, %(nombre)s, %(tipo)s, %(fabricante)s, %(vendor_id)s, %(product_id)s,
                %(serial)s, %(bus)s, %(direccion_dispositivo)s, %(ubicacion_puerto)s, %(velocidad)s, %(conectado)s
            );
        """, periferico)

    # Dispositivos que SÍ estaban conectados antes pero ya no aparecen -> marcar desconexión
    for clave, estaba_conectado in estado_previo.items():
        if estaba_conectado is True and clave not in claves_actuales:
            nombre, vendor_id, product_id = clave
            cur.execute("""
                INSERT INTO perifericos_usb (
                    equipo_id, nombre, vendor_id, product_id, conectado
                ) VALUES (%s, %s, %s, %s, false);
            """, (equipo_id, nombre, vendor_id, product_id))


def guardar_payload_agente(payload: dict, cliente_id: int):
    """
    Inserta todo el payload de un agente en una sola transacción.
    Si falla cualquier parte (por ejemplo, un proceso mal formado),
    se revierte TODO el payload — no quedan métricas huérfanas.
    """
    equipo = payload.get("equipo") or {}
    equipo_id = equipo.get("equipo_id")
    if not equipo_id:
        raise ValueError("El payload no incluye equipo.equipo_id")

    with db.with_transaction() as cur:
        # --- 1. Upsert de equipos ---
        cur.execute("""
            INSERT INTO equipos (
                equipo_id, cliente_id, nombre, hostname, sistema_operativo,
                os_version, os_release, arquitectura, direccion_ip,
                mac_address, ultimo_visto, activo
            ) VALUES (
                %(equipo_id)s, %(cliente_id)s, %(nombre)s, %(hostname)s, %(sistema_operativo)s,
                %(os_version)s, %(os_release)s, %(arquitectura)s, %(direccion_ip)s,
                %(mac_address)s, now(), true
            )
            ON CONFLICT (equipo_id) DO UPDATE SET
                nombre = EXCLUDED.nombre,
                hostname = EXCLUDED.hostname,
                sistema_operativo = EXCLUDED.sistema_operativo,
                os_version = EXCLUDED.os_version,
                os_release = EXCLUDED.os_release,
                arquitectura = EXCLUDED.arquitectura,
                direccion_ip = EXCLUDED.direccion_ip,
                mac_address = EXCLUDED.mac_address,
                ultimo_visto = now(),
                activo = true;
        """, {**equipo, "cliente_id": cliente_id})

        # --- 2. Métricas generales ---
        metricas = payload.get("metricas")
        if metricas:
            cur.execute("""
                INSERT INTO metricas (
                    equipo_id, cpu_pct, cpu_freq_mhz, ram_usada_mb, ram_total_mb,
                    ram_pct, disco_usado_gb, disco_total_gb, disco_pct,
                    temp_cpu, uptime_horas, total_procesos
                ) VALUES (
                    %(equipo_id)s, %(cpu_pct)s, %(cpu_freq_mhz)s, %(ram_usada_mb)s, %(ram_total_mb)s,
                    %(ram_pct)s, %(disco_usado_gb)s, %(disco_total_gb)s, %(disco_pct)s,
                    %(temp_cpu)s, %(uptime_horas)s, %(total_procesos)s
                );
            """, metricas)

        # --- 3. GPU ---
        for gpu in payload.get("gpu_metricas") or []:
            cur.execute("""
                INSERT INTO gpu_metricas (
                    equipo_id, uso_gpu, temperatura, memoria_usada_mb, memoria_total_mb,
                    encoder, decoder, consumo_watts, modelo, fabricante, driver_gpu
                ) VALUES (
                    %(equipo_id)s, %(uso_gpu)s, %(temperatura)s, %(memoria_usada_mb)s, %(memoria_total_mb)s,
                    %(encoder)s, %(decoder)s, %(consumo_watts)s, %(modelo)s, %(fabricante)s, %(driver_gpu)s
                );
            """, gpu)

        # --- 4. Discos ---
        for disco in payload.get("discos") or []:
            cur.execute("""
                INSERT INTO discos (
                    equipo_id, nombre, tipo, capacidad_gb, espacio_libre_gb,
                    porcentaje_usado, temperatura, serial, estado_smart, vida_util
                ) VALUES (
                    %(equipo_id)s, %(nombre)s, %(tipo)s, %(capacidad_gb)s, %(espacio_libre_gb)s,
                    %(porcentaje_usado)s, %(temperatura)s, %(serial)s, %(estado_smart)s, %(vida_util)s
                );
            """, disco)

        # --- 5. Procesos (justo el caso del enunciado: si esto falla, todo se revierte) ---
        for proceso in payload.get("procesos") or []:
            cur.execute("""
                INSERT INTO procesos (
                    equipo_id, nombre, pid, cpu_pct, ram_mb, es_sospechoso
                ) VALUES (
                    %(equipo_id)s, %(nombre)s, %(pid)s, %(cpu_pct)s, %(ram_mb)s, %(es_sospechoso)s
                );
            """, proceso)

        # --- 6. Interfaces de red ---
        for interfaz in payload.get("interfaces_red") or []:
            cur.execute("""
                INSERT INTO interfaces_red (
                    equipo_id, nombre, mac, ip, gateway, dns, velocidad, estado
                ) VALUES (
                    %(equipo_id)s, %(nombre)s, %(mac)s, %(ip)s, %(gateway)s, %(dns)s, %(velocidad)s, %(estado)s
                );
            """, interfaz)

        # --- 7. Puertos abiertos ---
        for puerto in payload.get("puertos_abiertos") or []:
            cur.execute("""
                INSERT INTO puertos_abiertos (
                    equipo_id, puerto, protocolo, servicio, estado, proceso, pid
                ) VALUES (
                    %(equipo_id)s, %(puerto)s, %(protocolo)s, %(servicio)s, %(estado)s, %(proceso)s, %(pid)s
                );
            """, puerto)

        # --- 8. Periféricos USB (solo se inserta si algo CAMBIÓ, no en cada ciclo) ---
        perifericos_actuales = payload.get("perifericos_usb") or []
        _sincronizar_perifericos_usb(cur, equipo_id, perifericos_actuales)

        # --- 9. Hardware ---
        hw = payload.get("hardware")
        if hw:
            cur.execute("""
                INSERT INTO hardware (
                    equipo_id, cpu_modelo, cpu_fabricante, cpu_nucleos, cpu_hilos, cpu_socket,
                    gpu_modelo, gpu_fabricante, gpu_memoria_mb, gpu_driver,
                    placa_base, bios_version, bios_fecha, ram_tipo, ram_slots, ram_velocidad
                ) VALUES (
                    %(equipo_id)s, %(cpu_modelo)s, %(cpu_fabricante)s, %(cpu_nucleos)s, %(cpu_hilos)s, %(cpu_socket)s,
                    %(gpu_modelo)s, %(gpu_fabricante)s, %(gpu_memoria_mb)s, %(gpu_driver)s,
                    %(placa_base)s, %(bios_version)s, %(bios_fecha)s, %(ram_tipo)s, %(ram_slots)s, %(ram_velocidad)s
                );
            """, hw)

        # --- 10. Auditoría del payload crudo (tabla agent_payload) ---
        cur.execute("""
            INSERT INTO agent_payload (endpoint, device_name, payload)
            VALUES (%s, %s, %s);
        """, ("/ingest", equipo.get("hostname"), json.dumps(payload)))


# ======================================================
# ENDPOINTS HTTP
# ======================================================

def _api_key_valida() -> bool:
    return request.headers.get("X-API-Key") == _config.get("api_key")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/ingest", methods=["POST"])
def ingest():
    if not _api_key_valida():
        return jsonify({"error": "API key inválida"}), 401

    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"error": "Payload JSON inválido o vacío"}), 400

    try:
        guardar_payload_agente(payload, _config["cliente_id"])
        return jsonify({"success": True}), 200
    except Exception as error:
        log.error("Error guardando payload: %s", error)
        return jsonify({"success": False, "error": str(error)}), 500


# ======================================================
# ESCANEO DE RED EN SEGUNDO PLANO
# ======================================================

def _obtener_equipos_del_cliente(cliente_id: int) -> list:
    with db.solo_lectura() as cur:
        cur.execute("""
            SELECT equipo_id, hostname, direccion_ip::text AS direccion_ip
            FROM equipos
            WHERE cliente_id = %s AND direccion_ip IS NOT NULL;
        """, (cliente_id,))
        return cur.fetchall()


def _guardar_resultado_escaneo(resultado_escaneo: dict, cliente_id: int):
    resumen = resultado_escaneo["resumen"]
    with db.with_transaction() as cur:
        cur.execute("""
            INSERT INTO network_scans (equipo_id, subnet, online, offline, payload)
            VALUES (NULL, %s, %s, %s, %s)
            RETURNING id;
        """, (
            f"cliente-{cliente_id}",
            resumen["online"], resumen["offline"],
            json.dumps(resultado_escaneo),
        ))
        scan_id = cur.fetchone()["id"]

        for resultado in resultado_escaneo["resultados"]:
            cur.execute("""
                INSERT INTO network_scan_hosts (scan_id, ip, hostname, online, latency_ms)
                VALUES (%s, %s, %s, %s, %s);
            """, (
                scan_id, resultado["ip"], resultado["hostname"],
                resultado["online"], resultado["latency_ms"],
            ))


def _bucle_escaneo_red(cliente_id: int, intervalo_segundos: int):
    while True:
        try:
            equipos = _obtener_equipos_del_cliente(cliente_id)
            if equipos:
                resultado = network_scan.escanear_equipos(equipos)
                _guardar_resultado_escaneo(resultado, cliente_id)
                log.info(
                    "Escaneo de red completado: %s online / %s offline",
                    resultado["resumen"]["online"], resultado["resumen"]["offline"],
                )
        except Exception as error:
            log.error("Error en el escaneo de red: %s", error)

        time.sleep(intervalo_segundos)


# ======================================================
# PUNTO DE ENTRADA DEL SERVIDOR
# ======================================================

def iniciar_servidor(config: dict):
    global _config
    _config = config

    db.inicializar_pool(config["db_url"])

    hilo_escaneo = threading.Thread(
        target=_bucle_escaneo_red,
        args=(config["cliente_id"], config.get("intervalo_escaneo_red_segundos", 300)),
        daemon=True,
    )
    hilo_escaneo.start()

    log.info("Servidor CoreWatch escuchando en el puerto %s", config["puerto"])
    app.run(host="0.0.0.0", port=config["puerto"], threaded=True)
