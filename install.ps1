# workflow_loop 官方安装脚本（Windows PowerShell 5.1 / PowerShell 7）
# 职责：终端确认、无写入预检、固定版本 uv 下载校验、全局命令安装、用户 PATH 处理，
# 以及通过一次性事务调用包内项目安装入口。项目文件写入全部由 Python 内部入口完成。
# 本脚本不调用 Bash；ExecutionPolicy Bypass 只作用于本次进程，不修改用户或机器策略。

$ErrorActionPreference = "Stop"

# ─── 固定版本与固定资产（不可变发布，不使用 latest） ───
$ProductName = "workflow-loop"
$ProductVersion = "0.2.0"
$ProductIdentity = "$ProductName $ProductVersion"
$UvVersion = "0.11.33"
$UvBaseUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion"
# 各平台资产的固定摘要（来自官方不可变发布）
$ShaWindowsX64 = "c253ce868ad48d29327b661452ce184c9e333e6d6f5bc8d6fcfbf4dd52b83442"
$ShaWindowsArm64 = "6eb261d3ad61b35e2a6cfd997b296b908ff74d6199717eca81c3c73e1df7fbc7"

# ─── 基本路径 ───
$ProjectRoot = (Get-Location).Path
$WfDir = Join-Path $ProjectRoot ".workflow_loop"
$AgentsMd = Join-Path $ProjectRoot "AGENTS.md"

# 工具环境与命令目录：显式固定并导出，保证确认时披露的位置就是实际写入位置
if (-not $env:UV_TOOL_BIN_DIR) { $env:UV_TOOL_BIN_DIR = Join-Path $env:USERPROFILE ".local\bin" }
if (-not $env:UV_TOOL_DIR) { $env:UV_TOOL_DIR = Join-Path $env:USERPROFILE ".local\share\uv\tools" }
$ToolBinDir = $env:UV_TOOL_BIN_DIR
$ToolDir = $env:UV_TOOL_DIR
$recordBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE ".local\share" }
$InstallRecord = if ($env:WORKFLOW_LOOP_INSTALL_RECORD) { $env:WORKFLOW_LOOP_INSTALL_RECORD } else { Join-Path $recordBase "workflow-loop\install.json" }

# 临时目录（确认后才创建和使用；结束时删除）
$TmpDir = $null
# 本次回滚范围记录
$InstalledGlobal = $false
$UserPathBackup = $null
$UserPathChanged = $false
$InstallRecordBackup = $null
$InstallRecordExisted = $false

function Remove-TempDir {
    if ($script:TmpDir -and (Test-Path $script:TmpDir)) {
        Remove-Item -Recurse -Force $script:TmpDir -ErrorAction SilentlyContinue
    }
}

function Undo-GlobalInstall {
    if ($script:InstalledGlobal) {
        Write-Host "回滚本次新装的全局命令..."
        Remove-Item -Recurse -Force (Join-Path $script:ToolDir $script:ProductName) -ErrorAction SilentlyContinue
        Remove-Item -Force (Join-Path $script:ToolBinDir "workflow.exe") -ErrorAction SilentlyContinue
        Remove-Item -Force (Join-Path $script:ToolBinDir "workflow") -ErrorAction SilentlyContinue
    }
    if ($script:UserPathChanged) {
        Write-Host "恢复本次修改的用户 PATH..."
        [Environment]::SetEnvironmentVariable("Path", $script:UserPathBackup, "User")
    }
    if ($script:InstallRecordExisted -and $script:InstallRecordBackup -and (Test-Path $script:InstallRecordBackup)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:InstallRecord) | Out-Null
        Copy-Item -Force $script:InstallRecordBackup $script:InstallRecord
    }
    elseif (-not $script:InstallRecordExisted) {
        Remove-Item -Force $script:InstallRecord -ErrorAction SilentlyContinue
    }
}

function Stop-Install([string]$Message) {
    Write-Host "错误：$Message" -ForegroundColor Red
    Remove-TempDir
    exit 1
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    # Windows PowerShell 5.1 的 Set-Content -Encoding UTF8 会写 BOM，
    # Python 的严格 UTF-8 JSON 读取会把 BOM 当成非法字符。
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

Write-Host "═══ $ProductName $ProductVersion 安装脚本 ═══"
Write-Host ""

# ─────────────────────────────────────────────
# 无写入预检：以下检查不修改任何文件
# ─────────────────────────────────────────────

# 1. 兼容 Python：安装动作和项目写入前必须确认 Python 3.11+；没有时只说明，不代装
$PythonBin = $null
$PythonVersion = $null
$candidates = @(
    @{ Cmd = "python"; Args = @() },
    @{ Cmd = "py"; Args = @("-3") }
)
foreach ($candidate in $candidates) {
    $cmdInfo = Get-Command $candidate.Cmd -ErrorAction SilentlyContinue
    if (-not $cmdInfo) { continue }
    $checkArgs = $candidate.Args + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
    & $candidate.Cmd @checkArgs 2>$null
    if ($LASTEXITCODE -eq 0) {
        $verArgs = $candidate.Args + @("-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])")
        $PythonVersion = (& $candidate.Cmd @verArgs).Trim()
        $exeArgs = $candidate.Args + @("-c", "import sys; print(sys.executable)")
        $PythonBin = (& $candidate.Cmd @exeArgs).Trim()
        break
    }
}
if (-not $PythonBin) {
    Write-Host "错误：没有找到 Python 3.11 或更高版本。" -ForegroundColor Red
    Write-Host "workflow 命令需要兼容的 Python 运行。请先自行安装，例如：" -ForegroundColor Red
    Write-Host "  winget install Python.Python.3.12" -ForegroundColor Red
    Write-Host "安装脚本不会自动替你安装 Python。本次未修改任何文件。" -ForegroundColor Red
    exit 1
}

# 2. 已有同名命令身份核对：只有兼容的 Workflow Loop 才能复用
$ExistingWorkflow = $null
$GlobalNeeded = $true
$existingCmd = Get-Command workflow -ErrorAction SilentlyContinue
if ($existingCmd) {
    $ExistingWorkflow = $existingCmd.Source
    $existingIdentity = ""
    try { $existingIdentity = (& $ExistingWorkflow --version 2>$null | Out-String).Trim() } catch { $existingIdentity = "" }
    if ($existingIdentity -eq $ProductIdentity) {
        $GlobalNeeded = $false
    }
    else {
        Write-Host "错误：PATH 中已有名为 workflow 的其它命令，安装已停止。" -ForegroundColor Red
        Write-Host "  命令位置：$ExistingWorkflow" -ForegroundColor Red
        if ($existingIdentity) {
            Write-Host "  检测到的身份：$existingIdentity" -ForegroundColor Red
        }
        else {
            Write-Host "  检测到的身份：（无法取得版本输出）" -ForegroundColor Red
        }
        Write-Host "  本安装器只接受身份严格为 `"$ProductIdentity`" 的命令。" -ForegroundColor Red
        Write-Host "处理方法：改名或移除该命令，或调整 PATH 后重新运行安装脚本。" -ForegroundColor Red
        Write-Host "本次未修改任何文件。" -ForegroundColor Red
        exit 1
    }
}

# 3. 平台资产选择（全局命令需要安装时才用到）
$UvAsset = $null
$UvSha = $null
switch ($env:PROCESSOR_ARCHITECTURE) {
    "AMD64" { $UvAsset = "uv-x86_64-pc-windows-msvc.zip"; $UvSha = $ShaWindowsX64 }
    "ARM64" { $UvAsset = "uv-aarch64-pc-windows-msvc.zip"; $UvSha = $ShaWindowsArm64 }
    default {
        if ($GlobalNeeded) {
            Stop-Install "暂不支持的 Windows 处理器架构：$env:PROCESSOR_ARCHITECTURE。本次未修改任何文件。"
        }
    }
}

# 4. 已有兼容 uv 检测（版本完全相同才复用；不覆盖用户已有的其它 uv）
$ReuseUv = $null
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) {
    $uvVer = ""
    try { $uvVer = ((& $uvCmd.Source --version) -split "\s+")[1] } catch { $uvVer = "" }
    if ($uvVer -eq $UvVersion) { $ReuseUv = $uvCmd.Source }
}

# 5. 用户 PATH：确定写入前的实际持久修改位置（HKCU 用户环境变量）
$PathChangeNeeded = $false
if ($GlobalNeeded) {
    $currentUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $currentUserPath) { $currentUserPath = "" }
    $pathEntries = $currentUserPath -split ";" | Where-Object { $_ }
    $processEntries = $env:Path -split ";" | Where-Object { $_ }
    if (($pathEntries -notcontains $ToolBinDir) -and ($processEntries -notcontains $ToolBinDir)) {
        $PathChangeNeeded = $true
    }
}

# ─────────────────────────────────────────────
# 完整写入范围披露 + 一次确认
# ─────────────────────────────────────────────
Write-Host "当前项目根目录（安装器严格使用当前目录，不向上猜测）："
Write-Host "  $ProjectRoot"
Write-Host ""
Write-Host "本机 Python：$PythonBin（$PythonVersion）"
Write-Host ""
Write-Host "本次安装的检查与可能写入范围："
Write-Host "  项目侧由安装包内的 Python 入口统一检查，不由 PowerShell 根据目录或文字猜测："
Write-Host "    已完整安装 $ProductVersion：项目文件零修改"
Write-Host "    干净未安装：写入以下固定范围"
Write-Host "      $AgentsMd（存在则整份覆盖，不合并；失败时由安装事务恢复）"
Write-Host "      $WfDir\（写入模板仓库、规范仓库和安装版本标记）"
Write-Host "      $ProjectRoot\.workflow_loop_install_tx\（一次性安装事务目录，成功后删除）"
Write-Host "    骨架残缺或版本异常：在写入项目文件前停止"
if ($GlobalNeeded) {
    Write-Host "  电脑侧："
    Write-Host "    全局工具环境：$ToolDir\$ProductName\"
    Write-Host "    workflow 可执行文件：$ToolBinDir\workflow.exe"
    if ($ReuseUv) {
        Write-Host "    安装工具：复用本机已有的 uv $UvVersion（$ReuseUv）"
    }
    else {
        Write-Host "    安装工具：下载固定版本 uv $UvVersion（$UvAsset）到本次临时目录，校验后使用，结束时删除"
    }
    if ($PathChangeNeeded) {
        Write-Host "    PATH 修改：把 $ToolBinDir 加入用户 PATH（注册表用户环境变量）"
    }
    else {
        Write-Host "    PATH 修改：无需修改（命令目录已在 PATH 中）"
    }
}
else {
    Write-Host "  电脑侧：全局命令无修改（已存在兼容的 $ProductIdentity）"
}
Write-Host ""
Write-Host "临时下载目录只在确认后创建，安装结束时删除。"
Write-Host ""

$response = Read-Host "确认以上完整写入范围并开始安装？[y/N]"
if ($response -notmatch "^(y|Y|yes|YES|Yes)$") {
    Write-Host "已取消。未下载任何内容，未修改任何文件。"
    exit 0
}
Write-Host "确认通过，开始安装..."
Write-Host ""

# ─────────────────────────────────────────────
# 确认后：准备临时目录与安装工具
# ─────────────────────────────────────────────
$TmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("workflow_loop_install_" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $TmpDir | Out-Null

$UvBin = $null
$WorkflowBin = $null
if ($GlobalNeeded) {
    Write-Host "─── 安装全局 workflow 命令 ───"
    if ($ReuseUv) {
        $UvBin = $ReuseUv
        Write-Host "复用本机已有的 uv $UvVersion。"
    }
    else {
        Write-Host "下载 uv $UvVersion（$UvAsset）..."
        $assetPath = Join-Path $TmpDir $UvAsset
        try {
            Invoke-WebRequest -Uri "$UvBaseUrl/$UvAsset" -OutFile $assetPath -UseBasicParsing
        }
        catch {
            Stop-Install "uv 下载失败：$($_.Exception.Message)。已删除临时内容，本次未修改任何文件。"
        }
        $actualSha = (Get-FileHash -Algorithm SHA256 -Path $assetPath).Hash.ToLowerInvariant()
        if ($actualSha -ne $UvSha) {
            Stop-Install "uv 下载文件的 SHA-256（$actualSha）与脚本内置摘要不符。已删除临时内容，本次未修改任何文件。"
        }
        $extractDir = Join-Path $TmpDir "uv"
        Expand-Archive -Path $assetPath -DestinationPath $extractDir -Force
        $uvExe = Get-ChildItem -Path $extractDir -Recurse -Filter "uv.exe" | Select-Object -First 1
        if (-not $uvExe) {
            Stop-Install "解压后找不到 uv.exe。已删除临时内容，本次未修改任何文件。"
        }
        $UvBin = $uvExe.FullName
        $actualUvVersion = ((& $UvBin --version) -split "\s+")[1]
        if ($actualUvVersion -ne $UvVersion) {
            Stop-Install "下载的 uv 版本是 $actualUvVersion，期望 $UvVersion。已删除临时内容，本次未修改任何文件。"
        }
    }

    # 显式使用已检查的本机 Python；禁止 uv 托管或下载 Python
    Write-Host "安装 $ProductName==$ProductVersion..."
    & $UvBin tool install "$ProductName==$ProductVersion" --python $PythonBin --no-managed-python --no-python-downloads
    if ($LASTEXITCODE -ne 0) {
        Undo-GlobalInstall
        Stop-Install "全局命令安装失败。已删除临时内容，项目保持未修改。"
    }
    $InstalledGlobal = $true

    # 从实际命令目录复核身份；不要求用户重开终端
    $actualBinDir = (& $UvBin tool dir --bin | Out-String).Trim()
    if ($actualBinDir -ne $ToolBinDir) {
        Undo-GlobalInstall
        Stop-Install "实际命令目录 $actualBinDir 与确认时披露的 $ToolBinDir 不一致。已回滚，项目保持未修改。"
    }
    $WorkflowBin = Join-Path $ToolBinDir "workflow.exe"
    if (-not (Test-Path $WorkflowBin)) { $WorkflowBin = Join-Path $ToolBinDir "workflow" }
    $installedIdentity = ""
    try { $installedIdentity = (& $WorkflowBin --version 2>$null | Out-String).Trim() } catch { $installedIdentity = "" }
    if ($installedIdentity -ne $ProductIdentity) {
        Undo-GlobalInstall
        Stop-Install "安装后的身份复核失败：得到 `"$installedIdentity`"，期望 `"$ProductIdentity`"。已回滚，项目保持未修改。"
    }
    Write-Host "全局命令已安装：$WorkflowBin（$installedIdentity）"

    # PATH 处理：先备份用户 PATH 原值，失败可恢复
    if ($PathChangeNeeded) {
        $UserPathBackup = [Environment]::GetEnvironmentVariable("Path", "User")
        if (-not $UserPathBackup) { $UserPathBackup = "" }
        $newUserPath = if ($UserPathBackup) { "$UserPathBackup;$ToolBinDir" } else { $ToolBinDir }
        try {
            [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
            $UserPathChanged = $true
        }
        catch {
            Undo-GlobalInstall
            Stop-Install "用户 PATH 更新失败：$($_.Exception.Message)。已回滚本次全局安装，项目保持未修改。"
        }
        Write-Host "已把 $ToolBinDir 加入用户 PATH（对后续新终端生效）。"
    }

    # 记录用户 PATH 来源。只有 path_added=true 且当前值仍与记录完全相同时，全局卸载才恢复原值。
    if (Test-Path -LiteralPath $InstallRecord) {
        if (-not (Test-Path -LiteralPath $InstallRecord -PathType Leaf)) {
            $InstallRecordExisted = $true
            Undo-GlobalInstall
            Stop-Install "安装来源记录不是可安全覆盖的普通文件：$InstallRecord"
        }
        $InstallRecordBackup = Join-Path $TmpDir "install_record.bak"
        Copy-Item -Force $InstallRecord $InstallRecordBackup
        $InstallRecordExisted = $true
    }
    $recordDirectory = Split-Path -Parent $InstallRecord
    New-Item -ItemType Directory -Force -Path $recordDirectory | Out-Null
    $currentUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $currentUserPath) { $currentUserPath = "" }
    $pathBefore = if ($UserPathChanged) { $UserPathBackup } else { $currentUserPath }
    $record = [ordered]@{
        product          = $ProductName
        version          = $ProductVersion
        tool_dir         = $ToolDir
        tool_bin_dir     = $ToolBinDir
        path_added       = [bool]$UserPathChanged
        path_scope       = "user"
        user_path_before = $pathBefore
        user_path_after  = $currentUserPath
        recorded_at      = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
    }
    $recordTemp = Join-Path $recordDirectory (".workflow-install-" + [System.IO.Path]::GetRandomFileName())
    try {
        Write-Utf8NoBom -Path $recordTemp -Content ($record | ConvertTo-Json)
        Move-Item -Force $recordTemp $InstallRecord
    }
    catch {
        Remove-Item -Force $recordTemp -ErrorAction SilentlyContinue
        Undo-GlobalInstall
        Stop-Install "安装来源记录写入失败：$($_.Exception.Message)。已回滚本次全局安装，项目保持未修改。"
    }
}
else {
    $WorkflowBin = $ExistingWorkflow
    Write-Host "─── 全局命令无修改 ───"
    Write-Host "复用已有命令：$WorkflowBin"
}
Write-Host ""

# ─────────────────────────────────────────────
# 项目检查与安装：始终由一次性事务调用包内 Python 权威入口。
# 重复安装时，该入口确认骨架完整后直接返回，项目文件保持零修改。
# ─────────────────────────────────────────────
Write-Host "─── 检查并安装当前项目 ───"
$txFile = Join-Path $TmpDir "install_transaction.json"
$transaction = [ordered]@{
    product       = $ProductName
    version       = $ProductVersion
    project_root  = $ProjectRoot
    created_at    = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
    used          = $false
    allowed_paths = @("AGENTS.md", ".workflow_loop")
}
Write-Utf8NoBom -Path $txFile -Content ($transaction | ConvertTo-Json)

Push-Location $ProjectRoot
try {
    & $WorkflowBin _install-project --transaction $txFile
    $installExit = $LASTEXITCODE
}
finally {
    Pop-Location
}
if ($installExit -ne 0) {
    Undo-GlobalInstall
    Stop-Install "项目检查或安装失败。本次电脑侧修改已回滚；项目侧由安装事务负责恢复。"
}

Remove-TempDir
Write-Host ""
Write-Host "═══ 安装完成 ═══"
Write-Host "启动 Codex / OpenCode 并提出需求即可。"
Write-Host "智能体会读取 AGENTS.md 并自动调用 workflow start。"
