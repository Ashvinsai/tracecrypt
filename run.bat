@echo off
cd /d "%~dp0"
python launch.py --prepare --with-worker %*
