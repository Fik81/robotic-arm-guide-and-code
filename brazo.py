"""
Control por voz de un brazo robótico de 6 servos

Conexiones:
  Módulo PWM:  VCC -> pin 1 (3.3V) | SDA -> pin 3  | SCL -> pin 5  | GND -> pin 6   (bus I2C 1)
  LCD 16x2:    VCC -> pin 2 (5V)   | SDA -> pin 27 | SCL -> pin 28 | GND -> pin 9   (bus I2C 0)

Uso: presiona Enter, di un comando (se graba SEG segundos) y el brazo lo ejecuta.
En el teclado:  Enter = hablar | h = ayuda | q = salir
"""
import re
import time
import unicodedata

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from adafruit_servokit import ServoKit

# =====================================================================
#  CONFIGURACIÓN  
# =====================================================================

# --- Micrófono ---
MIC_NOMBRE = "YU8"      # parte del nombre del micrófono USB 
MIC_RESPALDO = 11       # índice a usar si no se encuentra por nombre
SR_WHISPER = 16000      # frecuencia que espera Whisper
SEG = 3                 # segundos que se graba por comando

# --- Movimiento suave ---
PASO_SUAVE = 2          # grados por paso
PAUSA_SUAVE = 0.02      # segundos entre paso y paso

# --- Valores de los comandos ---
PASO_BASE = 20          # girar derecha / izquierda
PASO_HOMBRO = 10        # subir / bajar
PASO_MUNECA = 10        # apuntar arriba / abajo
CENTRO_BASE = 90        # centrar

CODO_RETRAIDO = 0       # retraer
CODO_EXTENDIDO = 100    # extender (máxima extensión sin forzar el servo)
CODO_SEMIFLEXION = (CODO_RETRAIDO + CODO_EXTENDIDO) // 2   # punto medio

GARRA_HORIZONTAL = 0    # 
GARRA_VERTICAL = 90     # 

AGARRE_ABIERTO = 40     # abrir
AGARRE_CERRADO = 120    # cerrar

# --- Servos: fila del módulo PWM (1 a 6) = canal (0 a 5) ---
# "inicio" es la posición a la que va cada servo al arrancar el programa.
# "min" y "max" son los límites de seguridad de cada servo.
SERVOS = {
    "base":     {"fila": 1, "canal": 0, "inicio": 90,               "min": 0, "max": 180},
    "hombro":   {"fila": 2, "canal": 1, "inicio": 90,               "min": 0, "max": 180},
    "codo":     {"fila": 3, "canal": 2, "inicio": CODO_RETRAIDO,    "min": 0, "max": CODO_EXTENDIDO},
    "muneca":   {"fila": 4, "canal": 3, "inicio": 90,               "min": 0, "max": 180},
    "rotacion": {"fila": 5, "canal": 4, "inicio": GARRA_HORIZONTAL, "min": 0, "max": 180},
    "agarre":   {"fila": 6, "canal": 5, "inicio": AGARRE_ABIERTO,   "min": 0, "max": 180},
}

# --- Comandos: (nombre, palabras clave) ---
# Las palabras clave van sin tildes y en minúsculas. El orden importa:
# se prueba de arriba hacia abajo y gana la primera coincidencia.
COMANDOS = [
    ("garra horizontal", ["garra horizontal", "horizontal"]),
    ("garra vertical",   ["garra vertical", "vertical"]),
    ("apuntar arriba",   ["apuntar arriba", "arriba"]),
    ("apuntar abajo",    ["apuntar abajo", "abajo"]),
    ("girar derecha",    ["girar derecha", "derecha"]),
    ("girar izquierda",  ["girar izquierda", "izquierda"]),
    ("centrar",          ["centr"]),
    ("semiflexión",      ["semiflexion", "flexion"]),
    ("extender",         ["extend", "extiend"]),
    ("retraer",          ["retra"]),
    ("subir",            ["subir", "sube", "subi"]),
    ("bajar",            ["bajar", "baja"]),
    ("abrir",            ["abri", "abre"]),
    ("cerrar",           ["cerr", "cierr"]),
]

PROMPT_WHISPER = (
    "girar derecha, girar izquierda, centrar, subir, bajar, extender, retraer, "
    "semiflexión, apuntar arriba, apuntar abajo, garra horizontal, garra vertical, "
    "abrir, cerrar"
)

# Variables que se llenan al iniciar
kit = None
model = None
MIC = MIC_RESPALDO
SR_MIC = 48000
pos = {}   # posición actual de cada servo (en grados)


# =====================================================================
#  MICRÓFONO Y AUDIO
# =====================================================================
def buscar_microfono(nombre, respaldo):
    """Busca el micrófono por nombre; si no lo encuentra usa el índice de respaldo."""
    for i, d in enumerate(sd.query_devices()):
        if nombre.lower() in d["name"].lower() and d["max_input_channels"] > 0:
            return i
    return respaldo


def a_16k(audio, sr_origen):
    """Convierte el audio a 16000 Hz (el micrófono no graba directo a esa tasa)."""
    if sr_origen == SR_WHISPER:
        return audio
    k = max(1, sr_origen // SR_WHISPER)
    if k > 1:
        n = (len(audio) // k) * k
        audio = audio[:n].reshape(-1, k).mean(axis=1)
        sr_origen = sr_origen / k
    n_destino = int(len(audio) * SR_WHISPER / sr_origen)
    x_old = np.linspace(0, 1, len(audio), endpoint=False)
    x_new = np.linspace(0, 1, n_destino, endpoint=False)
    return np.interp(x_new, x_old, audio).astype("float32")


def escuchar():
    """Graba SEG segundos, transcribe con Whisper y devuelve el texto normalizado."""
    audio = sd.rec(int(SEG * SR_MIC), samplerate=SR_MIC, channels=1,
                   dtype="float32", device=MIC)
    sd.wait()
    audio = a_16k(audio.flatten(), SR_MIC)

    segs, _ = model.transcribe(
        audio, language="es", beam_size=1, vad_filter=True,
        initial_prompt=PROMPT_WHISPER,
    )
    return normalizar(" ".join(s.text for s in segs))


# =====================================================================
#  INTERPRETACIÓN DEL TEXTO
# =====================================================================
def normalizar(t):
    """Minúsculas, sin tildes y sin signos: 'Semi-flexión.' -> 'semi flexion'."""
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def buscar_comando(texto):
    """Devuelve el nombre del comando que aparece en el texto, o None."""
    compacto = texto.replace(" ", "")   # para casos como 'semi flexion'
    for nombre, claves in COMANDOS:
        for c in claves:
            if c in texto or c.replace(" ", "") in compacto:
                return nombre
    return None


# =====================================================================
#  CONTROL DE SERVOS
# =====================================================================
def mover(nombre, pedido):
    """Mueve un servo de forma suave hasta el ángulo pedido (respetando sus límites)."""
    s = SERVOS[nombre]
    destino = max(s["min"], min(s["max"], pedido))
    if destino != pedido:
        print(f"   límite alcanzado en {nombre}: se queda en {destino}°")

    servo = kit.servo[s["canal"]]
    actual = pos[nombre]
    paso = PASO_SUAVE if destino > actual else -PASO_SUAVE
    while abs(destino - actual) > PASO_SUAVE:
        actual += paso
        servo.angle = actual
        time.sleep(PAUSA_SUAVE)
    servo.angle = destino
    pos[nombre] = destino
    print(f"   {nombre} (fila {s['fila']}) -> {destino}°")


def ejecutar(c):
    """Ejecuta el movimiento que corresponde a cada comando."""
    if c == "girar derecha":
        mover("base", pos["base"] + PASO_BASE)
    elif c == "girar izquierda":
        mover("base", pos["base"] - PASO_BASE)
    elif c == "centrar":
        mover("base", CENTRO_BASE)
    elif c == "subir":
        mover("hombro", pos["hombro"] + PASO_HOMBRO)
    elif c == "bajar":
        mover("hombro", pos["hombro"] - PASO_HOMBRO)
    elif c == "extender":
        mover("codo", CODO_EXTENDIDO)
    elif c == "retraer":
        mover("codo", CODO_RETRAIDO)
    elif c == "semiflexión":
        mover("codo", CODO_SEMIFLEXION)
    elif c == "apuntar arriba":
        mover("muneca", pos["muneca"] + PASO_MUNECA)
    elif c == "apuntar abajo":
        mover("muneca", pos["muneca"] - PASO_MUNECA)
    elif c == "garra horizontal":
        mover("rotacion", GARRA_HORIZONTAL)
    elif c == "garra vertical":
        mover("rotacion", GARRA_VERTICAL)
    elif c == "abrir":
        mover("agarre", AGARRE_ABIERTO)
    elif c == "cerrar":
        mover("agarre", AGARRE_CERRADO)


def mostrar_posiciones():
    print("   posiciones: " + ", ".join(f"{n} {a}°" for n, a in pos.items()))


def mostrar_ayuda():
    print("\n=== COMANDOS (fila del módulo PWM) ===")
    print(" 1 base ......... girar derecha | girar izquierda | centrar")
    print(" 2 hombro ....... subir | bajar")
    print(" 3 codo ......... extender | retraer | semiflexión")
    print(" 4 muñeca ....... apuntar arriba | apuntar abajo")
    print(" 5 rotación ..... garra horizontal | garra vertical")
    print(" 6 agarre ....... abrir | cerrar")
    print("\n Teclado: Enter = hablar | h = ayuda | q = salir")


# =====================================================================
#  PROGRAMA PRINCIPAL
# =====================================================================
def iniciar():
    global kit, model, MIC, SR_MIC

    MIC = buscar_microfono(MIC_NOMBRE, MIC_RESPALDO)
    SR_MIC = int(sd.query_devices(MIC)["default_samplerate"])
    print(f"Micrófono {MIC} a {SR_MIC} Hz")

    kit = ServoKit(channels=16, address=0x40)
    for s in SERVOS.values():
        kit.servo[s["canal"]].set_pulse_width_range(500, 2500)

    # Posición inicial: un servo a la vez para no cargar la fuente de golpe
    for nombre, s in SERVOS.items():
        kit.servo[s["canal"]].angle = s["inicio"]
        pos[nombre] = s["inicio"]
        time.sleep(0.3)

    print("Cargando modelo de voz...")
    model =WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=4)
    print("Modelo cargado")


def main():
    iniciar()
    mostrar_ayuda()
    mostrar_posiciones()

    while True:
        try:
            tecla = input("\nEnter para hablar (h = ayuda, q = salir): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break
        if tecla == "q":
            break
        if tecla == "h":
            mostrar_ayuda()
            continue

        print(f"Habla ahora ({SEG} s)...")
        t0 = time.time()
        texto = escuchar()
        print(f"-> '{texto}'  ({time.time() - t0 - SEG:.1f}s de reconocimiento)")

        if not texto:
            print("   no se escuchó nada, intenta de nuevo")
            continue

        comando = buscar_comando(texto)
        if comando is None:
            print("   comando no reconocido")
            continue

        print(f"   comando: {comando}")
        ejecutar(comando)
        mostrar_posiciones()

    print("\nPrograma terminado. Los servos quedan en su última posición.")


if __name__ == "__main__":
    main()
