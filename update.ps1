# Workflow Loop update entry for Windows PowerShell 5.1 and PowerShell 7.
param(
    [string]$ProjectRoot = (Get-Location).Path,
    [string]$TargetVersion = "",
    [string]$ExpectedProjectVersion = "",
    [switch]$Confirmed,
    [int]$WaitForProcessId = 0,
    [string]$CleanupDirectory = ""
)

$ErrorActionPreference = "Stop"
$ProductName = "workflow-loop"
$ScriptVersion = "0.3.6"
$UvVersion = "0.11.33"
$UvBaseUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion"
$ShaWindowsX64 = "c253ce868ad48d29327b661452ce184c9e333e6d6f5bc8d6fcfbf4dd52b83442"
$ShaWindowsArm64 = "6eb261d3ad61b35e2a6cfd997b296b908ff74d6199717eca81c3c73e1df7fbc7"
$PypiJsonUrl = if ($env:WORKFLOW_LOOP_PYPI_JSON_URL) { $env:WORKFLOW_LOOP_PYPI_JSON_URL } else { "https://pypi.org/pypi/workflow-loop/json" }
$GithubApiUrl = if ($env:WORKFLOW_LOOP_GITHUB_API_URL) { $env:WORKFLOW_LOOP_GITHUB_API_URL.TrimEnd("/") } else { "https://api.github.com/repos/yuzyf/workflow_loop" }
$TmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("workflow_loop_update_" + [System.IO.Path]::GetRandomFileName())

function Quote-NativeArgument([string]$Value) {
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-NativeCaptured([string]$FilePath, [string[]]$Arguments) {
    $stdoutPath = Join-Path $script:TmpDir ("stdout_" + [System.IO.Path]::GetRandomFileName())
    $stderrPath = Join-Path $script:TmpDir ("stderr_" + [System.IO.Path]::GetRandomFileName())
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (($Arguments | ForEach-Object { Quote-NativeArgument $_ }) -join " ")
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw "无法启动 $FilePath" }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    [System.IO.File]::WriteAllText($stdoutPath, $stdout, (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText($stderrPath, $stderr, (New-Object System.Text.UTF8Encoding($false)))
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Stdout = $stdout; Stderr = $stderr; StdoutPath = $stdoutPath; StderrPath = $stderrPath }
}

function Write-CapturedResult($Result) {
    if ($Result.Stdout) { [Console]::Out.Write($Result.Stdout) }
    if ($Result.Stderr) { [Console]::Error.Write($Result.Stderr) }
}

function Stop-Update([string]$Message) {
    Write-Host "错误：$Message" -ForegroundColor Red
    exit 1
}

try {
    New-Item -ItemType Directory -Path $TmpDir | Out-Null
    $resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path
    if ((Get-Location).Path -ne $resolvedRoot) {
        Stop-Update "更新脚本必须从目标项目根目录执行，不会向父目录查找。"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedRoot ".workflow_loop") -PathType Container)) {
        Stop-Update "当前目录缺少 .workflow_loop，不是已安装项目根目录。"
    }

    $PythonBin = $null
    foreach ($candidate in @("python", "python3")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $versionCheck = Invoke-NativeCaptured $command.Source @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
        if ($versionCheck.ExitCode -eq 0) { $PythonBin = $command.Source; break }
    }
    if (-not $PythonBin) { Stop-Update "没有找到 Python 3.11 或更高版本；本次未修改任何内容。" }

    if (-not $env:UV_TOOL_BIN_DIR) { $env:UV_TOOL_BIN_DIR = Join-Path $env:USERPROFILE ".local\bin" }
    if (-not $env:UV_TOOL_DIR) { $env:UV_TOOL_DIR = Join-Path $env:USERPROFILE ".local\share\uv\tools" }
    $ToolBinDir = $env:UV_TOOL_BIN_DIR

    $UvBin = $null
    $existingUv = Get-Command uv -ErrorAction SilentlyContinue
    if ($existingUv) {
        $uvCheck = Invoke-NativeCaptured $existingUv.Source @("--version")
        if ($uvCheck.ExitCode -eq 0 -and (($uvCheck.Stdout.Trim() -split "\s+")[1] -eq $UvVersion)) {
            $UvBin = $existingUv.Source
        }
    }
    if (-not $UvBin) {
        $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        if ($architecture -eq "Arm64") {
            $UvAsset = "uv-aarch64-pc-windows-msvc.zip"; $UvSha = $ShaWindowsArm64
        }
        elseif ($architecture -eq "X64") {
            $UvAsset = "uv-x86_64-pc-windows-msvc.zip"; $UvSha = $ShaWindowsX64
        }
        else { Stop-Update "暂不支持的 Windows 架构：$architecture。" }
        $assetPath = Join-Path $TmpDir $UvAsset
        Invoke-WebRequest -Uri "$UvBaseUrl/$UvAsset" -OutFile $assetPath -UseBasicParsing
        $actualSha = (Get-FileHash -Algorithm SHA256 -Path $assetPath).Hash.ToLowerInvariant()
        if ($actualSha -ne $UvSha) { Stop-Update "uv 下载文件的 SHA-256 与脚本内置摘要不符。" }
        $extractDir = Join-Path $TmpDir "uv"
        Expand-Archive -Path $assetPath -DestinationPath $extractDir -Force
        $uvExe = Get-ChildItem -Path $extractDir -Recurse -Filter "uv.exe" | Select-Object -First 1
        if (-not $uvExe) { Stop-Update "解压后找不到 uv.exe。" }
        $UvBin = $uvExe.FullName
    }

    $resolverPath = Join-Path $TmpDir "resolve_version.py"
    $resolver = @'
import json
import os
import urllib.request
from packaging.version import Version, InvalidVersion

def load(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "workflow-loop-maintenance"})
    with urllib.request.urlopen(req, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"元数据顶层不是对象: {url}")
    return value

requested = os.environ.get("WORKFLOW_LOOP_REQUESTED_VERSION", "").strip()
pypi = load(os.environ["WORKFLOW_LOOP_PYPI_JSON_URL"])
raw = requested or pypi.get("info", {}).get("version", "")
try:
    target = Version(raw)
except InvalidVersion:
    raise SystemExit(f"目标版本无效: {raw!r}")
if target.is_prerelease or target.is_devrelease or target.local is not None:
    raise SystemExit(f"目标版本不是正式版本: {target}")
files = pypi.get("releases", {}).get(str(target), [])
if not files or not any(not item.get("yanked", False) for item in files if isinstance(item, dict)):
    raise SystemExit(f"PyPI 没有可用的正式版本 {target}")
suffix = f"releases/tags/v{target}" if requested else "releases/latest"
github = load(os.environ["WORKFLOW_LOOP_GITHUB_API_URL"].rstrip("/") + "/" + suffix)
if github.get("draft") or github.get("prerelease") or github.get("tag_name") != f"v{target}":
    raise SystemExit(f"PyPI {target} 与 GitHub Release {github.get('tag_name')!r} 不一致")
print(target)
'@
    [System.IO.File]::WriteAllText($resolverPath, $resolver, (New-Object System.Text.UTF8Encoding($false)))
    $env:WORKFLOW_LOOP_REQUESTED_VERSION = $TargetVersion
    $env:WORKFLOW_LOOP_PYPI_JSON_URL = $PypiJsonUrl
    $env:WORKFLOW_LOOP_GITHUB_API_URL = $GithubApiUrl
    $resolveResult = Invoke-NativeCaptured $UvBin @("run", "--no-project", "--with", "packaging>=24.0", "--python", $PythonBin, "--no-managed-python", "--no-python-downloads", "python", $resolverPath)
    if ($resolveResult.ExitCode -ne 0) { Write-CapturedResult $resolveResult; Stop-Update "无法确认目标正式版本；本次未修改任何内容。" }
    $TargetVersion = $resolveResult.Stdout.Trim()

    $projectData = Get-Content -Raw -LiteralPath (Join-Path $resolvedRoot ".workflow_loop\project.json") | ConvertFrom-Json
    $currentProjectVersion = [string]$projectData.installer_version
    if ($ExpectedProjectVersion -and $currentProjectVersion -ne $ExpectedProjectVersion) {
        Stop-Update "项目版本在确认后发生变化：确认时是 $ExpectedProjectVersion，现在是 $currentProjectVersion。"
    }

    Write-Host "─── 项目更新预检 ───"
    $preflight = Invoke-NativeCaptured $UvBin @("tool", "run", "--isolated", "--from", "$ProductName==$TargetVersion", "--python", $PythonBin, "--no-managed-python", "--no-python-downloads", "workflow", "_update-project", "--check-only")
    Write-CapturedResult $preflight
    if ($preflight.ExitCode -ne 0) { Stop-Update "目标版本拒绝更新当前项目；项目和全局命令均未修改。" }

    $workflowBin = Join-Path $ToolBinDir "workflow.exe"
    $existingGlobalVersion = "未安装"
    if (Test-Path -LiteralPath $workflowBin -PathType Leaf) {
        $identityResult = Invoke-NativeCaptured $workflowBin @("--version")
        if ($identityResult.ExitCode -ne 0 -or $identityResult.Stdout.Trim() -notmatch '^workflow-loop (.+)$') {
            Stop-Update "$workflowBin 不是可确认的 Workflow Loop 命令。"
        }
        $existingGlobalVersion = $Matches[1]
    }
    if ($existingGlobalVersion -ne "未安装") {
        $versionCheckPath = Join-Path $TmpDir "check_direction.py"
        $versionCheckCode = "from packaging.version import Version; import sys; raise SystemExit(0 if Version(sys.argv[2]) >= Version(sys.argv[1]) else 1)"
        [System.IO.File]::WriteAllText($versionCheckPath, $versionCheckCode, (New-Object System.Text.UTF8Encoding($false)))
        $direction = Invoke-NativeCaptured $UvBin @("run", "--no-project", "--with", "packaging>=24.0", "--python", $PythonBin, "--no-managed-python", "--no-python-downloads", "python", $versionCheckPath, $existingGlobalVersion, $TargetVersion)
        if ($direction.ExitCode -ne 0) { Stop-Update "目标版本 $TargetVersion 低于电脑全局命令版本 $existingGlobalVersion，不允许降级。" }
    }

    if (-not $Confirmed) {
        Write-Host ""
        Write-Host "═══ Workflow Loop 更新确认 ═══"
        Write-Host "项目根目录: $resolvedRoot"
        Write-Host "电脑全局命令版本: $existingGlobalVersion"
        Write-Host "当前项目版本: $currentProjectVersion"
        Write-Host "目标正式版本: $TargetVersion"
        Write-Host "直接覆盖 AGENTS.md、两套静态仓库和 project.json 的安装版本字段；不备份。"
        Write-Host "保留当前轮次、历史、回退资料、业务代码和正式产物。"
        $answer = Read-Host "确认以上范围并开始更新？[y/N]"
        if ($answer -notmatch '^(y|yes)$') { Write-Host "已取消。项目和电脑全局命令均未修改。"; exit 0 }
    }

    if ($WaitForProcessId -gt 0) {
        while (Get-Process -Id $WaitForProcessId -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 200 }
    }

    if ($existingGlobalVersion -ne $TargetVersion) {
        Write-Host "更新电脑全局命令到 $TargetVersion..."
        $install = Invoke-NativeCaptured $UvBin @("tool", "install", "--force", "$ProductName==$TargetVersion", "--python", $PythonBin, "--no-managed-python", "--no-python-downloads")
        Write-CapturedResult $install
        if ($install.ExitCode -ne 0) { Stop-Update "全局命令更新失败；项目尚未更新，可以重新执行同一命令。" }
    }

    if (-not (Test-Path -LiteralPath $workflowBin -PathType Leaf)) { Stop-Update "更新后找不到 $workflowBin；项目尚未更新。" }
    $identity = Invoke-NativeCaptured $workflowBin @("--version")
    if ($identity.ExitCode -ne 0 -or $identity.Stdout.Trim() -ne "workflow-loop $TargetVersion") {
        Stop-Update "全局命令复核失败：得到 $($identity.Stdout.Trim())。"
    }

    Write-Host "更新当前项目到 $TargetVersion..."
    $projectUpdate = Invoke-NativeCaptured $workflowBin @("_update-project", "--confirmed", "--expected-project-version", $currentProjectVersion)
    Write-CapturedResult $projectUpdate
    if ($projectUpdate.ExitCode -ne 0) { Stop-Update "项目更新未完成；全局命令保留实际结果，可以重新执行同一命令。" }
    $finalProject = Get-Content -Raw -LiteralPath (Join-Path $resolvedRoot ".workflow_loop\project.json") | ConvertFrom-Json
    Write-Host "═══ 更新完成 ═══"
    Write-Host "电脑全局命令版本: $TargetVersion"
    Write-Host "当前项目版本: $($finalProject.installer_version)"
}
finally {
    if (Test-Path -LiteralPath $TmpDir) { Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue }
    if ($CleanupDirectory -and (Test-Path -LiteralPath $CleanupDirectory)) {
        Remove-Item -Recurse -Force $CleanupDirectory -ErrorAction SilentlyContinue
    }
}
