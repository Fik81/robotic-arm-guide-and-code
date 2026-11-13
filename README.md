# Brazo robótico controlado por voz

Brazo robótico de 6 servomotores que se controla con comandos de voz en español. Una Jetson Nano escucha el comando por un micrófono USB, lo reconoce con el modelo **Whisper tiny** (implementación **faster-whisper**) y mueve los servos por medio del módulo PWM **PCA9685**.

Trabajo de grado de Ingeniería Electrónica — Santiago Rodriguez Molina.

## Versiones del programa

| Archivo | Descripción |
|---|---|
| `brazo_LCD.py` | Versión con pantalla LCD 16x2 I2C: muestra la bienvenida, el menú, la ayuda, el conteo, la barra de grabación y el comando detectado. Si la LCD no está conectada, sigue funcionando solo en la consola. |
| `brazo_sin_LCD.py` | Versión solo con consola: el mismo control de voz y de servos, sin la pantalla ni la librería RPLCD. Muestra en la consola el texto que reconoció. |

Las dos versiones usan los mismos comandos, ángulos, límites y teclas.

## Cómo funciona

1. Se presiona **Enter** y empieza un conteo de 3, 2, 1.
2. El programa graba 3 segundos de audio y lo convierte a 16 kHz.
3. faster-whisper transcribe el audio a texto. Si tarda más de 8 segundos, vuelve a pedir el comando (hasta 3 veces).
4. El texto se normaliza (minúsculas, sin tildes ni signos) y se buscan palabras clave para identificar el comando.
5. El servo correspondiente se mueve de forma suave (2° por paso) hasta su nuevo ángulo, sin pasar sus límites.

## Comandos

| Servo (fila del PCA9685) | Comandos |
|---|---|
| Base (1) | girar derecha · girar izquierda · centrar |
| Hombro (2) | subir · bajar |
| Codo (3) | extender · retraer · semiflexión |
| Muñeca (4) | apuntar arriba · apuntar abajo |
| Rotación de la garra (5) | garra horizontal · garra vertical |
| Agarre (6) | abrir · cerrar |

Teclas: **Enter** = hablar · **h** = ayuda · **r** = posición inicial · **q** = salir.

## Hardware

- Jetson Nano (JetPack 4.x)
- Módulo PWM PCA9685 (I2C bus 1, dirección `0x40`)
- 6 servomotores con fuente externa de 5 a 6 V
- Micrófono USB
- LCD 16x2 con módulo I2C PCF8574 (I2C bus 0, dirección `0x27`), solo para `brazo_LCD.py`

Las conexiones, el uso paso a paso y la solución de problemas están en el [manual de usuario](MANUAL.md).

## Instalación

La Jetson Nano trae Python 3.6.9, que faster-whisper no soporta, así que el proyecto usa un entorno virtual con Python 3.8:

```bash
sudo apt install python3.8 python3.8-venv python3.8-dev libportaudio2
python3.8 -m venv ~/venv-whisper
source ~/venv-whisper/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

`RPLCD` y `smbus2` solo son necesarias para la versión con LCD.

La primera vez que se ejecuta, el modelo Whisper tiny se descarga desde Hugging Face, así que la Jetson necesita internet en ese momento.

## Ejecución

```bash
cd ~/Desktop/Brazo

# Versión con LCD
sudo -E ~/venv-whisper/bin/python brazo_LCD.py

# Versión sin LCD
sudo -E ~/venv-whisper/bin/python brazo_sin_LCD.py
```

## Archivos

| Archivo | Contenido |
|---|---|
| `brazo_LCD.py` | Programa con pantalla LCD |
| `brazo_sin_LCD.py` | Programa solo con consola |
| `MANUAL.md` | Manual de usuario |
| `requirements.txt` | Librerías de Python necesarias |

## Créditos

- [Whisper](https://github.com/openai/whisper) — OpenAI (licencia MIT)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — SYSTRAN (licencia MIT)
