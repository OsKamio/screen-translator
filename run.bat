@echo off
rem 屏幕翻译 - Windows 一键启动
rem 优先使用项目内 .venv；否则使用系统 python。
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

%PY% main.py
if errorlevel 1 (
    echo.
    echo 启动失败。请先安装依赖：
    echo   1) python -m venv .venv
    echo   2) .venv\Scripts\python -m pip install -r requirements.txt
    echo   (Python 3.13 安装时请加 --ignore-requires-python)
    pause
)
