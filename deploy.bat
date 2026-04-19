@echo off
set PLUGINS_DIR=%APPDATA%\Mirabox\StreamDock\Plugins

echo Copiando plugin a %PLUGINS_DIR%...
xcopy /E /I /Y "com.cgm.freestyle.sdPlugin" "%PLUGINS_DIR%\com.cgm.freestyle.sdPlugin"

echo Listo. Reinicia StreamDock para cargar el plugin.
pause
