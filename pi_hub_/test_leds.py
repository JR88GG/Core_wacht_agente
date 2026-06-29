import RPi.GPIO as GPIO
import time

EQUIPOS = {
    "HERBER88-PC01": (17, 27, 22),
    "JIM_PC":        ( 9,  5,  6),
    "Equipo-C":      (13, 19, 26),
}
COLORES = {"R": 0, "G": 1, "Y": 2}
NOMBRES_COLOR = {0: "ROJO", 1: "VERDE", 2: "AMARILLO"}

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

todos_pines = [p for pines in EQUIPOS.values() for p in pines]
for p in todos_pines:
    GPIO.setup(p, GPIO.OUT)
    GPIO.output(p, GPIO.LOW)

try:
    print("\n=== TEST DE LEDs SysWatch ===\n")

    # 1. Encender todos los verdes
    print("1. Todos los LEDs VERDES encendidos...")
    for nombre, (pr, pg, py) in EQUIPOS.items():
        GPIO.output(pg, GPIO.HIGH)
    time.sleep(2)
    for nombre, (pr, pg, py) in EQUIPOS.items():
        GPIO.output(pg, GPIO.LOW)
    print("   OK\n")

    # 2. Encender todos los amarillos
    print("2. Todos los LEDs AMARILLOS encendidos...")
    for nombre, (pr, pg, py) in EQUIPOS.items():
        GPIO.output(py, GPIO.HIGH)
    time.sleep(2)
    for nombre, (pr, pg, py) in EQUIPOS.items():
        GPIO.output(py, GPIO.LOW)
    print("   OK\n")

    # 3. Encender todos los rojos
    print("3. Todos los LEDs ROJOS encendidos...")
    for nombre, (pr, pg, py) in EQUIPOS.items():
        GPIO.output(pr, GPIO.HIGH)
    time.sleep(2)
    for nombre, (pr, pg, py) in EQUIPOS.items():
        GPIO.output(pr, GPIO.LOW)
    print("   OK\n")

    # 4. Probar equipo por equipo
    print("4. Prueba por equipo (R → G → Y)...")
    for nombre, (pr, pg, py) in EQUIPOS.items():
        print(f"   {nombre}:")
        for pin, color in [(pr,"ROJO"),(pg,"VERDE"),(py,"AMARILLO")]:
            print(f"     {color}...", end=" ", flush=True)
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(1)
            GPIO.output(pin, GPIO.LOW)
            print("OK")
        time.sleep(0.3)

    # 5. Secuencia final todos juntos
    print("\n5. Secuencia final — todos parpadean...")
    for _ in range(4):
        for p in todos_pines:
            GPIO.output(p, GPIO.HIGH)
        time.sleep(0.3)
        for p in todos_pines:
            GPIO.output(p, GPIO.LOW)
        time.sleep(0.3)

    print("\n=== TEST COMPLETADO ===")
    print("Si todos los LEDs respondieron correctamente")
    print("el cableado esta bien. Puedes iniciar el hub.\n")

except KeyboardInterrupt:
    print("\nTest interrumpido")
finally:
    for p in todos_pines:
        GPIO.output(p, GPIO.LOW)
    GPIO.cleanup()
