"""
Control por voz de un brazo robótico de 6 servos  —  VERSIÓN DE PRUEBA CON LCD 16x2 I2C

Conexiones:
  Módulo PWM:  VCC -> pin 1 (3.3V) | SDA -> pin 3  | SCL -> pin 5  | GND -> pin 6   (bus I2C 1)
  LCD 16x2:    VCC -> pin 2 (5V)   | SDA -> pin 27 | SCL -> pin 28 | GND -> pin 9   (bus I2C 0)

Uso: presiona Enter, di un comando (se graba SEG segundos) y el brazo lo ejecuta.
Si el reconocimiento tarda más de TIEMPO_MAX_RECONOCIMIENTO segundos, se vuelve a pedir el comando.
En el teclado:  Enter = hablar | h = ayuda | q = salir
La LCD es opcional: si no se encuentra o falla, el programa sigue solo en consola.
"""
import re
import threading
import time
import unicodedata

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from adafruit_servokit import ServoKit

try:
    from RPLCD.i2c import CharLCD
except ImportError:
    CharLCD = None

# =====================================================================
#  CONFIGURACIÓN  
# =====================================================================

# --- Micrófono ---
MIC_NOMBRE = "YU8"      # parte del nombre del micrófono USB 
MIC_RESPALDO = 11       # índice a usar si no se encuentra por nombre
SR_WHISPER = 16000      # frecuencia que espera Whisper
SEG = 3                 # segundos que se graba por comando

# --- Tiempo máximo de reconocimiento ---
TIEMPO_MAX_RECONOCIMIENTO = 8   # si pasa de estos segundos sin detectar, se vuelve a pedir
REINTENTOS_MAX = 3              # veces que se pide el comando antes de volver al menú

# --- LCD 16x2 I2C ---
USAR_LCD = True                 
LCD_PUERTO = 0                  
LCD_DIRECCIONES = (0x27,)       # dirección de la LCD 
BIENVENIDA = "Bienvenido"
NOMBRE = "Hecho por Santiago Rodriguez"   
CUENTA_REGRESIVA = 3            # "Habla en 3, 2, 1" 
TIEMPO_AYUDA = 3                # segundos que se ve cada pantalla de la ayuda
TIEMPO_RESULTADO = 3            # segundos que se ve el resultado antes de volver al menú

# Pantallas de la ayuda
AYUDA_LCD = [
    ("girar derecha",    "girar izquierda"),
    ("centrar",          "subir"),
    ("bajar",            "extender"),
    ("retraer",          "semiflexion"),
    ("apuntar arriba",   "apuntar abajo"),
    ("garra horizontal", "garra vertical"),
    ("abrir",            "cerrar"),
    ("Tecla r:",         "estado inicial"),
]
MENU = ("Enter:hab  r:ini", "h:ayuda  q:salir")
TECLA_INICIO = "r"      # tecla para volver todos los servos a su posición inicial

# --- Movimiento suave ---
PASO_SUAVE = 2          # grados por paso
PAUSA_SUAVE = 0.02      # segundos entre paso y paso

# --- Valores de los comandos  ---
PASO_BASE = 20          # girar derecha / izquierda
PASO_HOMBRO = 10        # subir / bajar
PASO_MUNECA = 10        # apuntar arriba / abajo
CENTRO_BASE = 90        # centrar

HOMBRO_ARRIBA = 33      # posición más alta del hombro 
HOMBRO_ABAJO = 98       # máximo de bajada del hombro

MUNECA_MIN = 0          # límite inferior de la muñeca
MUNECA_MAX = 130        # límite superior de la muñeca

CODO_RETRAIDO = 75      # retraer: estado base (inicio); no sube más de aquí
CODO_EXTENDIDO = 0      # extender: el codo totalmente estirado
CODO_SEMIFLEXION = 32

GARRA_HORIZONTAL = 90  
GARRA_VERTICAL = 10    

AGARRE_ABIERTO = 80     # abrir
AGARRE_CERRADO = 150    # cerrar

# --- Servos: fila del módulo PWM (1 a 6) = canal (0 a 5) ---
SERVOS = {
    "base":     {"fila": 1, "canal": 0, "inicio": 90,               "min": 0,              "max": 180},
    "hombro":   {"fila": 2, "canal": 1, "inicio": HOMBRO_ARRIBA,    "min": HOMBRO_ARRIBA,  "max": HOMBRO_ABAJO},
    "codo":     {"fila": 3, "canal": 2, "inicio": CODO_RETRAIDO,    "min": CODO_EXTENDIDO, "max": CODO_RETRAIDO},
    "muneca":   {"fila": 4, "canal": 3, "inicio": 30,               "min": MUNECA_MIN,     "max": MUNECA_MAX},
    "rotacion": {"fila": 5, "canal": 4, "inicio": GARRA_HORIZONTAL, "min": 0,              "max": 180},
    "agarre":   {"fila": 6, "canal": 5, "inicio": AGARRE_ABIERTO,   "min": 0,              "max": 180},
}

NOMBRES = {"base": "Base", "hombro": "Hombro", "codo": "Codo",
           "muneca": "Muneca", "rotacion": "Rotacion", "agarre": "Agarre"}

# --- Comandos: (nombre, palabras clave) ---
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
pantalla = None
MIC = MIC_RESPALDO
SR_MIC = 48000
pos = {}             # posición actual de cada servo 
aviso_limite = None  # mensaje de límite
hilo_reconocimiento = None   # reconocimiento en curso (para el tiempo máximo)


# =====================================================================
#  LCD 16x2 I2C  
# =====================================================================
BLOQUE = (0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F)   


def _ascii(t):
    """La LCD no tiene tildes ni ñ: 'Semiflexión' -> 'Semiflexion'."""
    t = unicodedata.normalize("NFD", str(t))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.encode("ascii", "ignore").decode()


def _ajustar(t):
    """Deja el texto exactamente de 16 letras (así no hace falta borrar la pantalla)."""
    return _ascii(t)[:16].ljust(16)


def _centro(t):
    return _ascii(t)[:16].center(16)


class Pantalla:
    def __init__(self):
        self.ok = False
        self.lcd = None
        self._hilo = None
        self._parar = threading.Event()
        self._n_barra = -1
        if not USAR_LCD:
            return
        if CharLCD is None:
            print("RPLCD no está conectada; se sigue solo en consola")
            return
        for d in LCD_DIRECCIONES:
            try:
                self.lcd = CharLCD(i2c_expander="PCF8574", address=d, port=LCD_PUERTO,
                                   cols=16, rows=2, charmap="A00", auto_linebreaks=False)
                self.lcd.create_char(0, BLOQUE)
                self.lcd.clear()
                self.ok = True
                print(f"LCD encontrada en la dirección 0x{d:02X}")
                break
            except Exception:
                self.lcd = None
        if not self.ok:
            print("LCD no encontrada; se sigue solo en consola")

    # ---------- escritura básica ----------
    def _linea(self, fila, texto):
        if not self.ok:
            return
        try:
            self.lcd.cursor_pos = (fila, 0)
            self.lcd.write_string(_ajustar(texto))
        except Exception as e:
            print(f"   (error de LCD: {e}; se sigue solo en consola)")
            self.ok = False

    def _escribir(self, l1, l2):
        self._linea(0, l1)
        self._linea(1, l2)

    # ---------- ayuda y volver al menú ----------
    def _detener(self):
        if self._hilo is not None and self._hilo.is_alive():
            self._parar.set()
            self._hilo.join()
        self._parar.clear()

    def _en_fondo(self, tarea):
        if not self.ok:
            return
        self._detener()
        self._hilo = threading.Thread(target=tarea, daemon=True)
        self._hilo.start()

    # ---------- pantallas ----------
    def mensaje(self, l1, l2=""):
        self._detener()
        self._escribir(l1, l2)

    def menu(self):
        self.mensaje(*MENU)

    def bienvenida(self):
        if not self.ok:
            return
        l1 = _centro(BIENVENIDA)
        nombre = _ascii(NOMBRE)
        if len(nombre) <= 16:
            self.mensaje(l1, nombre.center(16))
            time.sleep(3)
            return
        # Nombre, se desplaza para que se lea completo
        self.mensaje(l1, nombre[:16])
        time.sleep(1.5)
        for i in range(1, len(nombre) - 15):
            self._linea(1, nombre[i:i + 16])
            time.sleep(0.4)
        time.sleep(1.5)
        self._linea(1, nombre[:16])
        time.sleep(1)

    def ayuda(self):
        """Muestra todos los comandos, cambiando cada TIEMPO_AYUDA segundos, y vuelve al menú.
        Se interrumpe sola si se presiona Enter."""
        def tarea():
            self._escribir(_centro("Comandos de voz"), _centro(f"(cada {TIEMPO_AYUDA} s)"))
            if self._parar.wait(2):
                return
            for l1, l2 in AYUDA_LCD:
                self._escribir(l1, l2)
                if self._parar.wait(TIEMPO_AYUDA):
                    return
            self._escribir(*MENU)
        self._en_fondo(tarea)

    def cuenta(self, n):
        self.mensaje(_centro("Habla en..."), _centro(str(n)))

    def escuchando_inicio(self):
        self.mensaje(_centro("Escuchando..."), "")
        self._n_barra = -1

    def escuchando_barra(self, frac):
        n = max(0, min(16, int(16 * frac)))
        if n != self._n_barra:
            self._n_barra = n
            self._linea(1, "\x00" * n)

    def procesando(self):
        self.mensaje("Preparando orden", _centro("espere..."))

    def no_detectado(self):
        self.mensaje("No se detecto", "repite la orden")

    def orden(self, comando):
        self.mensaje("Orden detectada:", _centro(comando.upper()))

    def resultado(self, texto, comando):
        """Muestra el resultado unos segundos y vuelve al menú (o se interrumpe con Enter)."""
        def tarea():
            if texto is None:
                self._escribir("Tiempo agotado", "intenta de nuevo")
            elif not texto:
                self._escribir("No se escucho", "intenta de nuevo")
            elif comando is None:
                self._escribir(_centro("Comando no"), _centro("detectado"))
            elif aviso_limite:
                self._escribir("Limite alcanzado", aviso_limite)
            # si el comando fue válido, "Orden detectada" ya está en pantalla
            if self._parar.wait(TIEMPO_RESULTADO):
                return
            self._escribir(*MENU)
        self._en_fondo(tarea)

    def cerrar(self):
        self._detener()
        if self.ok:
            try:
                self.lcd.close(clear=False)
            except Exception:
                pass


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


def transcribir(audio):
    """Reconoce el audio con Whisper. Devuelve el texto, o None si pasa de
    TIEMPO_MAX_RECONOCIMIENTO segundos sin terminar."""
    global hilo_reconocimiento

    # Si quedó un reconocimiento anterior sin terminar, se espera a que acabe
    # para no tener dos al mismo tiempo (la Jetson se pondría más lenta)
    if hilo_reconocimiento is not None and hilo_reconocimiento.is_alive():
        hilo_reconocimiento.join()

    resultado = {}
    cancelar = threading.Event()

    def tarea():
        try:
            segs, _ = model.transcribe(
                audio, language="es", beam_size=1, vad_filter=True,
                initial_prompt=PROMPT_WHISPER,
                temperature=0.0,                   # sin reintentos internos (son los que más demoran)
                condition_on_previous_text=False,  # evita que se quede repitiendo texto
            )
            partes = []
            for s in segs:
                if cancelar.is_set():
                    return
                partes.append(s.text)
            resultado["texto"] = " ".join(partes)
        except Exception as e:
            resultado["error"] = e

    hilo_reconocimiento = threading.Thread(target=tarea, daemon=True)
    hilo_reconocimiento.start()
    hilo_reconocimiento.join(TIEMPO_MAX_RECONOCIMIENTO)

    if hilo_reconocimiento.is_alive():   # se pasó del tiempo
        cancelar.set()
        return None
    if "error" in resultado:
        raise resultado["error"]
    return normalizar(resultado.get("texto", ""))


def escuchar():
    """Cuenta regresiva, graba SEG segundos y transcribe.
    Devuelve (texto, tiempo); texto es None si se pasó del tiempo máximo."""
    for n in range(CUENTA_REGRESIVA, 0, -1):
        print(f"   {n}...")
        pantalla.cuenta(n)
        time.sleep(1)

    print(f"Habla ahora ({SEG} s)...")
    audio = sd.rec(int(SEG * SR_MIC), samplerate=SR_MIC, channels=1,
                   dtype="float32", device=MIC)
    pantalla.escuchando_inicio()
    t0 = time.time()
    while time.time() - t0 < SEG:       # la grabación sigue en segundo plano
        pantalla.escuchando_barra((time.time() - t0) / SEG)
        time.sleep(0.05)
    sd.wait()
    pantalla.escuchando_barra(1)

    pantalla.procesando()
    t1 = time.time()
    audio = a_16k(audio.flatten(), SR_MIC)
    texto = transcribir(audio)
    return texto, time.time() - t1


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
    compacto = texto.replace(" ", "")
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
    global aviso_limite
    s = SERVOS[nombre]
    destino = max(s["min"], min(s["max"], pedido))
    if destino != pedido:
        aviso_limite = f"{NOMBRES[nombre]} en {destino}"
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
        # En este brazo el hombro sube al REDUCIR el ángulo (33° es lo más arriba)
        mover("hombro", pos["hombro"] - PASO_HOMBRO)
    elif c == "bajar":
        # y baja al AUMENTAR el ángulo (98° es lo más abajo)
        mover("hombro", pos["hombro"] + PASO_HOMBRO)
    elif c == "extender":
        mover("codo", CODO_EXTENDIDO)
    elif c == "retraer":
        mover("codo", CODO_RETRAIDO)
    elif c == "semiflexión":
        mover("codo", CODO_SEMIFLEXION)
    elif c == "apuntar arriba":
        # En este brazo la muñeca sube al REDUCIR el ángulo
        mover("muneca", pos["muneca"] - PASO_MUNECA)
    elif c == "apuntar abajo":
        # y baja al AUMENTAR el ángulo
        mover("muneca", pos["muneca"] + PASO_MUNECA)
    elif c == "garra horizontal":
        mover("rotacion", GARRA_HORIZONTAL)
    elif c == "garra vertical":
        mover("rotacion", GARRA_VERTICAL)
    elif c == "abrir":
        mover("agarre", AGARRE_ABIERTO)
    elif c == "cerrar":
        mover("agarre", AGARRE_CERRADO)


def ir_a_inicio():
    """Lleva todos los servos a su posición inicial, uno por uno y de forma suave."""
    print("Volviendo al estado inicial...")
    pantalla.mensaje(_centro("Volviendo al"), _centro("estado inicial"))
    for nombre, s in SERVOS.items():
        mover(nombre, s["inicio"])
        time.sleep(0.2)
    print("   brazo en estado inicial")


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
    print(f"\n Teclado: Enter = hablar | h = ayuda | {TECLA_INICIO} = estado inicial | q = salir")


# =====================================================================
#  PROGRAMA PRINCIPAL
# =====================================================================
def iniciar():
    global kit, model, MIC, SR_MIC, pantalla

    pantalla = Pantalla()
    pantalla.bienvenida()
    pantalla.mensaje(_centro("Iniciando..."), _centro("mic y servos"))

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
    pantalla.mensaje(_centro("Cargando modelo"), _centro("de voz..."))
    model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=4)
    print("Modelo cargado")
    pantalla.menu()


def main():
    global aviso_limite
    iniciar()
    mostrar_ayuda()
    mostrar_posiciones()

    while True:
        try:
            tecla = input(f"\nEnter para hablar (h = ayuda, {TECLA_INICIO} = estado inicial, "
                          f"q = salir): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break
        if tecla == "q":
            break
        if tecla == "h":
            mostrar_ayuda()
            pantalla.ayuda()
            continue
        if tecla == TECLA_INICIO:
            ir_a_inicio()
            mostrar_posiciones()
            pantalla.menu()
            continue

        aviso_limite = None

        # Si el reconocimiento pasa del tiempo máximo, se vuelve a pedir el comando
        for intento in range(1, REINTENTOS_MAX + 1):
            texto, t_rec = escuchar()
            if texto is not None:
                break
            print(f"   pasaron {TIEMPO_MAX_RECONOCIMIENTO} s sin detectar el comando "
                  f"(intento {intento} de {REINTENTOS_MAX})")
            if intento < REINTENTOS_MAX:
                print("   repite el comando")
                pantalla.no_detectado()
                time.sleep(1.5)

        if texto is None:
            print("   no se pudo detectar el comando; presiona Enter para intentar de nuevo")
            pantalla.resultado(None, None)
            continue

        if not texto:
            print("   no se escuchó nada, intenta de nuevo")
            pantalla.resultado(texto, None)
            continue

        comando = buscar_comando(texto)
        if comando is None:
            print("   comando no detectado")
            pantalla.resultado(texto, None)
            continue

        print(f"   comando: {comando}  ({t_rec:.1f}s de reconocimiento)")
        pantalla.orden(comando)
        ejecutar(comando)
        mostrar_posiciones()
        pantalla.resultado(texto, comando)

    print("\nPrograma terminado. Los servos quedan en su última posición.")
    pantalla.mensaje(_centro("Programa"), _centro("terminado"))
    pantalla.cerrar()


if __name__ == "__main__":
    main()


