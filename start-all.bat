@echo off
chcp 65001 >nul
setlocal EnableExtensions
title 小微企业授信智能预审系统 - 一键启动

rem ============================================================
rem  一键启动 MySQL、后端 FastAPI、前端 Vite
rem  用法：start-all.bat [MySQL服务名] [后端端口] [前端端口]
rem  示例：start-all.bat MySQL 8000 5173
rem ============================================================

set "ROOT=%~dp0"
set "BACKEND=%ROOT%sme-credit-precheck-backend"
set "FRONTEND=%ROOT%sme-credit-precheck-web"
set "PYTHON=%BACKEND%\.venv\Scripts\python.exe"

set "MYSQL_SERVICE=%~1"
set "BACKEND_PORT=%~2"
set "FRONTEND_PORT=%~3"
set "MYSQL_PORT=3306"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8000"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5173"

echo.
echo ============================================================
echo   小微企业授信智能预审系统 - 一键启动
echo ============================================================

echo.
echo [检查] 项目目录
call :check_dir "%BACKEND%" 后端
if errorlevel 1 goto :fatal
call :check_dir "%FRONTEND%" 前端
if errorlevel 1 goto :fatal

rem ------------------------------------------------------------ MySQL
echo.
echo [1/3] 启动 MySQL
if not "%MYSQL_SERVICE%"=="" goto :mysql_check

for %%S in (MySQL MySQL80 MySQL57 MySQL84 MySQL56 mariadb) do (
    sc query "%%S" >nul 2>&1
    if not errorlevel 1 (
        set "MYSQL_SERVICE=%%S"
        goto :mysql_check
    )
)
echo   [WARN] 未找到 MySQL 服务，请手动启动 MySQL。
goto :mysql_ready

:mysql_check
sc query "%MYSQL_SERVICE%" | findstr /i "RUNNING" >nul
if not errorlevel 1 (
    echo   [OK] MySQL 服务已在运行：%MYSQL_SERVICE%
    goto :mysql_wait
)
echo   正在启动 MySQL 服务：%MYSQL_SERVICE%
net start "%MYSQL_SERVICE%" >nul 2>&1
if errorlevel 1 (
    echo   [WARN] 启动失败，请右键“以管理员身份运行”本脚本。
) else (
    echo   [OK] MySQL 服务已启动
)

:mysql_wait
call :wait_port %MYSQL_PORT% 30
if errorlevel 1 (
    echo   [WARN] 端口 %MYSQL_PORT% 未监听，后端可能无法连接数据库。
) else (
    echo   [OK] MySQL 端口 %MYSQL_PORT% 已就绪
)

:mysql_ready
if not exist "%BACKEND%\.env" (
    echo   [WARN] 未找到后端 .env，将使用默认连接串（root:920430@127.0.0.1:%MYSQL_PORT%/sme_credit）。
    echo          如账号密码不同，请复制 .env.example 为 .env 并修改 DATABASE_URL。
)

rem ------------------------------------------------------------ 后端
echo.
echo [2/3] 启动后端 FastAPI
if exist "%PYTHON%" goto :backend_ready

echo   未找到虚拟环境 .venv，正在创建并安装依赖...
python -m venv "%BACKEND%\.venv"
if errorlevel 1 goto :backend_fail
"%PYTHON%" -m pip install -r "%BACKEND%\requirements.txt"
if errorlevel 1 goto :backend_fail

:backend_ready
call :is_port_open %BACKEND_PORT%
if not errorlevel 1 (
    echo   [WARN] 端口 %BACKEND_PORT% 已被占用，跳过后端启动。
    goto :backend_done
)

start "后端 FastAPI" /D "%BACKEND%" cmd /k ""%PYTHON%" -m uvicorn app.main:app --reload --host 0.0.0.0 --port %BACKEND_PORT%"
call :wait_port %BACKEND_PORT% 40
if errorlevel 1 (
    echo   [WARN] 后端启动超时，请查看新打开的窗口日志。
) else (
    echo   [OK] 后端已启动：http://127.0.0.1:%BACKEND_PORT%
)

:backend_done

rem ------------------------------------------------------------ 前端
echo.
echo [3/3] 启动前端 Vite
if exist "%FRONTEND%\node_modules" goto :frontend_ready

echo   未找到 node_modules，正在安装前端依赖...
pushd "%FRONTEND%"
call npm install
if errorlevel 1 (
    popd
    echo   [WARN] 前端依赖安装失败，跳过前端启动。
    goto :frontend_done
)
popd

:frontend_ready
call :is_port_open %FRONTEND_PORT%
if not errorlevel 1 (
    echo   [WARN] 端口 %FRONTEND_PORT% 已被占用，跳过前端启动。
    goto :frontend_done
)

start "前端 Vite" /D "%FRONTEND%" cmd /k "npm run dev -- --port %FRONTEND_PORT%"
call :wait_port %FRONTEND_PORT% 60
if errorlevel 1 (
    echo   [WARN] 前端启动超时，请查看新打开的窗口日志。
) else (
    echo   [OK] 前端已启动：http://localhost:%FRONTEND_PORT%
)

:frontend_done

rem ------------------------------------------------------------ 汇总
echo.
echo ============================================================
echo   启动完成
echo     前端页面  http://localhost:%FRONTEND_PORT%
echo     后端服务  http://127.0.0.1:%BACKEND_PORT%
echo     接口文档  http://127.0.0.1:%BACKEND_PORT%/docs
echo.
echo   首次使用请先初始化数据库：
echo     mysql -u root -p ^< sme-credit-precheck-backend\db\mysql\schema.sql
echo   关闭本窗口不会停止服务，请在各自窗口按 Ctrl+C 结束。
echo ============================================================
echo.
start "" "http://localhost:%FRONTEND_PORT%"
pause
exit /b 0

rem ------------------------------------------------------------ 子过程
:check_dir
if exist "%~1\" (
    echo   [OK] %~2目录：%~1
    exit /b 0
)
echo   [ERROR] 目录不存在：%~1
exit /b 1

:is_port_open
netstat -an | findstr /c:":%~1" | findstr /i "LISTENING" >nul
if errorlevel 1 exit /b 1
exit /b 0

:wait_port
set "WP_PORT=%~1"
set "WP_TRIES=%~2"
for /L %%i in (1,1,%WP_TRIES%) do (
    netstat -an | findstr /c:":%WP_PORT%" | findstr /i "LISTENING" >nul
    if not errorlevel 1 exit /b 0
    timeout /t 1 /nobreak >nul
)
exit /b 1

rem ------------------------------------------------------------ 异常退出
:backend_fail
echo   [ERROR] 后端虚拟环境或依赖安装失败。
goto :fatal

:fatal
echo.
echo 启动失败，请根据上方提示排查后重试。
pause
exit /b 1
