"""
collectors/hardware.py — Especificaciones de hardware (tabla `hardware`).

Igual que con USB, Windows (WMI) y Linux (/proc, /sys) requieren caminos
distintos. BIOS/motherboard en Linux normalmente requiere `dmidecode`,
que casi siempre necesita privilegios root — se intenta y se degrada
con gracia si no está disponible.
"""

import platform
import shutil
import subprocess

import psutil


def _hardware_windows() -> dict:
    datos = {
        "cpu_modelo": None, "cpu_fabricante": None,
        "gpu_modelo": None, "gpu_fabricante": None, "gpu_memoria_mb": None, "gpu_driver": None,
        "placa_base": None, "bios_version": None, "bios_fecha": None,
        "ram_tipo": None, "ram_slots": None, "ram_velocidad": None,
    }
    try:
        import wmi
        conexion = wmi.WMI()

        procesadores = conexion.Win32_Processor()
        if procesadores:
            cpu = procesadores[0]
            datos["cpu_modelo"] = cpu.Name
            datos["cpu_fabricante"] = cpu.Manufacturer

        tarjetas = conexion.Win32_VideoController()
        if tarjetas:
            gpu = tarjetas[0]
            datos["gpu_modelo"] = gpu.Name
            datos["gpu_fabricante"] = gpu.AdapterCompatibility
            datos["gpu_memoria_mb"] = (
                round(int(gpu.AdapterRAM) / (1024 ** 2)) if gpu.AdapterRAM else None
            )
            datos["gpu_driver"] = gpu.DriverVersion

        placas = conexion.Win32_BaseBoard()
        if placas:
            datos["placa_base"] = f"{placas[0].Manufacturer} {placas[0].Product}".strip()

        bios_list = conexion.Win32_BIOS()
        if bios_list:
            datos["bios_version"] = bios_list[0].SMBIOSBIOSVersion

        modulos_ram = conexion.Win32_PhysicalMemory()
        if modulos_ram:
            datos["ram_slots"] = len(modulos_ram)
            datos["ram_velocidad"] = modulos_ram[0].Speed
            tipos_ram = {24: "DDR3", 26: "DDR4", 34: "DDR5"}
            datos["ram_tipo"] = tipos_ram.get(getattr(modulos_ram[0], "SMBIOSMemoryType", None))

    except Exception:
        pass

    return datos


def _leer_dmidecode(clave):
    if shutil.which("dmidecode") is None:
        return None
    try:
        salida = subprocess.run(
            ["dmidecode", "-s", clave], capture_output=True, text=True, timeout=5
        )
        resultado = salida.stdout.strip().splitlines()
        return resultado[0] if resultado else None
    except Exception:
        return None


def _hardware_linux() -> dict:
    datos = {
        "cpu_modelo": None, "cpu_fabricante": None,
        "gpu_modelo": None, "gpu_fabricante": None, "gpu_memoria_mb": None, "gpu_driver": None,
        "placa_base": None, "bios_version": None, "bios_fecha": None,
        "ram_tipo": None, "ram_slots": None, "ram_velocidad": None,
    }

    # CPU: /proc/cpuinfo no requiere privilegios especiales
    try:
        with open("/proc/cpuinfo", "r") as f:
            for linea in f:
                if linea.lower().startswith("model name"):
                    datos["cpu_modelo"] = linea.split(":", 1)[1].strip()
                    break
        datos["cpu_fabricante"] = "Intel" if "intel" in (datos["cpu_modelo"] or "").lower() else (
            "AMD" if "amd" in (datos["cpu_modelo"] or "").lower() else None
        )
    except Exception:
        pass

    # Motherboard/BIOS: requiere dmidecode + privilegios root, best-effort
    datos["placa_base"] = _leer_dmidecode("baseboard-product-name")
    datos["bios_version"] = _leer_dmidecode("bios-version")
    datos["ram_tipo"] = _leer_dmidecode("memory-type") if False else None  # dmidecode no da esto directo

    # GPU vía lspci (no requiere root, casi siempre disponible)
    if shutil.which("lspci"):
        try:
            salida = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
            for linea in salida.stdout.splitlines():
                if "VGA" in linea or "3D controller" in linea:
                    datos["gpu_modelo"] = linea.split(":", 2)[-1].strip()
                    break
        except Exception:
            pass

    return datos


def recolectar_hardware(equipo_id: str) -> dict:
    sistema = platform.system().lower()
    base = _hardware_windows() if sistema == "windows" else _hardware_linux()

    base["equipo_id"] = equipo_id
    base["cpu_nucleos"] = psutil.cpu_count(logical=False)
    base["cpu_hilos"] = psutil.cpu_count(logical=True)
    base["cpu_socket"] = None  # no expuesto de forma confiable multiplataforma

    return base
