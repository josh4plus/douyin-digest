@echo off
REM Windows 启动器：等价于 Unix 上的 dy-digest。
REM 依赖 Git Bash 或 WSL 跑过的 setup.sh（venv 里要有 faster-whisper）。
setlocal
set "HERE=%~dp0"
set "PYBIN=%USERPROFILE%\.venvs\dy-digest\Scripts\python.exe"
if not exist "%PYBIN%" (
  echo 找不到 venv：%PYBIN%
  echo 先在 Git Bash 里跑一次 setup.sh
  exit /b 1
)
"%PYBIN%" "%HERE%dy.py" %*
