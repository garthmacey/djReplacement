@echo off
setlocal

if not exist .venv (
    py -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pyinstaller --noconfirm --onefile --windowed --name DJReplacement app.py

echo.
echo Built dist\DJReplacement.exe
