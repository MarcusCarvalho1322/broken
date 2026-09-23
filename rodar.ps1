# rodar.ps1 — processa as conversas extraidas (cofre + metricas + treino + forense + dashboard)
# Uso: .\rodar.ps1
$ErrorActionPreference = "Continue"

if (-not $env:BIZZ_MASTER_KEY_FILE) {
    $env:BIZZ_MASTER_KEY_FILE = "$PWD\master.key"
    Write-Host "BIZZ_MASTER_KEY_FILE definida para $env:BIZZ_MASTER_KEY_FILE" -ForegroundColor Cyan
}

Write-Host "`n[1/6] Anonimizando..." -ForegroundColor Yellow
python anonimizador.py --clinica clin_demo --entrada conversas.jsonl --vault ./vault --metricas ./metrics

Write-Host "`n[2/6] Gerando pares de treino..." -ForegroundColor Yellow
python treino_export.py --clinica clin_demo --vault ./vault --out ./train

Write-Host "`n[3/6] Verificando integridade do cofre..." -ForegroundColor Yellow
python cofre.py verify --clinica clin_demo --vault ./vault

Write-Host "`n[4/6] Motor Forense (Core Engine v3.1 - parametrico)..." -ForegroundColor Yellow
python motor_forense.py --clinica clin_demo --vault ./vault --metrics ./metrics --out ./forense

Write-Host "`n[5/6] Gerando dashboard..." -ForegroundColor Yellow
python gerar_dashboard.py --clinica clin_demo --metrics ./metrics --vault ./vault --logo ./assets/logo.png --template ./dashboard_template.html --saida ./dashboard_bizzia.html

Write-Host "`n[6/6] Resumo:" -ForegroundColor Yellow
if (Test-Path "metrics\clin_demo\conversas.jsonl") {
    $n = (Get-Content "metrics\clin_demo\conversas.jsonl").Count
    Write-Host "  conversas com metricas: $n" -ForegroundColor Green
}
if (Test-Path "train\clin_demo\pares.jsonl") {
    $p = (Get-Content "train\clin_demo\pares.jsonl").Count
    Write-Host "  pares de treino: $p" -ForegroundColor Green
}
if (Test-Path "forense\telemetria.json") {
    Write-Host "  motor forense: forense\telemetria.json + dossie_direcao.md + dossie_equipe.md" -ForegroundColor Green
}
if (Test-Path "dashboard_bizzia.html") {
    Write-Host "  dashboard: dashboard_bizzia.html (abra no navegador)" -ForegroundColor Green
}
Write-Host ""
