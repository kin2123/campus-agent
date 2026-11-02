# ============================================================================
#  校园课程智能助手 · 一键启停
#
#  用法：双击 run.bat（不要直接双击本文件 —— 默认执行策略下会被当记事本打开）
#
#  三个服务：
#    前端      Vue3 + Vite              :5173   窗口标题 CampusAssistant-Frontend
#    业务后端  FastAPI                  :18000  窗口标题 CampusAssistant-Backend
#    MCP工具   FastMCP streamable-http  :18001  窗口标题 CampusAssistant-MCP
#
#  ⚠ 本文件必须保存为 UTF-8 with BOM。
#    PowerShell 5.1 对无 BOM 的文件按系统 ANSI(GBK) 解析，中文菜单会全变乱码。
#    改完记得确认编码，run.bat 里也校验了这一点。
# ============================================================================

$ErrorActionPreference = 'Continue'

$Root      = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root 'backend'
$FrontendDir = Join-Path $Root 'frontend'
$LogDir    = Join-Path $Root 'logs'
$PidFile   = Join-Path $LogDir '.win_pids'

# 窗口标题前缀。刻意用 ASCII：
# ① `title` 命令在非 UTF-8 代码页下中文会乱码
# ② ASCII 前缀正好能当「这个窗口是不是本脚本开的」的判据，
#    这样停止时只关自己开的窗口，不会误杀用户手工开的终端
$TitlePrefix = 'CampusAssistant'

$Services = @(
    @{ Name='Backend';  Port=18000; Title="$TitlePrefix-Backend :18000";
       Desc='业务后端 FastAPI' }
    @{ Name='MCP';      Port=18001; Title="$TitlePrefix-MCP :18001";
       Desc='MCP 工具服务' }
    @{ Name='Frontend'; Port=5173;  Title="$TitlePrefix-Frontend :5173";
       Desc='前端 Vite' }
)

# --------------------------------------------------------------------------- 环境探测

function Resolve-Python {
    $candidates = @()
    if ($env:CAMPUS_PYTHON) { $candidates += $env:CAMPUS_PYTHON }
    $candidates += (Join-Path $Root '.venv\Scripts\python.exe')
    $candidates += 'C:\Users\10115\.workbuddy\binaries\python\envs\campus-agent\Scripts\python.exe'
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    # 退回 PATH 上的 python
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Resolve-Npm {
    $candidates = @()
    if ($env:CAMPUS_NPM) { $candidates += $env:CAMPUS_NPM }
    $candidates += 'C:\Users\10115\.workbuddy\binaries\node\versions\22.22.2-3\npm.cmd'
    $candidates += 'C:\nvm4w\nodejs\npm.cmd'
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    $cmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Resolve-Node {
    $candidates = @(
        'C:\Users\10115\.workbuddy\binaries\node\versions\22.22.2-3\node.exe',
        'C:\nvm4w\nodejs\node.exe'
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# --------------------------------------------------------------------------- 端口工具

function Get-PortPids([int]$Port) {
    try {
        return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                 Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        return @()
    }
}

function Test-PortOpen([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Stop-ByPort([int]$Port) {
    # 按端口找进程，而不是记录启动时的 PID。原因：
    #  · uvicorn --reload 会同时有 reloader + worker 两个进程
    #  · npm run dev 会派生 node 子进程
    # 只杀父进程会留下占着端口的残留，下次启动就报「端口被占用」。
    # /T 连带子进程一起结束。
    $pids = Get-PortPids $Port
    if (-not $pids -or $pids.Count -eq 0) { return $false }
    foreach ($procId in $pids) {
        & taskkill /PID $procId /T /F 2>&1 | Out-Null
    }
    return $true
}

function Save-WindowPid([int]$ProcId) {
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    # 用 ASCII 编码：PS 5.1 的 -Encoding UTF8 会写 BOM，
    # 追加多行时每行都带 BOM，读回来解析 PID 会失败。
    Add-Content -Path $PidFile -Value $ProcId -Encoding ASCII
}

function Close-ServiceWindows {
    # taskkill /T 结束的是窗口「里面」的进程，cmd /k 的窗口壳会留下来，
    # 结果是每次停止都留一排空窗口要手动叉。
    # 这里做两件事：① 按记录过的 cmd PID 关；② 按窗口标题前缀兜底
    # （脚本重启后 PID 记录会丢，标题兜底能覆盖这种情况）。
    $closed = 0

    if (Test-Path $PidFile) {
        foreach ($line in (Get-Content $PidFile -ErrorAction SilentlyContinue)) {
            $procId = 0
            if ([int]::TryParse($line.Trim(), [ref]$procId)) {
                & taskkill /PID $procId /T /F 2>&1 | Out-Null
                $closed++
            }
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    # 标题兜底：只匹配本脚本设的前缀，不会误杀手工开的窗口
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -like "$TitlePrefix*" } |
        ForEach-Object {
            & taskkill /PID $_.Id /T /F 2>&1 | Out-Null
            $closed++
        }
    return $closed
}

# --------------------------------------------------------------------------- 启动

function Start-Service($Svc) {
    $port = $Svc.Port
    if (Test-PortOpen $port) {
        Write-Host ("  [跳过] {0} 端口 {1} 已被占用，先执行停止" -f $Svc.Desc, $port) -ForegroundColor Yellow
        return
    }

    $python = Resolve-Python
    $npm    = Resolve-Npm
    $node   = Resolve-Node

    switch ($Svc.Name) {
        'Backend' {
            if (-not $python) { Write-Host '  [错误] 找不到 python，请先按 README 安装依赖' -ForegroundColor Red; return }
            # cmd /k 让窗口执行完不关闭，日志留在窗口里便于排查
            $inner = "cd /d `"$BackendDir`" && set PYTHONIOENCODING=utf-8 && `"$python`" -m app.main"
        }
        'MCP' {
            if (-not $python) { Write-Host '  [错误] 找不到 python' -ForegroundColor Red; return }
            $inner = "cd /d `"$Root`" && set PYTHONIOENCODING=utf-8 && `"$python`" -m mcp_server.server"
        }
        'Frontend' {
            if (-not $npm) { Write-Host '  [错误] 找不到 npm' -ForegroundColor Red; return }
            if ($node) { $env:Path = (Split-Path $node) + ';' + $env:Path }
            # 首次运行自动装依赖，省掉一次手工操作
            if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
                $inner = "cd /d `"$FrontendDir`" && `"$npm`" install && `"$npm`" run dev"
            } else {
                $inner = "cd /d `"$FrontendDir`" && `"$npm`" run dev"
            }
        }
    }

    # 每个服务独立窗口，日志分开互不干扰，出问题一眼看出是哪个报错，
    # 也能单独关掉一个而不影响其他两个。
    $proc = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/k', "title $($Svc.Title) && $inner" `
        -PassThru
    Save-WindowPid $proc.Id

    Write-Host ("  [启动] {0} -> :{1}" -f $Svc.Desc, $port) -ForegroundColor Green
}

function Wait-Ready($Svc, [int]$TimeoutSec = 45) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        if (Test-PortOpen $Svc.Port) {
            return $true
        }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Start-All {
    Write-Host ''
    Write-Host '正在启动三个服务…' -ForegroundColor Cyan
    Write-Host ''

    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

    foreach ($svc in $Services) { Start-Service $svc }

    Write-Host ''
    Write-Host '等待端口就绪…' -ForegroundColor Cyan
    $allOk = $true
    foreach ($svc in $Services) {
        if (Wait-Ready $svc) {
            Write-Host ("  [就绪] {0,-16} http://127.0.0.1:{1}" -f $svc.Desc, $svc.Port) -ForegroundColor Green
        } else {
            Write-Host ("  [超时] {0,-16} :{1} 未监听，请查看该窗口的报错" -f $svc.Desc, $svc.Port) -ForegroundColor Red
            $allOk = $false
        }
    }

    Write-Host ''
    if ($allOk) {
        Write-Host '启动完成。' -ForegroundColor Green
        Write-Host '  前端界面  http://127.0.0.1:5173' -ForegroundColor White
        Write-Host '  接口文档  http://127.0.0.1:18000/docs' -ForegroundColor White
        Write-Host '  演示账号  20230101 / 123456' -ForegroundColor White
        Start-Process 'http://127.0.0.1:5173'
    } else {
        Write-Host '有服务启动失败，请查看对应窗口的日志。' -ForegroundColor Yellow
    }
}

function Stop-All {
    Write-Host ''
    Write-Host '正在停止服务…' -ForegroundColor Cyan
    foreach ($svc in $Services) {
        if (Stop-ByPort $svc.Port) {
            Write-Host ("  [已停] {0,-16} :{1}" -f $svc.Desc, $svc.Port) -ForegroundColor Green
        } else {
            Write-Host ("  [未运行] {0,-16} :{1}" -f $svc.Desc, $svc.Port) -ForegroundColor DarkGray
        }
    }
    $closed = Close-ServiceWindows
    if ($closed -gt 0) {
        Write-Host ("  已关闭 {0} 个由本脚本打开的窗口" -f $closed) -ForegroundColor DarkGray
    }
    Write-Host '停止完成。' -ForegroundColor Green
}

function Show-Status {
    Write-Host ''
    Write-Host '服务状态' -ForegroundColor Cyan
    Write-Host ('  {0,-18} {1,-8} {2}' -f '服务', '端口', '状态')
    Write-Host ('  ' + ('-' * 46))
    foreach ($svc in $Services) {
        $running = Test-PortOpen $svc.Port
        $pids = Get-PortPids $svc.Port
        if ($running) {
            $status = "运行中 (PID $($pids -join ','))"
            $color = 'Green'
        } else {
            $status = '未运行'
            $color = 'DarkGray'
        }
        Write-Host ('  {0,-18} {1,-8} {2}' -f $svc.Desc, $svc.Port, $status) -ForegroundColor $color
    }

    Write-Host ''
    Write-Host '运行环境' -ForegroundColor Cyan
    $python = Resolve-Python
    $node   = Resolve-Node
    if ($python) {
        Write-Host ('  python  {0}' -f $python) -ForegroundColor DarkGray
    } else {
        Write-Host '  python  ✗ 未找到' -ForegroundColor Yellow
    }
    if ($node) {
        Write-Host ('  node    {0}' -f $node) -ForegroundColor DarkGray
    } else {
        Write-Host '  node    ✗ 未找到' -ForegroundColor Yellow
    }

    $venv = Join-Path $FrontendDir 'node_modules'
    if (Test-Path $venv) {
        Write-Host '  前端依赖 已安装' -ForegroundColor DarkGray
    } else {
        Write-Host '  前端依赖 未安装（首次启动时会自动 npm install）' -ForegroundColor Yellow
    }

    # Agent 与 MCP 的实际连通性只能问后端
    if (Test-PortOpen 18000) {
        Write-Host ''
        Write-Host 'Agent 链路' -ForegroundColor Cyan
        try {
            $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:18000/health' -TimeoutSec 5
            Write-Host ('  向量库   {0}（{1} 个分块）' -f $resp.rag_backend, $resp.knowledge_chunks) -ForegroundColor DarkGray
            Write-Host ('  模型     {0}' -f $resp.llm_provider) -ForegroundColor DarkGray
            if (Test-PortOpen 18001) {
                Write-Host '  MCP      已监听 :18001' -ForegroundColor DarkGray
            } else {
                Write-Host '  MCP      ✗ 未监听，Agent 无法调用工具' -ForegroundColor Yellow
            }
        } catch {
            Write-Host ('  读取 /health 失败：{0}' -f $_.Exception.Message) -ForegroundColor Yellow
        }
    }
}

# --------------------------------------------------------------------------- 菜单

function Show-Menu {
    Clear-Host
    Write-Host ''
    Write-Host '  ╔══════════════════════════════════════════════════════════╗' -ForegroundColor Cyan
    Write-Host '  ║        校园课程智能助手 · AI Agent + RAG + MCP            ║' -ForegroundColor Cyan
    Write-Host '  ║        FastAPI :18000  |  FastMCP :18001  |  Vue3 :5173  ║' -ForegroundColor Cyan
    Write-Host '  ╚══════════════════════════════════════════════════════════╝' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '   1  启动全部服务'   -ForegroundColor White
    Write-Host '   2  停止全部服务'   -ForegroundColor White
    Write-Host '   3  查看状态'       -ForegroundColor White
    Write-Host '   4  重新构建知识库索引' -ForegroundColor White
    Write-Host '   5  运行链路自检（无需 API Key）' -ForegroundColor White
    Write-Host '   6  打开前端页面'   -ForegroundColor White
    Write-Host '   0  退出'           -ForegroundColor White
    Write-Host ''
}

function Invoke-IndexRebuild {
    $python = Resolve-Python
    if (-not $python) { Write-Host '  找不到 python' -ForegroundColor Red; return }
    Write-Host ''
    Write-Host '重建知识库索引…' -ForegroundColor Cyan
    Push-Location $Root
    try {
        $env:PYTHONIOENCODING = 'utf-8'
        & $python 'scripts/build_index.py' '--rebuild'
    } finally {
        Pop-Location
    }
    Write-Host ''
    Read-Host '按回车返回菜单'
}

function Invoke-ChainCheck {
    $python = Resolve-Python
    if (-not $python) { Write-Host '  找不到 python' -ForegroundColor Red; return }
    if (-not (Test-PortOpen 18000) -or -not (Test-PortOpen 18001)) {
        Write-Host ''
        Write-Host '  链路自检需要后端(18000)与 MCP(18001) 都在运行。' -ForegroundColor Yellow
        Write-Host '  请先执行「1 启动全部服务」。' -ForegroundColor Yellow
        Write-Host ''
        Read-Host '按回车返回菜单'
        return
    }
    Write-Host ''
    Write-Host '运行端到端链路自检…' -ForegroundColor Cyan
    Push-Location $Root
    try {
        $env:PYTHONIOENCODING = 'utf-8'
        & $python 'scripts/check_chain.py'
    } finally {
        Pop-Location
    }
    Write-Host ''
    Read-Host '按回车返回菜单'
}

while ($true) {
    Show-Menu
    $choice = Read-Host '  请选择'
    switch ($choice) {
        '1' { Start-All;                Write-Host ''; Read-Host '按回车返回菜单' }
        '2' { Stop-All;                 Write-Host ''; Read-Host '按回车返回菜单' }
        '3' { Show-Status;              Write-Host ''; Read-Host '按回车返回菜单' }
        '4' { Invoke-IndexRebuild }
        '5' { Invoke-ChainCheck }
        '6' { Start-Process 'http://127.0.0.1:5173' }
        '0' { Write-Host ''; Write-Host '  已退出。' -ForegroundColor Cyan; Write-Host ''; exit 0 }
        default { Write-Host '  无效选项，请输入 0-6。' -ForegroundColor Yellow; Start-Sleep -Milliseconds 900 }
    }
}
