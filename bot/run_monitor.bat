@echo off
REM Daily Command F monitor (Task Scheduler). Horizon 21d so Cepeda (Jun 21)
REM stays in range; includes real-money positions; logs to monitor_daily.log.
cd /d C:\Signal\bot
echo ==== %DATE% %TIME% ==== >> monitor_daily.log
set SIGNAL_COMMAND_F_HORIZON_DAYS=21
set PYTHONIOENCODING=utf-8
python run_command_f.py >> monitor_daily.log 2>&1
echo exit=%ERRORLEVEL% >> monitor_daily.log
