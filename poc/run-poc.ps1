<#
.SYNOPSIS
    FCP PoC 백엔드(FastAPI) + 프론트엔드(정적 서버) 통합 실행 스크립트

.DESCRIPTION
    poc/backend(uvicorn :8085)과 poc/frontend(http.server :8086)을 한 번에 기동/종료/상태확인합니다.

.PARAMETER Action
    Start  : 백엔드+프론트엔드 백그라운드 기동 (기본값)
    Stop   : 실행 중인 두 프로세스 종료
    Status : 헬스체크 및 PID 확인
    Logs   : 백엔드/프론트엔드 로그 tail 보기

.PARAMETER BackendPort
    백엔드 FastAPI 포트 (기본 8085, frontend/app.js의 API_BASE와 일치해야 함)

.PARAMETER FrontendPort
    프론트엔드 정적 서버 포트 (기본 8086)

.PARAMETER ApiKey
    FED_API_KEY 환경 변수 값 (선택). 지정 시 /api 라우트에 X-FED-API-Key 헤더 강제

.EXAMPLE
    .\run-poc.ps1
    .\run-poc.ps1 -Action Status
    .\run-poc.ps1 -Action Stop
    .\run-poc.ps1 -ApiKey "my_secret"
#>
[CmdletBinding()]
param(
    [ValidateSet("Start", "Stop", "Status", "Logs")]
    [string]$Action = "Start",

    [int]$BackendPort = 8085,
    [int]$FrontendPort = 8086,
    [string]$ApiKey = ""
)

# 경로 설정
$ScriptDir   = $PSScriptRoot
$BackendDir  = Join-Path $ScriptDir "backend"
$FrontendDir = Join-Path $ScriptDir "frontend"
$LogDir      = Join-Path $ScriptDir ".run-logs"
$PidFile     = Join-Path $LogDir "pids.json"
$BackendLog  = Join-Path $LogDir "backend.log"
$FrontendLog = Join-Path $LogDir "frontend.log"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

function Get-PortPid([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        return $conn.OwningProcess | Select-Object -First 1
    } catch {
        return $null
    }
}

function Test-Health {
    Write-Host "[Health] 백엔드 /healthz 검사..." -ForegroundColor Cyan
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$BackendPort/healthz" -UseBasicParsing -TimeoutSec 5
        Write-Host "  -> $($r.StatusCode) $($r.Content)" -ForegroundColor Green
    } catch {
        Write-Host "  -> 실패: $_" -ForegroundColor Red
    }

    Write-Host "[Health] 프론트엔드 index.html 검사..." -ForegroundColor Cyan
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$FrontendPort/index.html" -UseBasicParsing -TimeoutSec 5
        Write-Host "  -> $($r.StatusCode) OK" -ForegroundColor Green
    } catch {
        Write-Host "  -> 실패: $_" -ForegroundColor Red
    }
}

function Start-Services {
    # 포트 충돌 확인
    foreach ($p in @($BackendPort, $FrontendPort)) {
        $existing = Get-PortPid -Port $p
        if ($existing) {
            Write-Host "[오류] 포트 $p 가 이미 PID $existing 에 의해 점유 중입니다. 먼저 -Action Stop 으로 종료하세요." -ForegroundColor Red
            return
        }
    }

    # 백엔드 기동
    Write-Host "[Start] 백엔드 uvicorn 기동 (port $BackendPort)..." -ForegroundColor Yellow
    $env:FED_API_KEY = $ApiKey
    $backendProc = Start-Process -FilePath "python" `
        -ArgumentList @("-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "$BackendPort") `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $BackendLog `
        -RedirectStandardError "$BackendLog.err" `
        -WindowStyle Hidden -PassThru

    # 프론트엔드 기동
    Write-Host "[Start] 프론트엔드 http.server 기동 (port $FrontendPort)..." -ForegroundColor Yellow
    $frontendProc = Start-Process -FilePath "python" `
        -ArgumentList @("-m", "http.server", "$FrontendPort") `
        -WorkingDirectory $FrontendDir `
        -RedirectStandardOutput $FrontendLog `
        -RedirectStandardError "$FrontendLog.err" `
        -WindowStyle Hidden -PassThru

    # PID 저장
    @{
        backend  = $backendProc.Id
        frontend = $frontendProc.Id
        started  = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8

    Write-Host "[Start] PID 저장: backend=$($backendProc.Id), frontend=$($frontendProc.Id)" -ForegroundColor Green

    # 초기 부팅 대기 후 헬스체크
    Start-Sleep -Seconds 2
    Test-Health

    Write-Host ""
    Write-Host "대시보드 접속: http://localhost:$FrontendPort/index.html" -ForegroundColor Magenta
    Write-Host "API 문서:      http://localhost:$BackendPort/docs"        -ForegroundColor Magenta
    Write-Host "종료:          .\run-poc.ps1 -Action Stop"                 -ForegroundColor DarkGray
}

function Stop-Services {
    if (-not (Test-Path $PidFile)) {
        Write-Host "[Stop] PID 파일이 없습니다. 포트 기반으로 종료 시도합니다." -ForegroundColor Yellow
        foreach ($p in @($BackendPort, $FrontendPort)) {
            $procId = Get-PortPid -Port $p
            if ($procId) {
                try {
                    Stop-Process -Id $procId -Force -ErrorAction Stop
                    Write-Host "[Stop] 포트 $p (PID $procId) 종료" -ForegroundColor Green
                } catch {
                    Write-Host "[Stop] 포트 $p PID $procId 종료 실패: $_" -ForegroundColor Red
                }
            }
        }
        return
    }

    $pids = Get-Content $PidFile -Raw | ConvertFrom-Json
    foreach ($name in @("backend", "frontend")) {
        $procId = $pids.$name
        if ($procId) {
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-Host "[Stop] $name (PID $procId) 종료" -ForegroundColor Green
            } catch {
                Write-Host "[Stop] $name PID $procId 이미 종료되었거나 실패: $_" -ForegroundColor Yellow
            }
        }
    }
    Remove-Item $PidFile -Force
}

function Show-Status {
    if (Test-Path $PidFile) {
        Write-Host "[Status] PID 파일:" -ForegroundColor Cyan
        Get-Content $PidFile -Raw
    } else {
        Write-Host "[Status] PID 파일 없음 (서비스가 기동되지 않은 상태)" -ForegroundColor Yellow
    }
    foreach ($p in @(@{n="backend"; port=$BackendPort}, @{n="frontend"; port=$FrontendPort})) {
        $procId = Get-PortPid -Port $p.port
        if ($procId) {
            Write-Host "[Status] $($p.n) 포트 $($p.port) LISTEN -> PID $procId" -ForegroundColor Green
        } else {
            Write-Host "[Status] $($p.n) 포트 $($p.port) 미사용" -ForegroundColor DarkGray
        }
    }
    Test-Health
}

function Show-Logs {
    foreach ($f in @(@{n="backend"; path=$BackendLog}, @{n="frontend"; path=$FrontendLog})) {
        Write-Host "===== $($f.n) ($($f.path)) =====" -ForegroundColor Cyan
        if (Test-Path $f.path) {
            Get-Content $f.path -Tail 30
        } else {
            Write-Host "(로그 파일 없음)" -ForegroundColor DarkGray
        }
    }
}

switch ($Action) {
    "Start"  { Start-Services }
    "Stop"   { Stop-Services }
    "Status" { Show-Status }
    "Logs"   { Show-Logs }
}
