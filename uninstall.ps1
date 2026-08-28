# Workflow Loop project/global uninstall entry for Windows PowerShell 5.1 and PowerShell 7.
param(
    [switch]$Global,
    [string]$ProjectRoot = (Get-Location).Path,
    [switch]$Confirmed,
    [int]$WaitForProcessId = 0,
    [string]$CleanupDirectory = ""
)

$ErrorActionPreference = "Stop"
$ProductName = "workflow-loop"
$ProductVersion = "0.3.5"
$UvVersion = "0.11.33"
$UvBaseUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion"
$ShaWindowsX64 = "c253ce868ad48d29327b661452ce184c9e333e6d6f5bc8d6fcfbf4dd52b83442"
$ShaWindowsArm64 = "6eb261d3ad61b35e2a6cfd997b296b908ff74d6199717eca81c3c73e1df7fbc7"
$TmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("workflow_loop_uninstall_" + [System.IO.Path]::GetRandomFileName())

function Quote-NativeArgument([string]$Value) {
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-NativeCaptured([string]$FilePath, [string[]]$Arguments) {
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
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Stdout = $stdout; Stderr = $stderr }
}

function Write-CapturedResult($Result) {
    if ($Result.Stdout) { [Console]::Out.Write($Result.Stdout) }
    if ($Result.Stderr) { [Console]::Error.Write($Result.Stderr) }
}

function Stop-Uninstall([string]$Message) {
    Write-Host "错误：$Message" -ForegroundColor Red
    exit 1
}

try {
    New-Item -ItemType Directory -Path $TmpDir | Out-Null
    $PythonBin = $null
    foreach ($candidate in @("python", "python3")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $versionCheck = Invoke-NativeCaptured $command.Source @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
        if ($versionCheck.ExitCode -eq 0) { $PythonBin = $command.Source; break }
    }
    if (-not $PythonBin) { Stop-Uninstall "没有找到 Python 3.11 或更高版本；本次未修改任何内容。" }

    if (-not $env:UV_TOOL_BIN_DIR) { $env:UV_TOOL_BIN_DIR = Join-Path $env:USERPROFILE ".local\bin" }
    if (-not $env:UV_TOOL_DIR) { $env:UV_TOOL_DIR = Join-Path $env:USERPROFILE ".local\share\uv\tools" }
    $ToolBinDir = $env:UV_TOOL_BIN_DIR
    $ToolDir = $env:UV_TOOL_DIR
    $recordBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE ".local\share" }
    $InstallRecord = if ($env:WORKFLOW_LOOP_INSTALL_RECORD) { $env:WORKFLOW_LOOP_INSTALL_RECORD } else { Join-Path $recordBase "workflow-loop\install.json" }

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
        else { Stop-Uninstall "暂不支持的 Windows 架构：$architecture。" }
        $assetPath = Join-Path $TmpDir $UvAsset
        Invoke-WebRequest -Uri "$UvBaseUrl/$UvAsset" -OutFile $assetPath -UseBasicParsing
        $actualSha = (Get-FileHash -Algorithm SHA256 -Path $assetPath).Hash.ToLowerInvariant()
        if ($actualSha -ne $UvSha) { Stop-Uninstall "uv 下载文件的 SHA-256 与脚本内置摘要不符。" }
        $extractDir = Join-Path $TmpDir "uv"
        Expand-Archive -Path $assetPath -DestinationPath $extractDir -Force
        $uvExe = Get-ChildItem -Path $extractDir -Recurse -Filter "uv.exe" | Select-Object -First 1
        if (-not $uvExe) { Stop-Uninstall "解压后找不到 uv.exe。" }
        $UvBin = $uvExe.FullName
    }

    if (-not $Global) {
        $resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path
        if ((Get-Location).Path -ne $resolvedRoot) {
            Stop-Uninstall "项目卸载必须从目标项目根目录执行，不会向父目录查找。"
        }
        Write-Host "─── 项目卸载预检 ───"
        $preflight = Invoke-NativeCaptured $UvBin @("tool", "run", "--isolated", "--from", "$ProductName==$ProductVersion", "--python", $PythonBin, "--no-managed-python", "--no-python-downloads", "workflow", "_uninstall-project", "--check-only")
        Write-CapturedResult $preflight
        if ($preflight.ExitCode -ne 0) { Stop-Uninstall "无法确认当前项目的固定卸载范围。" }
        if (-not $Confirmed) {
            Write-Host "删除没有备份；当前轮次状态不会阻止卸载，业务代码和正式产物保持不变。"
            $answer = Read-Host "确认强制卸载当前项目？[y/N]"
            if ($answer -notmatch '^(y|yes)$') { Write-Host "已取消。当前项目未修改。"; exit 0 }
        }
        $removeProject = Invoke-NativeCaptured $UvBin @("tool", "run", "--isolated", "--from", "$ProductName==$ProductVersion", "--python", $PythonBin, "--no-managed-python", "--no-python-downloads", "workflow", "_uninstall-project", "--confirmed")
        Write-CapturedResult $removeProject
        if ($removeProject.ExitCode -ne 0) { Stop-Uninstall "项目卸载未完成；已删除内容不会恢复，解决残留后重新执行同一命令。" }
        exit 0
    }

    # Global mode deliberately does not resolve or inspect ProjectRoot.
    $workflowBin = Join-Path $ToolBinDir "workflow.exe"
    if (Test-Path -LiteralPath $workflowBin -PathType Leaf) {
        $identity = Invoke-NativeCaptured $workflowBin @("--version")
        if ($identity.ExitCode -ne 0 -or $identity.Stdout.Trim() -notmatch '^workflow-loop (.+)$') {
            Stop-Uninstall "$workflowBin 不是可确认的 Workflow Loop 命令，已保留。"
        }
    }

    if (-not $Confirmed) {
        Write-Host "═══ Workflow Loop 全局卸载确认 ═══"
        Write-Host "全局命令: $workflowBin"
        Write-Host "全局工具环境: $(Join-Path $ToolDir $ProductName)"
        Write-Host "PATH 来源记录: $InstallRecord"
        Write-Host "只删除来源记录能证明由 Workflow Loop 添加的 PATH 项；未知来源会保留并报告。"
        Write-Host "不会查找、扫描、读取或删除任何项目；其它项目将暂时无法运行 workflow。"
        $answer = Read-Host "确认只卸载电脑全局命令？[y/N]"
        if ($answer -notmatch '^(y|yes)$') { Write-Host "已取消。电脑和项目内容均未修改。"; exit 0 }
    }

    if ($WaitForProcessId -gt 0) {
        while (Get-Process -Id $WaitForProcessId -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 200 }
    }

    $toolEnvironment = Join-Path $ToolDir $ProductName
    if ((Test-Path -LiteralPath $workflowBin) -or (Test-Path -LiteralPath $toolEnvironment)) {
        $removeTool = Invoke-NativeCaptured $UvBin @("tool", "uninstall", $ProductName)
        Write-CapturedResult $removeTool
        if ($removeTool.ExitCode -ne 0) { Stop-Uninstall "全局工具删除失败；已完成内容不恢复，可以重新执行同一命令。" }
    }

    $pathMessage = "来源记录不存在；用户 PATH 保留。"
    if (Test-Path -LiteralPath $InstallRecord -PathType Leaf) {
        $record = $null
        try {
            $record = Get-Content -Raw -LiteralPath $InstallRecord | ConvertFrom-Json
        }
        catch {
            $pathMessage = "来源记录无法读取；PATH 保留：$($_.Exception.Message)"
        }
        if ($record) {
            if ($record.product -eq $ProductName -and $record.path_added -eq $true -and $record.path_scope -eq "user" -and $record.user_path_before -is [string] -and $record.user_path_after -is [string]) {
                $currentUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
                if (-not $currentUserPath) { $currentUserPath = "" }
                if ($currentUserPath -eq [string]$record.user_path_after) {
                    try {
                        [Environment]::SetEnvironmentVariable("Path", [string]$record.user_path_before, "User")
                    }
                    catch {
                        Stop-Uninstall "全局命令已删除，但用户 PATH 清理失败；来源记录已保留以便重试：$($_.Exception.Message)"
                    }
                    $pathMessage = "已删除 Workflow Loop 写入的用户 PATH 项。"
                }
                else {
                    $pathMessage = "用户 PATH 与来源记录不再精确匹配；PATH 保留。"
                }
            }
            else {
                $pathMessage = "来源记录未证明 PATH 由 Workflow Loop 添加；PATH 保留。"
            }
        }
        try {
            Remove-Item -Force -LiteralPath $InstallRecord -ErrorAction Stop
        }
        catch {
            Stop-Uninstall "全局命令已删除，但来源记录清理失败；可以重新执行同一命令：$($_.Exception.Message)"
        }
        $recordDirectory = Split-Path -Parent $InstallRecord
        if (Test-Path -LiteralPath $recordDirectory) {
            Remove-Item -LiteralPath $recordDirectory -ErrorAction SilentlyContinue
        }
    }
    Write-Host $pathMessage
    Write-Host "═══ 电脑全局 Workflow Loop 命令卸载完成 ═══"
    Write-Host "没有扫描或修改任何项目目录。"
}
finally {
    if (Test-Path -LiteralPath $TmpDir) { Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue }
    if ($CleanupDirectory -and (Test-Path -LiteralPath $CleanupDirectory)) {
        Remove-Item -Recurse -Force $CleanupDirectory -ErrorAction SilentlyContinue
    }
}
