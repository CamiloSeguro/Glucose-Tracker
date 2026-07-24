# Glucose Tracker — CGM FreeStyle StreamDock Plugin

Plugin para [StreamDock](https://www.mirabox.com/) (VSDinside) que muestra en tiempo real el nivel de glucosa de un sensor **FreeStyle Libre 2 Plus**, obtenido a través de la API de **LibreLinkUp**.

El botón se actualiza automáticamente cada minuto y muestra:

- Valor de glucosa en mg/dL
- Flecha de tendencia (subiendo, bajando, estable, etc.)
- Color según el rango: verde (normal), ámbar (alto) o rojo (bajo)

## Requisitos

- Windows 10 o superior
- Python 3.10+ (solo para desarrollo/compilación)
- Software StreamDock instalado
- Una cuenta de LibreLinkUp vinculada a un sensor FreeStyle Libre 2 Plus

## Configuración

1. Copia `.env.example` a `.env` y completa tus credenciales de LibreLinkUp:

   ```
   LLU_EMAIL=tu_email@ejemplo.com
   LLU_PASSWORD=tu_contraseña
   ```

2. El archivo `.env` debe quedar junto al ejecutable del plugin (`com.cgm.freestyle.sdPlugin/main.exe`) o junto a `main.py` en modo desarrollo.

## Compilar y desplegar

```bat
build.bat    REM instala dependencias y compila main.py con PyInstaller
deploy.bat   REM copia el plugin compilado a la carpeta de plugins de StreamDock
```

`build.bat` genera `com.cgm.freestyle.sdPlugin/main.exe`. `deploy.bat` lo copia a `%APPDATA%\Mirabox\StreamDock\Plugins`.

## Estructura del proyecto

```
main.py                          Punto de entrada del plugin
librelinkup/client.py            Cliente HTTP para la API de LibreLinkUp (login, cache de token, lectura de glucosa)
src/core/plugin.py               Conexión WebSocket con StreamDock y enrutado de eventos
src/core/action.py               Clase base para acciones (botones)
src/core/action_factory.py       Registro y creación de instancias de acciones
src/core/timer.py                Temporizador simple para el polling periódico
src/core/logger.py               Logging a archivo y consola
src/actions/glucose_action.py    Acción "Glucosa": polling, render del ícono y estados de error
com.cgm.freestyle.sdPlugin/      Manifiesto y recursos del plugin para StreamDock
```

## Cómo funciona

1. StreamDock lanza `main.exe` y se conecta por WebSocket local (`ws://127.0.0.1:<port>`).
2. Al aparecer el botón (`willAppear`), el plugin inicia sesión en LibreLinkUp y comienza a consultar la última lectura de glucosa cada 60 segundos.
3. El token de sesión se cachea localmente (`.llu_token_cache.json`) para evitar reautenticar en cada reinicio.
4. Cada lectura se renderiza como una imagen (anillo de color + valor + flecha de tendencia) y se envía al botón vía `setImage`.

## Notas

- Las credenciales y el cache de token nunca se versionan (ver `.gitignore`).
- Si no se detectan `LLU_EMAIL` / `LLU_PASSWORD`, el botón muestra "Sin config".
