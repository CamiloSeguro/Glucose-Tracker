@echo off
echo Instalando dependencias...
pip install -r requirements.txt

echo Compilando con PyInstaller...
pyinstaller --onefile --name main --distpath "com.cgm.freestyle.sdPlugin" ^
  --hidden-import PIL ^
  --hidden-import PIL.ImageFont ^
  --hidden-import PIL._imaging ^
  main.py

echo Listo. El plugin esta en com.cgm.freestyle.sdPlugin\main.exe
pause
