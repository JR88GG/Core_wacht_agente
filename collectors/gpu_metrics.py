"""
collectors/gpu_metrics.py — Métricas de GPU (tabla `gpu_metricas`).

Soporte real solo para GPUs NVIDIA vía `pynvml` (funciona igual en Windows
y Linux si el driver NVIDIA está instalado). Para AMD/Intel no existe una
librería multiplataforma confiable y gratuita — se documenta como límite
conocido en vez de simular datos.
"""

_NVML_DISPONIBLE = False
try:
    import pynvml
    pynvml.nvmlInit()
    _NVML_DISPONIBLE = True
except Exception:
    _NVML_DISPONIBLE = False


def recolectar_gpu_metricas(equipo_id: str) -> list:
    """Devuelve una lista de payloads (una por GPU NVIDIA detectada)."""
    if not _NVML_DISPONIBLE:
        return []

    resultados = []
    try:
        cantidad = pynvml.nvmlDeviceGetCount()
    except Exception:
        return []

    for indice in range(cantidad):
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(indice)
            nombre = pynvml.nvmlDeviceGetName(handle)
            if isinstance(nombre, bytes):
                nombre = nombre.decode("utf-8")

            utilizacion = pynvml.nvmlDeviceGetUtilizationRates(handle)
            memoria = pynvml.nvmlDeviceGetMemoryInfo(handle)
            temperatura = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)

            try:
                consumo_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            except Exception:
                consumo_watts = None

            try:
                driver = pynvml.nvmlSystemGetDriverVersion()
                if isinstance(driver, bytes):
                    driver = driver.decode("utf-8")
            except Exception:
                driver = None

            try:
                encoder_util = pynvml.nvmlDeviceGetEncoderUtilization(handle)[0]
            except Exception:
                encoder_util = None

            try:
                decoder_util = pynvml.nvmlDeviceGetDecoderUtilization(handle)[0]
            except Exception:
                decoder_util = None

            resultados.append({
                "equipo_id": equipo_id,
                "uso_gpu": float(utilizacion.gpu),
                "temperatura": float(temperatura),
                "memoria_usada_mb": round(memoria.used / (1024 ** 2)),
                "memoria_total_mb": round(memoria.total / (1024 ** 2)),
                "encoder": float(encoder_util) if encoder_util is not None else None,
                "decoder": float(decoder_util) if decoder_util is not None else None,
                "consumo_watts": consumo_watts,
                "modelo": nombre,
                "fabricante": "NVIDIA",
                "driver_gpu": driver,
            })
        except Exception:
            continue

    return resultados
