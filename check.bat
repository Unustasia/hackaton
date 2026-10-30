@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py
if "%PY%"=="" where python >nul 2>nul && set PY=python
if "%PY%"=="" (
  echo [ !! ] Python не найден на этом компьютере.
  echo Скачайте его на https://www.python.org/downloads/ и при установке поставьте галочку Add Python to PATH.
  pause
  exit /b 1
)
echo Найден запуск Python: %PY%
%PY% check_setup.py
echo.
pause
