@echo off
REM ==========================================================================
REM  富化数据每周刷新（Windows 计划任务入口）
REM    * 距上次刷新不足 7 天时自动跳过（run_update_factors.py --if-stale）
REM    * 输出追加到 logs\update_factors_weekly.log
REM
REM  注册计划任务（每周一 02:00，管理员 PowerShell / CMD 执行一次即可）:
REM    schtasks /Create /TN "ABM_UpdateFactors" /SC WEEKLY /D MON /ST 02:00 ^
REM      /TR "cmd /c cd /d F:\ai_backtest_model && scripts\update_factors_weekly.bat"
REM
REM  手动触发:
REM    schtasks /Run /TN "ABM_UpdateFactors"
REM  删除:
REM    schtasks /Delete /TN "ABM_UpdateFactors" /F
REM ==========================================================================
setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
echo. >> "logs\update_factors_weekly.log"
python run_update_factors.py --if-stale >> "logs\update_factors_weekly.log" 2>&1
echo [%date% %time%] run_update_factors exit=%ERRORLEVEL% >> "logs\update_factors_weekly.log"
endlocal
