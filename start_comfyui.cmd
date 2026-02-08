@echo off
setlocal enabledelayedexpansion

set "COMFYUI_DIR=D:\ComfyUI"
set "PYTHON_EXE=%COMFYUI_DIR%\venv\Scripts\python.exe"
set "MAIN_PY=%COMFYUI_DIR%\main.py"
set "HOST=127.0.0.1"
set "PORT=8188"

if not exist "%COMFYUI_DIR%" (
  echo ОШИБКА: ComfyUI не найден: %COMFYUI_DIR%
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo ОШИБКА: Python venv не найден: %PYTHON_EXE%
  echo Запусти один раз:  py -3.11 -m venv "D:\ComfyUI\venv"  и  "D:\ComfyUI\venv\Scripts\python.exe" -m pip install -U -r "D:\ComfyUI\requirements.txt"
  exit /b 1
)

if not exist "%MAIN_PY%" (
  echo ОШИБКА: main.py не найден: %MAIN_PY%
  exit /b 1
)

cd /d "%COMFYUI_DIR%"
start "ComfyUI" "%PYTHON_EXE%" "%MAIN_PY%" --listen %HOST% --port %PORT%
echo ComfyUI запущен: http://%HOST%:%PORT%/
exit /b 0
