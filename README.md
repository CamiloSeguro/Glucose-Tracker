# Glucose Tracker — CGM FreeStyle StreamDock Plugin

Plugin para [StreamDock](https://www.mirabox.com/) (VSDinside) que muestra en tiempo real el nivel de glucosa de un sensor **FreeStyle Libre 2 Plus**, obtenido a través de la API de **LibreLinkUp**.

El botón se actualiza cada minuto y muestra:

- Valor de glucosa en mg/dL o mmol/L, coloreado según el rango: rojo intenso (muy baja), rojo (baja), verde (en rango), ámbar (alta) o naranja (muy alta)
- Flecha de tendencia y cambio en los últimos 5 minutos (`+6`, `-0.3`)
- Gráfica de las últimas 3 horas con la franja objetivo marcada
- La lectura en gris con "hace Xm" si tiene más de 15 minutos

**Pulsar** el botón refresca al momento. **Mantenerlo pulsado** muestra durante 6 s un resumen: porcentaje de tiempo en rango de las últimas 12 h, mínimo y máximo de las últimas 3 h.

### Alertas

Con las notificaciones activadas, el plugin avisa con una notificación de Windows cuando la glucosa está baja, cae rápido o está muy alta. En **muy baja** el botón parpadea y suena una alarma en bucle hasta que se descarta. Cada tipo de alerta se repite con un intervalo mínimo (5 min en muy baja, 15 min en baja o caída rápida, 60 min en muy alta) y se reinicia al volver a un valor seguro. Las lecturas de más de 15 minutos no disparan alertas.

## Requisitos

- Windows 10 o superior
- Software StreamDock instalado
- Una cuenta de LibreLinkUp vinculada a un sensor FreeStyle Libre 2 Plus
- Python 3.10+ (solo para compilar)

## Configuración

Selecciona el botón en StreamDock para abrir su panel de configuración:

- **Cuenta LibreLinkUp**: email y contraseña. La contraseña se guarda cifrada con tu usuario de Windows (DPAPI), nunca en texto plano. El panel muestra si la conexión funciona.
- **Persona**: si tu cuenta sigue a varias personas, cada botón puede mostrar una distinta.
- **Unidades y rangos**: mg/dL o mmol/L y los cuatro umbrales (por defecto 54 / 70 / 180 / 250 mg/dL).
- **Notificaciones de Windows**: activa o desactiva las alertas.

Como alternativa, se puede usar un archivo `.env` junto a `main.exe` (ver `.env.example`). Las credenciales del panel tienen prioridad.

### Mensajes del botón

| Mensaje | Qué significa |
|---|---|
| Sin config | No hay credenciales. Configúralas en el panel. |
| Clave mala | LibreLinkUp rechazó el email o la contraseña. El plugin deja de reintentar solo durante 30 min, porque LibreLinkUp bloquea la cuenta 5 min tras 3 fallos. Corrígela y pulsa el botón. |
| Bloqueado | La cuenta está bloqueada temporalmente; el plugin espera a que termine el bloqueo. |
| Acepta T&C | Abre la app LibreLinkUp y acepta los nuevos términos. |
| Error API | Error de red o del servidor; se reintenta en el siguiente ciclo. |

## Compilar e instalar

```bat
build.bat    REM instala dependencias, ejecuta los tests y compila main.py con PyInstaller
deploy.bat   REM copia el plugin a la carpeta de plugins de StreamDock
```

`deploy.bat` copia a `%APPDATA%\HotSpot\StreamDock\plugins` (o a `%APPDATA%\Mirabox\StreamDock\Plugins` en versiones antiguas) e incluye el `.env` de la raíz si existe. Reinicia StreamDock después de instalar.

Cada push a `main` compila y prueba el plugin en GitHub Actions. Al publicar un tag `v*` se crea una release con el zip del plugin.

Para regenerar los iconos: `python tools/make_icons.py`.

## Tests

```bat
python -m unittest discover -s tests -t .
```

## Estructura del proyecto

```
main.py                          Punto de entrada del plugin
librelinkup/client.py            Cliente de la API de LibreLinkUp: login por región, cache de token, lecturas e historial
src/core/                        Conexión WebSocket con StreamDock, acciones, timer, logging, .env y cifrado DPAPI
src/glucose/service.py           Sesión y sondeo compartidos por todos los botones, backoff ante errores de login
src/glucose/history.py           Historial combinado, delta a 5 min y tiempo en rango
src/glucose/alerts.py            Reglas de alerta y notificaciones de Windows
src/glucose/render.py            Dibujo de los botones (valor, flecha, gráfica, resumen, errores)
src/glucose/settings.py          Unidades y umbrales
src/actions/glucose_action.py    Acción "Glucosa": pulsaciones, parpadeo y panel de configuración
com.cgm.freestyle.sdPlugin/      Manifiesto, panel de configuración e iconos
tests/                           Tests unitarios
```

## Notas

- Las credenciales, el cache de token y los logs nunca se versionan (ver `.gitignore`).
- Los logs están en `logs/plugin.log` junto a `main.exe` (rotación a 1 MB, 3 archivos).
- LibreLinkUp publica el historial con unos 15–30 minutos de retraso. El delta aparece unos 3 minutos después de arrancar, cuando el plugin ya tiene lecturas propias.
