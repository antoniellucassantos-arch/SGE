@echo off
REM ===========================================================================
REM  SGE - Sistema de Gestao Escolar
REM  Duplo clique aqui para subir o sistema.
REM
REM  A janela preta que abrir E o servidor: enquanto ela estiver aberta, o
REM  sistema esta no ar. Fechar a janela derruba o sistema.
REM ===========================================================================

cd /d "%~dp0"
title SGE - servidor (nao feche esta janela)

echo.
echo   ===================================================
echo    SGE - Sistema de Gestao Escolar
echo   ===================================================
echo.

REM --- O ambiente virtual existe? -------------------------------------------
if not exist "venv\Scripts\python.exe" (
  echo   [ERRO] Ambiente virtual nao encontrado em venv\
  echo.
  echo   Para criar, abra o Prompt de Comando nesta pasta e rode:
  echo       python -m venv venv
  echo       venv\Scripts\pip install -e ".[dev]"
  echo.
  pause
  exit /b 1
)

REM --- A porta 5000 ja esta ocupada? ----------------------------------------
REM Duas copias do servidor na mesma porta e a causa mais comum de "abri e
REM nao carregou": a segunda morre em silencio e a primeira pode estar velha.
netstat -ano | findstr /r /c:"TCP.*:5000 .*LISTENING" >nul
if not errorlevel 1 (
  echo   [AVISO] Ja existe algo rodando na porta 5000.
  echo.
  echo   Provavelmente o sistema ja esta no ar. Abra:
  echo       http://localhost:5000
  echo.
  echo   Se nao carregar, feche a outra janela preta e rode este arquivo
  echo   de novo.
  echo.
  pause
  exit /b 1
)

REM --- Diagnostico rapido ---------------------------------------------------
echo   Conferindo a instalacao...
echo.
set FLASK_APP=run.py
venv\Scripts\python.exe -m flask verificar-saude 2>nul | findstr /c:"[ok]" /c:"[aviso]" /c:"[falha]"

echo.
echo   ===================================================
echo    Abra no navegador:  http://localhost:5000
echo.
echo    Contas de teste  (senha: 1234)
echo      adm@gmail.com      administrador
echo      prof@gmail.com     professor
echo      aluno@gmail.com    aluno
echo   ===================================================
echo.
echo   Para parar: feche esta janela ou aperte Ctrl+C
echo.

REM Abre o navegador sozinho, com uma folga para o servidor levantar.
REM O `ping` faz a pausa: `timeout` nao existe em toda instalacao do Windows
REM e, quando o Git esta no PATH, pode cair na versao do Unix, que recusa os
REM argumentos e some com a pausa.
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul & start http://localhost:5000"

venv\Scripts\python.exe run.py

echo.
echo   Servidor encerrado.
pause
