@echo off

call .venv\scripts\activate
python main.py %*

echo "launching the server"
pause
