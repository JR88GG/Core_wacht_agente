import threading
import time
import logging

logger = logging.getLogger("syswatch.leds")

_SPI_LOCK = threading.Lock()

EQUIPOS_LEDS = {
    "HERBER88-PC01": (17, 27, 22),
    "JIM_PC":        ( 9,  5,  6),
    "Equipo-C":      (13, 19, 26),
}
LED_GLOBAL = None
class LedTricolor:
    def __init__(self, pin_r, pin_g, pin_y, gpio):
        self.pin_r = pin_r
        self.pin_g = pin_g
        self.pin_y = pin_y
        self._gpio = gpio
        self._corriendo = False
        self._hilo = None
        gpio.setup(pin_r, gpio.OUT)
        gpio.setup(pin_g, gpio.OUT)
        gpio.setup(pin_y, gpio.OUT)
        self.apagar()

    def apagar(self):
        self._corriendo = False
        for p in (self.pin_r, self.pin_g, self.pin_y):
            self._gpio.output(p, self._gpio.LOW)

    def verde_pulso(self, periodo=2.0):
        self._iniciar_hilo(self._loop, periodo, self.pin_g)

    def amarillo(self):
        self._corriendo = False
        self._gpio.output(self.pin_r, self._gpio.LOW)
        self._gpio.output(self.pin_g, self._gpio.LOW)
        self._gpio.output(self.pin_y, self._gpio.HIGH)

    def rojo_rapido(self, periodo=0.4):
        self._iniciar_hilo(self._loop, periodo, self.pin_r)

    def _iniciar_hilo(self, fn, *args):
        self._corriendo = False
        if self._hilo and self._hilo.is_alive():
            self._hilo.join(timeout=1)
        self._corriendo = True
        self._hilo = threading.Thread(target=fn, args=args, daemon=True)
        self._hilo.start()

    def _loop(self, periodo, pin):
        mitad = periodo / 2
        for p in (self.pin_r, self.pin_g, self.pin_y):
            if p != pin:
                self._gpio.output(p, self._gpio.LOW)
        while self._corriendo:
            self._gpio.output(pin, self._gpio.HIGH)
            time.sleep(mitad)
            if not self._corriendo:
                break
            self._gpio.output(pin, self._gpio.LOW)
            time.sleep(mitad)
        self._gpio.output(pin, self._gpio.LOW)

def _aplicar_estado(led, estado):
    if estado == "ok":
        led.verde_pulso()
    elif estado == "warning":
        led.amarillo()
    elif estado == "critical":
        led.rojo_rapido()
    else:
        led.apagar()


def _estado_equipo(eq):
    from datetime import datetime, timezone
    ts = eq.get("metrica_ts")
    if not ts:
        return "offline"
    try:
        seg = (datetime.now(timezone.utc) -
               datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()
        if seg > 180:
            return "offline"
    except Exception:
        return "offline"
    alertas = eq.get("alertas_activas", 0)
    if alertas == 0:
        return "ok"
    return "critical" if eq.get("tiene_critica") else "warning"


class Pantalla:
    def __init__(self):
        self._disp      = None
        self._Image     = None
        self._ImageDraw = None
        self._font_g    = None
        self._font_n    = None
        self._font_p    = None
        self._lock      = threading.Lock()

    def inicializar(self):
        try:
            import board
            import busio
            import digitalio
            import fourwire
            from adafruit_st7789 import ST7789
            from PIL import Image, ImageDraw, ImageFont
            self._Image     = Image
            self._ImageFont = ImageFont
            self._ImageDraw = ImageDraw
            bl = digitalio.DigitalInOut(board.D18)
            bl.direction = digitalio.Direction.OUTPUT
            bl.value = True
            spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)
            bus = fourwire.FourWire(
                spi,
                command=board.D24,
                chip_select=board.CE0,
                reset=board.D25,
                baudrate=40000000
            )
            self._disp = ST7789(bus, width=240, height=240, rowstart=80, colstart=0)
            try:
                rb = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                rn = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
                self._font_g = ImageFont.truetype(rb, 18)
                self._font_n = ImageFont.truetype(rn, 13)
                self._font_p = ImageFont.truetype(rn, 11)
            except Exception:
                self._font_g = ImageFont.load_default()
                self._font_n = self._font_g
                self._font_p = self._font_g
            self._inicio()
            logger.info("Pantalla ST7789 inicializada")
            return True
        except Exception as e:
            logger.warning("Pantalla no disponible: %s", e)
            return False

    def _rgb565(self, img):
        data = bytearray(240 * 240 * 2)
        pixels = list(img.getdata())
        for i, (r, g, b) in enumerate(pixels):
            c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            data[i*2]     = (c >> 8) & 0xFF
            data[i*2 + 1] = c & 0xFF
        return bytes(data)

    def _enviar(self, img):
        with _SPI_LOCK:
            self._disp._send_pixels(self._rgb565(img))

    def _inicio(self):
        img  = self._Image.new("RGB", (240, 240), (8, 11, 14))
        draw = self._ImageDraw.Draw(img)
        font_title = self._ImageFont.truetype("/usr/share/fonts/truetype/pixel/PressStart2P-Regular.ttf", 22)
        font_sub   = self._ImageFont.truetype("/usr/share/fonts/truetype/pixel/PressStart2P-Regular.ttf", 10)
        draw.rectangle([(0,0),(240,240)], fill=(8,11,14))
        draw.rectangle([(0,0),(240,3)],   fill=(0,212,255))
        draw.rectangle([(0,237),(240,240)], fill=(0,212,255))
        draw.text((120, 95),  "CORE",    font=font_title, fill=(0,212,255), anchor="mm")
        draw.text((120, 125), "WATCH",   font=font_title, fill=(0,212,255), anchor="mm")
        draw.text((120, 165), "v1.0",    font=font_sub,   fill=(60,80,100), anchor="mm")
        draw.text((120, 185), "monitor activo", font=font_sub, fill=(40,60,80), anchor="mm")
        self._enviar(img)

    def actualizar(self, equipos, alertas_totales):
        if not self._disp:
            return
        ahora = time.time()
        if ahora - getattr(self, '_ultima_actualizacion', 0) < 60:
            return
        self._ultima_actualizacion = ahora
        with self._lock:
            try:
                self._render(equipos, alertas_totales)
            except Exception as e:
                logger.warning("Error pantalla: %s", e)

    def _render(self, equipos, alertas_totales):
        from datetime import datetime
        img  = self._Image.new("RGB", (240, 240), (8, 11, 14))
        draw = self._ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (240, 28)], fill=(13, 17, 23))
        draw.text((8, 14),   "COREWATCH",                       font=self._font_n, fill=(0, 212, 255), anchor="lm")
        draw.text((232, 14), datetime.now().strftime("%H:%M"), font=self._font_p, fill=(107, 128, 153), anchor="rm")
        draw.line([(0, 29), (240, 29)], fill=(30, 45, 61), width=1)
        y = 38
        for eq in equipos[:4]:
            estado = _estado_equipo(eq)
            color_dot = {
                "ok":       (0, 255, 136),
                "warning":  (255, 183, 0),
                "critical": (255, 71, 87),
                "offline":  (60, 80, 100),
            }.get(estado, (60, 80, 100))
            nombre = (eq.get("nombre") or "Equipo")[:15]
            draw.text((8, y+8), nombre, font=self._font_n, fill=(232, 244, 255), anchor="lm")
            draw.ellipse([(222, y+2), (234, y+14)], fill=color_dot)
            cpu = eq.get("cpu_pct") or 0
            bw  = int((cpu / 100) * 110)
            bc  = (0, 212, 255) if cpu < 70 else (255, 183, 0) if cpu < 90 else (255, 71, 87)
            draw.rectangle([(8, y+18), (118, y+24)], fill=(30, 45, 61))
            if bw > 0:
                draw.rectangle([(8, y+18), (8+bw, y+24)], fill=bc)
            draw.text((122, y+21), f"CPU {cpu:.0f}%", font=self._font_p, fill=(107, 128, 153), anchor="lm")
            ram  = eq.get("ram_pct") or 0
            temp = eq.get("temp_cpu")
            draw.text((8, y+32), f"RAM {ram:.0f}%", font=self._font_p, fill=(107, 128, 153), anchor="lm")
            if temp:
                tc = (255, 71, 87) if temp >= 85 else (255, 183, 0) if temp >= 75 else (107, 128, 153)
                draw.text((122, y+32), f"{temp:.0f}C", font=self._font_p, fill=tc, anchor="lm")
            draw.line([(0, y+44), (240, y+44)], fill=(20, 30, 42), width=1)
            y += 50
        draw.rectangle([(0, 214), (240, 240)], fill=(13, 17, 23))
        draw.line([(0, 214), (240, 214)], fill=(30, 45, 61), width=1)
        if alertas_totales > 0:
            draw.text((120, 227), f"{alertas_totales} alerta(s)", font=self._font_p, fill=(255, 71, 87), anchor="mm")
        else:
            draw.text((120, 227), "Sistemas OK", font=self._font_p, fill=(0, 255, 136), anchor="mm")
        self._enviar(img)


class ControladorLEDs:
    def __init__(self):
        self._leds     = {}
        self._global   = None
        self._gpio     = None
        self._ok       = False
        self._pantalla = Pantalla()
        self._ultimo_dashboard = []
        self._hilo_pantalla = None

    def inicializar(self):
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            for nombre, (pr, pg, py) in EQUIPOS_LEDS.items():
                self._leds[nombre] = LedTricolor(pr, pg, py, GPIO)
            self._global = None
            self._ok = True
            logger.info("GPIO inicializado — %d equipos", len(self._leds))
            self._animacion_inicio()
        except Exception as e:
            logger.warning("GPIO no disponible: %s", e)
        self._pantalla.inicializar()
        self._hilo_pantalla = threading.Thread(target=self._loop_pantalla, daemon=True)
        self._hilo_pantalla.start()

    def _animacion_inicio(self):
        todos = list(self._leds.values()) + ([self._global] if self._global else [])
        for led in todos:
            led._gpio.output(led.pin_g, led._gpio.HIGH)
            time.sleep(0.12)
        time.sleep(0.4)
        for led in todos:
            led.apagar()

    def _loop_pantalla(self):
        pass
        import time as _time
    def actualizar(self, dashboard_data):
        alertas_totales = sum(eq.get("alertas_activas", 0) for eq in dashboard_data)
        estados = []
        for eq in dashboard_data:
            estado = _estado_equipo(eq)
            estados.append(estado)
            led = self._leds.get(eq.get("nombre", ""))
            if led and self._ok:
                _aplicar_estado(led, estado)
        if self._global and self._ok:
            if not estados or all(e == "offline" for e in estados):
                self._global.apagar()
            elif "critical" in estados:
                _aplicar_estado(self._global, "critical")
            elif "warning" in estados:
                _aplicar_estado(self._global, "warning")
            else:
                _aplicar_estado(self._global, "ok")
        self._ultimo_dashboard = dashboard_data

    def apagar_todo(self):
        if self._ok:
            for led in self._leds.values():
                led.apagar()
            if self._global:
                self._global.apagar()
        if self._gpio:
            self._gpio.cleanup()


controlador = ControladorLEDs()
