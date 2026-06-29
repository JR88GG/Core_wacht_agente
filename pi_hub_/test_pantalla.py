import board
import busio
import digitalio
import fourwire
from adafruit_st7789 import ST7789
from PIL import Image, ImageDraw

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

disp = ST7789(bus, width=240, height=240, rowstart=80, colstart=0)

# Crear imagen con PIL
img  = Image.new("RGB", (240, 240), (0, 20, 40))
draw = ImageDraw.Draw(img)
draw.rectangle([(0,0),(240,240)], fill=(0, 20, 40))
draw.text((120, 100), "SYSWATCH",    fill=(0, 212, 255), anchor="mm")
draw.text((120, 130), "Pantalla OK", fill=(0, 255, 136), anchor="mm")

# Convertir RGB888 a RGB565 que usa el ST7789
def rgb_to_rgb565(img):
    pixels = list(img.getdata())
    data = bytearray(240 * 240 * 2)
    for i, (r, g, b) in enumerate(pixels):
        color = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        data[i*2]     = (color >> 8) & 0xFF
        data[i*2 + 1] = color & 0xFF
    return bytes(data)

pixel_bytes = rgb_to_rgb565(img)
disp._send_pixels(pixel_bytes)
print("Imagen enviada a la pantalla")
import time; time.sleep(30)
import time; time.sleep(30)
