# Guía de usuario - Brazo robótico controlado por voz

Elaborada por Santiago Rodriguez Molina · Oct 19, 2026

## 1. Presentación

En esta guía explico cómo conectar y usar el brazo robótico que se controla con la voz. El brazo tiene 6 servomotores y lo maneja una Jetson Nano: escucha el comando por un micrófono USB, lo reconoce con el modelo Faster-Whisper y mueve los servos por medio del módulo PWM PCA9685.

Además le agregué una pantalla LCD de 16x2 para que se pueda ver en qué paso va el programa y qué comando entendió. La idea es que cualquier persona pueda poner a funcionar el brazo siguiendo estos pasos, sin necesidad de leer el código.

## 2. Materiales

Estos son los elementos que forman el sistema y la función de cada uno:

| Elemento                               | Para qué sirve                                                                                       |
|----------------------------------------|------------------------------------------------------------------------------------------------------|
| Jetson Nano                            | Es el cerebro: corre el programa, reconoce la voz y envía las órdenes a los servos.                  |
| Módulo PWM PCA9685                     | Genera la señal de control de los 6 servomotores.                                                    |
| 6 servomotores                         | Mueven cada parte del brazo: base, hombro, codo, muñeca, rotación de la garra y agarre.              |
| Fuente externa para los servos         | Le da la corriente a los servomotores; la Jetson no tiene la potencia suficiente para moverlos. 5-6V |
| Micrófono USB o interfaz de audio      | Capta el comando de voz.                                                                             |
| LCD 16x2 con módulo I2C (PCF8574)      | Muestra los mensajes del programa: menú, ayuda, conteo y comando detectado.                          |
| Cables jumper hembra-hembra            | Conexión entre la Jetson, el módulo PWM y la LCD.                                                    |
| Teclado y monitor (o conexión por SSH) | Para iniciar el programa y usar las teclas Enter, h y q.                                             |

## 3. Conexiones

El módulo PWM y la LCD se comunican con la Jetson por I2C, pero cada uno va en un bus diferente: el PWM en el bus 1 (pines 3 y 5) y la LCD en el bus 0 (pines 27 y 28). Así no hay que compartir pines y, si algo falla en la LCD, no afecta el movimiento del brazo. Todas las conexiones se hacen con la Jetson y la fuente apagadas.

### 3.1 Módulo PWM PCA9685 a la Jetson Nano

| Pin del módulo PWM | Pin de la Jetson Nano | Descripción                  |
|--------------------|-----------------------|------------------------------|
| VCC                | Pin 1                 | Alimentación lógica de 3.3 V |
| SDA                | Pin 3                 | Datos I2C (bus 1)            |
| SCL                | Pin 5                 | Reloj I2C (bus 1)            |
| GND                | Pin 6                 | Tierra                       |

La fuente externa de los servos se conecta en la bornera V+ y GND del módulo PWM, nunca a los pines de la Jetson.

### 3.2 LCD 16x2 (módulo I2C) a la Jetson Nano

| Pin de la LCD | Pin de la Jetson Nano | Descripción         |
|---------------|-----------------------|---------------------|
| VCC           | Pin 2                 | Alimentación de 5 V |
| GND           | Pin 9                 | Tierra              |
| SDA           | Pin 27                | Datos I2C (bus 0)   |
| SCL           | Pin 28                | Reloj I2C (bus 0)   |

La LCD necesita 5 V para que el texto se vea bien, por eso va al pin 2 y no al pin 1. La dirección de mi LCD es `0x27`.

### 3.3 Servomotores en el módulo PWM

Cada servo va en una fila del módulo PWM. La fila 1 corresponde al canal 0, la fila 2 al canal 1, y así sucesivamente:

| Fila del PWM | Canal | Servo                   |
|--------------|-------|-------------------------|
| 1            | 0     | Base                    |
| 2            | 1     | Hombro                  |
| 3            | 2     | Codo                    |
| 4            | 3     | Muñeca                  |
| 5            | 4     | Rotación de la garra    |
| 6            | 5     | Agarre (abrir y cerrar) |

### 3.4 Micrófono

El micrófono USB va en cualquier puerto USB de la Jetson. El programa lo busca solo por su nombre (`YU8`), así que no importa en cuál puerto quede.

### 3.5 Comprobar las conexiones

Antes de correr el programa se puede verificar que la Jetson detecta los dos módulos con estos comandos en la terminal:

```bash
sudo i2cdetect -y -r 1
sudo i2cdetect -y -r 0
```

En el bus 1 debe aparecer **40** (el módulo PWM; también puede salir un 70, que es normal) y en el bus 0 debe aparecer **27** (la LCD).

## 4. Encendido y ejecución del programa

El programa se llama `brazo_LCD.py` y está en la carpeta `~/Desktop/Brazo` de la Jetson. Se ejecuta con el Python del entorno virtual `venv-whisper`, que es donde están instaladas todas las librerías.

1.  Revisar que todo esté conectado como en la sección 3.

2.  Encender la fuente de los servos y luego la Jetson Nano.

3.  Abrir una terminal y entrar a la carpeta del proyecto:

    ```bash
    cd ~/Desktop/Brazo
    ```

4.  Correr el programa:

    ```bash
    sudo -E ~/venv-whisper/bin/python brazo_LCD.py
    ```

5.  Esperar a que arranque. En la LCD aparece primero "Bienvenido" con el mensaje "Hecho por Santiago Rodriguez" desplazándose, luego "Iniciando..." mientras se preparan el micrófono y los servos, y después "Cargando modelo de voz...". Esta última parte puede tardar un poco.

6.  Cuando aparezca el menú ("Enter: hablar" / "h:ayuda q:salir"), el brazo ya está listo para recibir comandos.

Al arrancar, cada servo se mueve a su posición inicial uno por uno, para no exigirle toda la corriente a la fuente de una sola vez.

## 5. Uso del sistema

El brazo se maneja con tres teclas y la voz. Cada vez que se presiona Enter, el programa graba 3 segundos, reconoce lo que se dijo y ejecuta el movimiento.

### 5.1 Teclas

| Tecla     | Qué hace                                                            |
|-----------|---------------------------------------------------------------------|
| Enter     | Inicia el conteo para hablar y graba el comando de voz.             |
| h + Enter | Muestra la ayuda con todos los comandos en la LCD y en la terminal. |
| q + Enter | Termina el programa. Los servos se quedan en su última posición.    |

### 5.2 Paso a paso para dar un comando

1.  Con el menú en pantalla, presionar **Enter**.

2.  La LCD muestra "Habla en..." con un conteo de 3, 2, 1.

3.  Aparece "Escuchando..." con una barra que se va llenando. Durante esos 3 segundos se dice el comando, claro y cerca del micrófono.

4.  Mientras el programa reconoce la voz, la LCD muestra "Preparando orden / espere...".

5.  Si entiende el comando, muestra "Orden detectada:" con el nombre del comando, y el brazo se mueve.

6.  A los 3 segundos la pantalla vuelve sola al menú y se puede dar el siguiente comando.

Si no entiende lo que se dijo, la LCD muestra "No reconocido:" con el texto que escuchó. Si no captó ningún sonido, muestra "No se escucho / intenta de nuevo". En los dos casos basta con presionar Enter otra vez.

### 5.3 Ayuda en la LCD

Como la LCD solo tiene 16 caracteres por línea, la ayuda muestra los comandos de dos en dos y cambia cada 3 segundos. Son 7 pantallas en total y al terminar vuelve al menú. Si se presiona Enter en medio de la ayuda, esta se corta y empieza de una vez el conteo para hablar.

## 6. Comandos de voz

El brazo reconoce 14 comandos, repartidos entre los 6 servos. Algunos llevan el servo a una posición fija y otros lo mueven unos grados desde donde esté en ese momento.

| Comando          | Servo (fila) | Movimiento                             | Grados                        |
|------------------|--------------|----------------------------------------|-------------------------------|
| girar derecha    | Base (1)     | Gira la base hacia la derecha          | +20° desde la posición actual |
| girar izquierda  | Base (1)     | Gira la base hacia la izquierda        | −20° desde la posición actual |
| centrar          | Base (1)     | Lleva la base al centro                | 90°                           |
| subir            | Hombro (2)   | Sube el hombro                         | +10° desde la posición actual |
| bajar            | Hombro (2)   | Baja el hombro                         | −10° desde la posición actual |
| extender         | Codo (3)     | Estira el codo al máximo               | 70°                           |
| retraer          | Codo (3)     | Recoge el codo                         | 30°                           |
| semiflexión      | Codo (3)     | Deja el codo a medio camino            | 50°                           |
| apuntar arriba   | Muñeca (4)   | Inclina la muñeca hacia arriba         | +10° desde la posición actual |
| apuntar abajo    | Muñeca (4)   | Inclina la muñeca hacia abajo          | −10° desde la posición actual |
| garra horizontal | Rotación (5) | Gira la garra a posición horizontal    | 90°                           |
| garra vertical   | Rotación (5) | Gira la garra a posición vertical      | 10°                           |
| abrir            | Agarre (6)   | Abre la garra                          | 80°                           |
| cerrar           | Agarre (6)   | Cierra la garra para agarrar el objeto | 150°                          |

No hace falta decir el comando completo: el programa también lo reconoce con la palabra principal, por ejemplo "derecha", "vertical" o "abrir". Todos los movimientos se hacen de forma suave, de a 2° por paso, para evitar golpes en la estructura y picos de corriente.

### 6.1 Posición inicial y límites

Al iniciar el programa cada servo va a una posición de arranque. Además, cada uno tiene un límite que el programa no deja pasar, para no forzar el servo ni la estructura:

| Servo (fila) | Posición inicial | Límite mínimo | Límite máximo |
|--------------|------------------|---------------|---------------|
| Base (1)     | 90°              | 0°            | 180°          |
| Hombro (2)   | 90°              | 0°            | 180°          |
| Codo (3)     | 30° (retraído)   | 0°            | 70°           |
| Muñeca (4)   | 90°              | 0°            | 180°          |
| Rotación (5) | 90° (horizontal) | 0°            | 180°          |
| Agarre (6)   | 80° (abierta)    | 0°            | 180°          |

Si un comando intenta pasar uno de estos límites (por ejemplo, decir "subir" varias veces seguidas), el servo se queda en el límite y la LCD muestra "Limite alcanzado" con el nombre del servo y el ángulo en el que quedó.

## 7. Recomendaciones y solución de problemas

### 7.1 Recomendaciones

- Hacer o cambiar las conexiones siempre con la Jetson y la fuente apagada.

- Alimentar los servos únicamente con la fuente externa. Si se alimentan desde la Jetson, esta se puede reiniciar o dañar.

- Hablar después de que aparezca "Escuchando...", no durante el conteo, y decir un solo comando a la vez.

- Evitar ruido fuerte cerca del micrófono, porque afecta el reconocimiento.

- El módulo de la LCD trabaja a 5 V, mientras que los pines I2C de la Jetson son de 3.3 V. Para protegerla, es mejor usar un conversor de nivel I2C o retirar las resistencias pull-up del módulo de la LCD.

### 7.2 Problemas comunes

| Problema                                   | Qué hacer                                                                                           |
|--------------------------------------------|-----------------------------------------------------------------------------------------------------|
| La LCD prende, pero no se ve texto         | Girar el potenciómetro azul de la parte de atrás del módulo para ajustar el contraste.              |
| La terminal dice "LCD no encontrada"       | Revisar que SDA esté en el pin 27 y SCL en el pin 28, y que `sudo i2cdetect -y -r 0` muestre 27.|
| La terminal dice "RPLCD no está conectada" | Instalar la librería en el entorno virtual: `~/venv-whisper/bin/python -m pip install RPLCD smbus2`|
| Los servos no se mueven                    | Revisar que la fuente externa esté encendida y que `sudo i2cdetect -y -r 1` muestre 40.|
| Sale "No reconocido" muy seguido           | Hablar más claro y más cerca del micrófono, y decir el comando completo.                            |
| Sale "No se escucho"                       | Revisar que el micrófono USB esté bien conectado y que la terminal muestre el micrófono al iniciar. |

Si la LCD falla o se desconecta, el programa sigue funcionando normalmente y muestra todo en la terminal, así que el brazo se puede seguir usando sin la pantalla.
