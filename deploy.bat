@echo off
REM StreamDock stores plugins under HotSpot (current versions) or Mirabox (older ones)
set PLUGINS_DIR=%APPDATA%\HotSpot\StreamDock\plugins
if not exist "%PLUGINS_DIR%" set PLUGINS_DIR=%APPDATA%\Mirabox\StreamDock\Plugins
if not exist "%PLUGINS_DIR%" (
    echo No se encontro la carpeta de plugins de StreamDock.
    pause
    exit /b 1
)

echo Copiando plugin a %PLUGINS_DIR%...
xcopy /E /I /Y "com.cgm.freestyle.sdPlugin" "%PLUGINS_DIR%\com.cgm.freestyle.sdPlugin"

if exist ".env" (
    echo Copiando .env...
    copy /Y ".env" "%PLUGINS_DIR%\com.cgm.freestyle.sdPlugin\.env" >nul
)

echo Listo. Reinicia StreamDock para cargar el plugin.
pause
