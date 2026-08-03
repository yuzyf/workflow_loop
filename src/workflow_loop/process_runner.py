"""跨平台受控进程执行器。

主题测试和最终全量回归共用同一套执行行为：只接受命令参数数组和项目内工作目录，
不经过 Shell；POSIX 新建会话并按进程组先终止后强制结束；Windows 新建进程组并
使用系统进程树终止能力；所有路径都等待进程完成并收集有界输出。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

# 输出摘要保留的末尾字节数；完整输出只保存哈希和字节数，不落盘
OUTPUT_TAIL_BYTES = 8 * 1024
# 超时后先礼貌终止，再等这些秒数才强制结束
TERMINATE_GRACE_SECONDS = 5


@dataclass
class ProcessRequest:
    """一次受控执行请求。"""

    argv: list[str]
    # 项目内工作目录（绝对路径；由调用方校验在项目内）
    cwd: str
    timeout_seconds: int
    # 额外环境变量（在当前环境基础上覆盖）；None 表示原样继承
    extra_env: dict[str, str] | None = None


@dataclass
class ProcessResult:
    """一次受控执行的机器事实。"""

    status: str  # passed / failed / timeout / error
    exit_code: int | None
    started_at: str
    finished_at: str
    duration_seconds: float
    output_tail: str
    output_sha256: str
    output_bytes: int
    platform: str
    # argv[0] 解析出的实际可执行文件；无法解析时保留原样
    executable: str
    error_message: str = ""
    argv: list[str] = field(default_factory=list)
    cwd: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_executable(command: str) -> str:
    """返回当前环境实际会执行的程序路径；无法解析时保留原参数。"""
    return shutil.which(command) or command


def _kill_process_tree(process: subprocess.Popen) -> None:
    """按平台清理整个进程组或进程树，不遗留测试子进程。"""
    if sys.platform.startswith("win"):
        # Windows：使用系统进程树终止能力（taskkill /T /F）
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    # POSIX：进程在新会话中启动，按进程组先 SIGTERM，宽限后 SIGKILL
    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_process(request: ProcessRequest) -> ProcessResult:
    """执行一次命令并返回完整机器事实；超时后清理整个进程组或进程树。"""
    started_at = _now_iso()
    start_clock = time.monotonic()
    platform_name = sys.platform
    executable = resolve_executable(request.argv[0])

    env = None
    if request.extra_env:
        env = dict(os.environ)
        env.update(request.extra_env)

    popen_kwargs: dict = {
        "args": request.argv,
        "cwd": request.cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "shell": False,
        "env": env,
    }
    if sys.platform.startswith("win"):
        # 新建进程组，供 taskkill /T 清理整棵进程树
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        # 新建会话（同时成为新进程组组长），供 killpg 清理
        popen_kwargs["start_new_session"] = True

    def _finish(
        status: str,
        exit_code: int | None,
        output: bytes,
        error_message: str = "",
    ) -> ProcessResult:
        finished_at = _now_iso()
        tail = output[-OUTPUT_TAIL_BYTES:].decode("utf-8", errors="replace")
        return ProcessResult(
            status=status,
            exit_code=exit_code,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=round(time.monotonic() - start_clock, 3),
            output_tail=tail,
            output_sha256=hashlib.sha256(output).hexdigest(),
            output_bytes=len(output),
            platform=platform_name,
            executable=executable,
            error_message=error_message,
            argv=list(request.argv),
            cwd=request.cwd,
        )

    try:
        process = subprocess.Popen(**popen_kwargs)
    except (OSError, ValueError) as exc:
        return _finish("error", None, b"", f"无法启动命令: {exc}")

    try:
        output, _ = process.communicate(timeout=request.timeout_seconds)
    except subprocess.TimeoutExpired as first_timeout:
        _kill_process_tree(process)
        # communicate() 超时后的再次调用会返回从进程启动起的完整累计输出，
        # 不能再与第一次异常中的部分输出拼接，否则会重复计算摘要、哈希和字节数。
        try:
            output, _ = process.communicate(timeout=TERMINATE_GRACE_SECONDS + 5)
        except subprocess.TimeoutExpired as final_timeout:
            output = final_timeout.output
            if output is None:
                output = first_timeout.output
        if isinstance(output, str):
            output = output.encode("utf-8", errors="replace")
        return _finish(
            "timeout",
            None,
            output or b"",
            f"超过 {request.timeout_seconds} 秒未完成，已清理整个进程组或进程树",
        )

    exit_code = process.returncode
    status = "passed" if exit_code == 0 else "failed"
    return _finish(status, exit_code, output or b"")
