@echo off
REM Uso: build.bat          (local, espera una tecla al terminar)
REM      build.bat --ci     (sin pausa; lo usa GitHub Actions)

REM "python" can be the empty Microsoft Store alias; fall back to the py launcher
set PY=python
python -c "" >nul 2>&1 || set PY=py

echo Instalando dependencias...
%PY% -m pip install -r requirements.txt || goto :fail

echo Ejecutando tests...
%PY% -m unittest discover -s tests -t . || goto :fail

echo Compilando con PyInstaller...
%PY% -m PyInstaller --noconfirm --onefile --name main --distpath "com.cgm.freestyle.sdPlugin" ^
  --hidden-import PIL ^
  --hidden-import PIL.ImageFont ^
  --hidden-import PIL._imaging ^
  main.py || goto :fail

echo Listo. El plugin esta en com.cgm.freestyle.sdPlugin\main.exe
if not "%1"=="--ci" pause
exit /b 0

:fail
echo ERROR: la compilacion fallo.
if not "%1"=="--ci" pause
exit /b 1
