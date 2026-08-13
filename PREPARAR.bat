@echo off
REM ===========================================================================
REM  SGE - Sistema de Gestao Escolar
REM  Instalacao do zero. Rode UMA VEZ, depois use o INICIAR.bat.
REM
REM  Do computador limpo ao sistema funcionando: cria o ambiente, instala as
REM  dependencias, monta o banco, popula com uma escola de exemplo e cria as
REM  tres contas de teste.
REM ===========================================================================

cd /d "%~dp0"
title SGE - preparando a instalacao

echo.
echo   ===================================================
echo    SGE - preparando a instalacao
echo   ===================================================
echo.
echo   Leva alguns minutos na primeira vez.
echo.

REM --- 1. Python ------------------------------------------------------------
set PY=
py -3.12 --version >nul 2>&1 && set PY=py -3.12
if not defined PY ( python --version >nul 2>&1 && set PY=python )

if not defined PY (
  echo   [ERRO] Python nao encontrado.
  echo.
  echo   Instale o Python 3.12 em https://python.org/downloads
  echo   Marque "Add Python to PATH" durante a instalacao.
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('%PY% --version') do echo   [1/6] %%v

REM --- 2. Ambiente virtual --------------------------------------------------
if exist "venv\Scripts\python.exe" (
  echo   [2/6] Ambiente virtual ja existe
) else (
  echo   [2/6] Criando o ambiente virtual...
  %PY% -m venv venv
  if errorlevel 1 (
    echo   [ERRO] Falhou ao criar o ambiente virtual.
    pause
    exit /b 1
  )
)

REM --- 3. Dependencias ------------------------------------------------------
echo   [3/6] Instalando as dependencias...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\python.exe -m pip install -e ".[dev]" --quiet
if errorlevel 1 (
  echo   [ERRO] Falhou ao instalar as dependencias.
  echo   Verifique a conexao com a internet e rode de novo.
  pause
  exit /b 1
)

set FLASK_APP=run.py

REM --- 4. Banco de dados ----------------------------------------------------
REM `db upgrade` aplica as migrations em ordem, do banco vazio ate a versao
REM atual — o mesmo caminho que a escola percorreria num servidor novo.
echo   [4/6] Montando o banco de dados...
venv\Scripts\python.exe -m flask db upgrade >nul 2>&1
if errorlevel 1 (
  echo   [ERRO] Falhou ao aplicar as migrations.
  pause
  exit /b 1
)

REM --- 5. Escola de exemplo -------------------------------------------------
echo   [5/6] Criando a escola de exemplo...
venv\Scripts\python.exe -m flask criar-estrutura-inicial >nul 2>&1
venv\Scripts\python.exe -m flask popular-demonstracao --alunos 60 --yes >nul 2>&1

REM --- 6. Contas de teste ---------------------------------------------------
echo   [6/6] Criando as contas de teste...
venv\Scripts\python.exe scripts\criar_contas_de_teste.py 2>nul | findstr /v "^$"

echo.
echo   ===================================================
echo    Pronto.
echo.
echo    Agora e so dar um duplo clique em  INICIAR.bat
echo.
echo    Contas  (senha: 1234)
echo      adm@gmail.com      administrador
echo      prof@gmail.com     professor
echo      aluno@gmail.com    aluno
echo   ===================================================
echo.
pause
