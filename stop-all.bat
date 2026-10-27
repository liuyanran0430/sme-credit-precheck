@echo off
chcp 65001 >nul
setlocal EnableExtensions
title 小微企业授信智能预审系统 - 停止服务

rem ============================================================
rem  关闭前端 Vite 与后端 FastAPI 服务
rem  用法：stop-all.bat [后端端口] [前端端口]
rem  示例：stop-all.bat 8000 5173
rem  说明：MySQL 服务不会被关闭
rem ============================================================

set "BACKEND_PORT=%~1"
set "FRONTEND_PORT=%~2"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8000"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5173"

echo.
echo ============================================================
echo   小微企业授信智能预审系统 - 停止服务
echo ============================================================

echo.
echo [1/2] 关闭前端 Vite
taskkill /FI "WINDOWTITLE eq 前端 Vite" /T /F >nul 2>&1
if not errorlevel 1 (
    echo   [OK] 已关闭前端窗口及其进程
) else (
    echo   未找到前端服务窗口，尝试按端口关闭...
)
timeout /t 1 /nobreak >nul
call :stop_port %FRONTEND_PORT% 前端 node.exe
call :check_port %FRONTEND_PORT% 前端

echo.
echo [2/2] 关闭后端 FastAPI
taskkill /FI "WINDOWTITLE eq 后端 FastAPI" /T /F >nul 2>&1
if not errorlevel 1 (
    echo   [OK] 已关闭后端窗口及其进程
) else (
    echo   未找到后端服务窗口，尝试按端口关闭...
)
timeout /t 1 /nobreak >nul
call :stop_port %BACKEND_PORT% 后端 python.exe
call :check_port %BACKEND_PORT% 后端

echo.
echo 前端与后端服务已停止，MySQL 未受影响。
pause
exit /b 0

rem ------------------------------------------------------------ 子过程
:stop_port
set "SP_PORT=%~1"
set "SP_NAME=%~2"
set "SP_IMAGE=%~3"

for /f "tokens=5" %%P in ('netstat -ano -p TCP ^| findstr /r /c:":%SP_PORT% .*LISTENING"') do (
    tasklist /FI "PID eq %%P" /NH | findstr /i "%SP_IMAGE%" >nul
    if not errorlevel 1 (
        echo   正在结束 %SP_NAME% 进程，PID=%%P
        taskkill /PID %%P /T /F >nul 2>&1
    )
)

exit /b 0

:check_port
timeout /t 1 /nobreak >nul
netstat -ano -p TCP | findstr /r /c:":%~1 .*LISTENING" >nul
if errorlevel 1 (
    echo   [OK] 端口 %~1 已释放
) else (
    echo   [WARN] 端口 %~1 仍被占用，请手动检查。
)
exit /b 0
