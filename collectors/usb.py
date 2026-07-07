"""
collectors/usb.py — Periféricos USB conectados (tabla `perifericos_usb`).

Windows y Linux exponen esta información de formas completamente distintas,
así que hay dos implementaciones separadas.
"""

import platform

PALABRAS_INFRAESTRUCTURA = (
    "hub", "concentrador", "controladora de host", "host controller",
    "root", "raíz", "generic usb hub",
)


def _es_infraestructura_usb(nombre: str, fabricante: str = None) -> bool:
    """True si el 'dispositivo' es en realidad un hub/controladora, no un periférico real."""
    texto = f"{nombre or ''} {fabricante or ''}".lower()
    return any(palabra in texto for palabra in PALABRAS_INFRAESTRUCTURA)


def _recolectar_usb_windows(equipo_id: str) -> list:
    resultados = []
    try:
        import wmi  # requiere pywin32 + WMI, solo se importa en Windows
        conexion = wmi.WMI()
        for dispositivo in conexion.Win32_PnPEntity():
            if not dispositivo.DeviceID or "USB" not in dispositivo.DeviceID:
                continue

            vendor_id = None
            product_id = None
            # DeviceID típico: USB\VID_046D&PID_C52B\...
            partes = dispositivo.DeviceID.split("\\")
            if len(partes) > 1 and "VID_" in partes[1]:
                for segmento in partes[1].split("&"):
                    if segmento.startswith("VID_"):
                        vendor_id = segmento.replace("VID_", "")
                    elif segmento.startswith("PID_"):
                        product_id = segmento.replace("PID_", "")

            nombre_dispositivo = dispositivo.Name or "Dispositivo USB desconocido"
            if _es_infraestructura_usb(nombre_dispositivo, dispositivo.Manufacturer):
                continue

            resultados.append({
                "equipo_id": equipo_id,
                "nombre": nombre_dispositivo,
                "tipo": dispositivo.PNPClass,
                "fabricante": dispositivo.Manufacturer,
                "vendor_id": vendor_id,
                "product_id": product_id,
                "serial": None,
                "bus": None,
                "direccion_dispositivo": None,
                "ubicacion_puerto": None,
                "velocidad": None,
                "conectado": dispositivo.Status == "OK",
            })
    except Exception:
        # WMI no disponible / permisos insuficientes / no es Windows real
        return []

    return resultados


def _recolectar_usb_linux(equipo_id: str) -> list:
    """
    Lee /sys/bus/usb/devices directamente, sin depender de pyusb (que
    requiere libusb instalado) ni de permisos elevados para lo básico.
    """
    import os

    resultados = []
    base = "/sys/bus/usb/devices"

    if not os.path.isdir(base):
        return resultados

    for entrada in os.listdir(base):
        ruta = os.path.join(base, entrada)

        def _leer(archivo):
            try:
                with open(os.path.join(ruta, archivo), "r") as f:
                    return f.read().strip()
            except Exception:
                return None

        vendor_id = _leer("idVendor")
        product_id = _leer("idProduct")
        if not vendor_id or not product_id:
            continue  # es un hub o entrada intermedia, no un dispositivo final

        # "1d6b" es el vendor_id reservado para hubs raíz virtuales del kernel
        # Linux ("Linux Foundation") — no es un periférico real conectado.
        if vendor_id.lower() == "1d6b":
            continue

        nombre = _leer("product") or "Dispositivo USB desconocido"
        fabricante = _leer("manufacturer")
        if _es_infraestructura_usb(nombre, fabricante):
            continue

        serial = _leer("serial")
        velocidad = _leer("speed")

        try:
            bus = int(_leer("busnum") or 0)
            direccion = int(_leer("devnum") or 0)
        except ValueError:
            bus, direccion = None, None

        resultados.append({
            "equipo_id": equipo_id,
            "nombre": nombre,
            "tipo": None,
            "fabricante": fabricante,
            "vendor_id": vendor_id,
            "product_id": product_id,
            "serial": serial,
            "bus": bus,
            "direccion_dispositivo": direccion,
            "ubicacion_puerto": entrada,
            "velocidad": velocidad,
            "conectado": True,
        })

    return resultados


def recolectar_perifericos_usb(equipo_id: str) -> list:
    sistema = platform.system().lower()
    if sistema == "windows":
        return _recolectar_usb_windows(equipo_id)
    if sistema == "linux":
        return _recolectar_usb_linux(equipo_id)
    return []
