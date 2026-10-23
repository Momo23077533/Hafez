@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Hafez Matcher

set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" where python >nul 2>nul && set PY=python
if "%PY%"=="" (
  echo.
  echo [X] Python is not installed.
  echo     Download it from https://www.python.org/downloads/
  echo     IMPORTANT: tick "Add python.exe to PATH" on the first screen, then run this file again.
  echo.
  pause
  exit /b 1
)

if not exist "venv\ok.txt" (
  echo First run: setting things up. This can take a few minutes and needs internet.
  %PY% -m venv venv || goto :err
  call venv\Scripts\activate.bat
  python -m pip install --upgrade pip -q
  pip install -r requirements.txt || goto :err
  echo ok> venv\ok.txt
) else (
  call venv\Scripts\activate.bat
)

if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  >"%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >>"%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo.
echo The app is starting and will open in your browser.
echo Keep this black window open while you use the app. Close it when you are done.
echo.
streamlit run app.py
pause
exit /b 0

:err
echo.
echo [X] Setup failed. Check your internet connection and try again.
pause
exit /b 1
