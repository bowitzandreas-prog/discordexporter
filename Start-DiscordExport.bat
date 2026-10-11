@echo off
rem Startet die Oberfläche von Discord-Export. Doppelklick genügt.
cd /d "%~dp0"
py -3 discord_export.py %*
if errorlevel 1 pause
