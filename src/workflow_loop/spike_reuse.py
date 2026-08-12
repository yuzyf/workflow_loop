"""在当前工作流中受控地重新运行历史穿刺资产。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import shutil
import stat
import sys
from dataclasses import asdict, dataclass
from datetime import datetime

from . import journal as journal_mod
from . import process_runner as process_runner_mod
from . import spike_validation as spike_validation_mod
from . import state as state_mod
from . import test_execution as test_execution_mod
from .stages.base import expected_spike_asset_path


DEFAULT_TIMEOUT_SECONDS = 600
MAX_TIMEOUT_SECONDS = 3600
_HEX_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PLACEHOLDER_CONCLUSIONS = {
    "",
    "无",
    "暂无",
    "待确认",
    "待补充",
    "符合预期",
    "运行成功",
    "通过",
}
_INLINE_EXECUTION_FLAGS = {
    "-c",
    "-e",
    "--eval",
    "--evaluate",
    "-command",
    "/c",
}


@dataclass(frozen=True)
class SpikeRerunPlan:
    """预检得到的重跑计划；预览命令只生成它，不启动进程。"""

    asset_path: str
    source_workflow_id: str
    current_workflow_id: str
    run_method: str
    command: list[str]
    cwd: str
    execution_cwd: str
    timeout_seconds: int
    asset_hash_before: str
    plan_id: str


@dataclass(frozen=True)
class SpikeRerunAttempt:
    """一次历史穿刺资产重跑的当前机器事实。"""

    asset_path: str
    source_workflow_id: str
    current_workflow_id: str
    command: list[str]
    cwd: str
    timeout_seconds: int
    status: str
    conclusion: str
    record_id: str
    result: process_runner_mod.ProcessResult
    record: state_mod.SpikeRerunRecord


def _normalized_asset_path(raw_path: str) -> str:
    if not isinstance(raw_path, str):
        raise ValueError("穿刺资产路径必须是字符串")
    normalized = raw_path.strip().strip("`").replace("\\", "/").rstrip("/")
    parts = normalized.split("/")
    if len(parts) != 4 or parts[:2] != [".workflow_loop", "spike_tmp"]:
        raise ValueError(
            "穿刺资产路径必须是 .workflow_loop/spike_tmp/<工作流编号>/<穿刺项标识>"
        )
    expected = expected_spike_asset_path(parts[2], parts[3])
    if normalized != expected:
        raise ValueError(f"穿刺资产路径不是受支持的隔离目录：{raw_path!r}")
    return normalized


def _find_historical_asset(
    workflow_state: state_mod.WorkflowState,
    relative_path: str,
) -> state_mod.SpikeAssetRegistration:
    normalized = _normalized_asset_path(relative_path)
    matches = [
        asset
        for asset in workflow_state.spike_assets
        if _normalized_asset_path(asset.relative_path) == normalized
    ]
    if not matches:
        raise ValueError(f"当前工作流没有继承这项已登记穿刺资产：{normalized}")
    if len(matches) != 1:
        raise ValueError(f"当前状态重复登记了同一穿刺资产：{normalized}")
    asset = matches[0]
    if asset.workflow_id != normalized.split("/")[2]:
        raise ValueError(f"历史穿刺资产登记来源与目录不一致：{normalized}")
    if asset.workflow_id == workflow_state.workflow_id:
        raise ValueError("该资产属于当前工作流，不是需要当前环境重跑的历史资产")
    if asset.status not in {"registered", "needs_revision"}:
        raise ValueError(f"历史穿刺资产状态无效：{asset.status!r}")
    return asset


def _validate_rerun_window(workflow_state: state_mod.WorkflowState) -> None:
    if workflow_state.run_status != "active":
        raise ValueError("只有进行中的完整研发工作流可以重跑历史穿刺资产")
    if workflow_state.intent == "light_task":
        raise ValueError("light_task（无需开发任务）不允许执行历史穿刺资产重跑")
    if workflow_state.current_stage not in {"spike", "acceptance_plan"}:
        raise ValueError(
            "历史穿刺资产必须在 spike（技术穿刺）或 acceptance_plan（验收计划）前段重跑；"
            "当前阶段已经进入后续交付，不能静默改写已确认结果"
        )
    current_stage = workflow_state.stages.get(workflow_state.current_stage)
    if current_stage is None:
        raise ValueError("当前工作流缺少历史穿刺重跑所需的阶段状态")
    if current_stage.gate.code_validated:
        stage_label = (
            "spike（技术穿刺）"
            if workflow_state.current_stage == "spike"
            else "acceptance_plan（验收计划）"
        )
        raise ValueError(f"{stage_label}第二道门已经校验，必须先退回该阶段再重跑历史穿刺资产")


def _validate_asset_directory(project_root: str, relative_path: str) -> str:
    full_path = os.path.join(project_root, *relative_path.split("/"))
    current = os.path.abspath(project_root)
    for component in relative_path.split("/"):
        current = os.path.join(current, component)
        if os.path.islink(current):
            raise ValueError(f"历史穿刺资产路径不能经过符号链接：{relative_path}")
    errors = spike_validation_mod.validate_reusable_asset_directory(
        project_root,
        relative_path,
        "历史穿刺资产重跑",
    )
    if errors:
        raise ValueError("\n".join(errors))
    return full_path


def _command_from_run_method(run_method: str) -> list[str]:
    if not isinstance(run_method, str):
        raise ValueError("历史穿刺资产缺少可执行的运行方法")
    normalized = run_method.strip()
    if normalized.startswith("`") and normalized.endswith("`"):
        normalized = normalized[1:-1].strip()
    if not normalized or "\n" in normalized or "\r" in normalized:
        raise ValueError("历史穿刺资产运行方法必须是一条完整命令")
    try:
        command = shlex.split(normalized, posix=os.name != "nt")
    except ValueError as exc:
        raise ValueError(f"历史穿刺资产运行方法无法解析：{exc}") from exc
    valid, detail = test_execution_mod.validate_command(command)
    if not valid:
        raise ValueError(f"历史穿刺资产运行方法不安全：{detail}")
    if any(
        token.casefold().split("=", 1)[0] in _INLINE_EXECUTION_FLAGS
        for token in command[1:]
    ):
        raise ValueError(
            "历史穿刺资产运行方法不能执行内联代码或 shell 命令串；"
            "必须运行资产目录中已登记的真实文件"
        )
    return command


def _validate_command_executable(
    asset_directory: str,
    command: list[str],
) -> None:
    """限制 argv[0]（第一个参数，即启动程序）为登记阶段允许的入口。"""

    executable = command[0]
    has_path = os.path.isabs(executable) or "/" in executable or "\\" in executable
    if not has_path:
        if spike_validation_mod.is_reusable_asset_executable_name(executable):
            return
        candidate_path = os.path.join(asset_directory, executable)
    else:
        candidate_path = (
            executable
            if os.path.isabs(executable)
            else os.path.join(asset_directory, executable)
        )
    candidate = os.path.realpath(candidate_path)
    asset_real = os.path.realpath(asset_directory)
    try:
        inside_asset = os.path.commonpath([asset_real, candidate]) == asset_real
    except ValueError:
        inside_asset = False
    if inside_asset:
        if os.path.islink(candidate_path) or not os.path.isfile(candidate):
            raise ValueError("历史穿刺资产运行方法引用的资产内启动程序不是普通文件")
        return

    # 允许把裸命令解析结果写成绝对路径，但必须和当前环境同名命令的真实解析结果一致。
    # 这样 `/tmp/python` 或 `./python` 不能只靠伪装 basename（文件名）绕过边界。
    if spike_validation_mod.is_reusable_asset_executable_name(executable):
        basename = os.path.basename(executable.replace("\\", "/"))
        resolved = shutil.which(basename)
        trusted_paths = {
            os.path.realpath(path)
            for path in (resolved, sys.executable)
            if path
        }
        if candidate in trusted_paths and os.path.isfile(candidate):
            return
    raise ValueError(
        "历史穿刺资产运行方法的启动程序不在登记允许集合中；"
        "只能使用 python、pytest、node、npm、bash、sh 等裸命令，"
        "当前环境解析出的同名程序，或资产目录内的真实文件"
    )


def _command_cwd(
    project_root: str,
    asset_path: str,
    asset_directory: str,
    command: list[str],
) -> tuple[str, str]:
    normalized_tokens = [token.strip().strip("`").replace("\\", "/") for token in command]
    if any(
        token == asset_path or token.startswith(asset_path + "/")
        for token in normalized_tokens[1:]
    ):
        cwd = project_root
        cwd_relative = ""
    else:
        cwd = asset_directory
        cwd_relative = asset_path

    for token in normalized_tokens[1:]:
        value = token.split("=", 1)[1] if "=" in token else token
        if not value or value.startswith("-"):
            continue
        looks_like_path = (
            os.path.isabs(value)
            or "/" in value
            or value.startswith(".")
            or os.path.lexists(os.path.join(asset_directory, *value.split("/")))
        )
        if not looks_like_path:
            continue
        if value == asset_path or value.startswith(asset_path + "/"):
            candidate = os.path.realpath(
                os.path.join(project_root, *value.split("/"))
            )
        elif os.path.isabs(value):
            candidate = os.path.realpath(value)
        else:
            candidate = os.path.realpath(
                os.path.join(asset_directory, *value.split("/"))
            )
        asset_real = os.path.realpath(asset_directory)
        try:
            inside_asset = os.path.commonpath([asset_real, candidate]) == asset_real
        except ValueError:
            inside_asset = False
        if not inside_asset:
            raise ValueError(
                "历史穿刺资产运行方法引用了资产目录之外的路径："
                f"{token}"
            )
        if os.path.islink(candidate):
            raise ValueError(f"历史穿刺资产运行方法不能引用符号链接：{token}")

    # `npm test`、`make` 等命令通过工作目录读取资产内配置，不一定显式写文件名。
    # 仍固定在资产目录执行，绝不把历史方法当成项目根任意命令。
    return cwd, cwd_relative


def _validated_conclusion(conclusion: str) -> str:
    normalized = conclusion.strip() if isinstance(conclusion, str) else ""
    if normalized.casefold() in {value.casefold() for value in _PLACEHOLDER_CONCLUSIONS}:
        raise ValueError("必须写出本次重跑后得到的具体技术结论，不能只写成功或符合预期")
    if len(normalized) > 2000:
        raise ValueError("本次重跑结论过长，最多 2000 个字符")
    return normalized


def compute_asset_directory_hash(asset_directory: str) -> str:
    """按相对路径、文件内容和权限计算稳定目录哈希，不绑定时间戳。"""

    if not os.path.isdir(asset_directory) or os.path.islink(asset_directory):
        raise ValueError(f"资产目录不存在或不是普通目录：{asset_directory}")
    digest = hashlib.sha256()
    root_mode = stat.S_IMODE(os.stat(asset_directory, follow_symlinks=False).st_mode)
    digest.update(json.dumps(["root", root_mode], separators=(",", ":")).encode("utf-8"))
    for root, directories, files in os.walk(
        asset_directory,
        topdown=True,
        followlinks=False,
    ):
        directories.sort()
        files.sort()
        for directory in directories:
            directory_path = os.path.join(root, directory)
            if os.path.islink(directory_path):
                raise ValueError(f"资产目录在哈希期间出现符号链接：{directory_path}")
            relative = os.path.relpath(directory_path, asset_directory).replace(os.sep, "/")
            mode = stat.S_IMODE(
                os.stat(directory_path, follow_symlinks=False).st_mode
            )
            digest.update(
                json.dumps(
                    ["directory", relative, mode],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        for filename in files:
            file_path = os.path.join(root, filename)
            if os.path.islink(file_path) or not os.path.isfile(file_path):
                raise ValueError(f"资产目录在哈希期间出现非普通文件：{file_path}")
            relative = os.path.relpath(file_path, asset_directory).replace(os.sep, "/")
            mode = stat.S_IMODE(os.stat(file_path, follow_symlinks=False).st_mode)
            file_digest = hashlib.sha256()
            with open(file_path, "rb") as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    file_digest.update(chunk)
            digest.update(
                json.dumps(
                    ["file", relative, mode, file_digest.hexdigest()],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
    return digest.hexdigest()


def plan_historical_asset_rerun(
    project_root: str,
    workflow_state: state_mod.WorkflowState,
    relative_path: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> SpikeRerunPlan:
    """只做重跑预检并返回计划；不会启动命令或修改状态。"""

    _validate_rerun_window(workflow_state)
    if timeout_seconds <= 0 or timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"历史穿刺资产重跑超时必须在 1 至 {MAX_TIMEOUT_SECONDS} 秒之间"
        )
    asset = _find_historical_asset(workflow_state, relative_path)
    normalized_path = _normalized_asset_path(asset.relative_path)
    asset_directory = _validate_asset_directory(project_root, normalized_path)
    command = _command_from_run_method(asset.run_method)
    _validate_command_executable(asset_directory, command)
    cwd, cwd_relative = _command_cwd(
        project_root,
        normalized_path,
        asset_directory,
        command,
    )
    plan_facts = {
        "asset_path": normalized_path,
        "source_workflow_id": asset.workflow_id,
        "current_workflow_id": workflow_state.workflow_id,
        "current_stage": workflow_state.current_stage,
        "run_method": asset.run_method,
        "command": command,
        "cwd": cwd_relative,
        "timeout_seconds": timeout_seconds,
        "asset_hash_before": compute_asset_directory_hash(asset_directory),
    }
    plan_id = "SPIKE-PLAN-" + hashlib.sha256(
        json.dumps(
            plan_facts,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return SpikeRerunPlan(
        asset_path=normalized_path,
        source_workflow_id=asset.workflow_id,
        current_workflow_id=workflow_state.workflow_id,
        run_method=asset.run_method,
        command=command,
        cwd=cwd_relative,
        execution_cwd=cwd,
        timeout_seconds=timeout_seconds,
        asset_hash_before=plan_facts["asset_hash_before"],
        plan_id=plan_id,
    )


def _record_payload(record: state_mod.SpikeRerunRecord) -> dict:
    payload = asdict(record)
    payload.pop("record_id", None)
    return payload


def compute_spike_rerun_record_id(record: state_mod.SpikeRerunRecord) -> str:
    """根据完整重跑机器事实重新计算不可手改的记录编号。"""

    digest = hashlib.sha256(
        json.dumps(
            _record_payload(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]
    compact_time = re.sub(r"[^0-9A-Za-z]", "", record.started_at or "unknown")
    return f"SPIKE-RUN-{compact_time}-{digest}"


def _failure_conclusion(
    result: process_runner_mod.ProcessResult,
    post_run_errors: list[str],
    hash_error: str | None,
    hash_changed: bool,
) -> str:
    reasons = []
    if result.status != "passed":
        reasons.append(f"当前重跑未成功（{result.status}）")
    if hash_changed:
        reasons.append("执行前后资产目录哈希不一致，说明运行过程修改了资产")
    if hash_error:
        reasons.append(f"执行后无法确认资产目录哈希：{hash_error}")
    if post_run_errors:
        reasons.extend(post_run_errors)
    reason_text = "；".join(reasons) or "当前重跑未形成可复用机器证据"
    return f"{reason_text}；历史结论不可沿用"


def rerun_historical_asset(
    project_root: str,
    workflow_state: state_mod.WorkflowState,
    relative_path: str,
    conclusion: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    expected_plan_id: str | None = None,
) -> SpikeRerunAttempt:
    """真实执行历史资产，并把完整机器事实写回当前工作流内存状态。"""

    plan = plan_historical_asset_rerun(
        project_root,
        workflow_state,
        relative_path,
        timeout_seconds=timeout_seconds,
    )
    if expected_plan_id is not None and plan.plan_id != expected_plan_id:
        raise ValueError(
            "重跑计划已经变化；资产内容、运行方法、工作目录、超时或当前阶段与预览不一致，"
            "必须重新预览后再确认"
        )
    accepted_conclusion = _validated_conclusion(conclusion)
    asset = _find_historical_asset(workflow_state, plan.asset_path)

    result = process_runner_mod.run_process(
        process_runner_mod.ProcessRequest(
            argv=plan.command,
            cwd=plan.execution_cwd,
            timeout_seconds=plan.timeout_seconds,
        )
    )

    post_run_errors = spike_validation_mod.validate_reusable_asset_directory(
        project_root,
        plan.asset_path,
        "历史穿刺资产重跑后检查",
    )
    asset_directory = os.path.join(project_root, *plan.asset_path.split("/"))
    post_hash_error: str | None = None
    try:
        asset_hash_after = compute_asset_directory_hash(asset_directory)
    except (OSError, ValueError) as exc:
        asset_hash_after = ""
        post_hash_error = str(exc)
    hash_changed = bool(asset_hash_after) and asset_hash_after != plan.asset_hash_before
    if result.status != "passed":
        effective_status = result.status
    else:
        effective_status = "passed"
    if post_run_errors or post_hash_error or hash_changed:
        effective_status = "blocked"

    if effective_status == "passed":
        effective_conclusion = accepted_conclusion
        asset.status = "registered"
    else:
        effective_conclusion = _failure_conclusion(
            result,
            post_run_errors,
            post_hash_error,
            hash_changed,
        )
        asset.status = "needs_revision"

    record = state_mod.SpikeRerunRecord(
        source_workflow_id=asset.workflow_id,
        current_workflow_id=workflow_state.workflow_id,
        asset_path=plan.asset_path,
        asset_hash_before=plan.asset_hash_before,
        asset_hash_after=asset_hash_after,
        run_method=asset.run_method,
        command=list(plan.command),
        cwd=plan.cwd,
        timeout_seconds=plan.timeout_seconds,
        started_at=result.started_at,
        finished_at=result.finished_at,
        duration_seconds=result.duration_seconds,
        status=effective_status,
        exit_code=result.exit_code,
        output_sha256=result.output_sha256,
        output_bytes=result.output_bytes,
        platform=result.platform,
        executable=result.executable,
        conclusion=effective_conclusion,
    )
    record = state_mod.SpikeRerunRecord(
        **{**asdict(record), "record_id": compute_spike_rerun_record_id(record)}
    )

    # 平面字段保留给旧文档和人工查看；完整记录是门禁唯一可信来源。
    asset.last_rerun_workflow_id = workflow_state.workflow_id
    asset.last_rerun_at = record.finished_at
    asset.last_rerun_status = record.status
    asset.last_rerun_conclusion = record.conclusion
    asset.last_rerun_record = record

    return SpikeRerunAttempt(
        asset_path=plan.asset_path,
        source_workflow_id=asset.workflow_id,
        current_workflow_id=workflow_state.workflow_id,
        command=list(plan.command),
        cwd=plan.cwd,
        timeout_seconds=plan.timeout_seconds,
        status=effective_status,
        conclusion=effective_conclusion,
        record_id=record.record_id,
        result=result,
        record=record,
    )


def _record_problems(
    project_root: str,
    asset: state_mod.SpikeAssetRegistration,
    workflow_id: str,
) -> list[str]:
    record = asset.last_rerun_record
    if record is None:
        return ["缺少结构化重跑机器记录"]
    problems: list[str] = []
    if asset.workflow_id == workflow_id:
        return []
    if record.source_workflow_id != asset.workflow_id:
        problems.append("记录来源工作流与资产登记不一致")
    if record.current_workflow_id != workflow_id:
        problems.append("记录不是当前工作流生成的")
    if asset.last_rerun_workflow_id != record.current_workflow_id:
        problems.append("平面字段 last_rerun_workflow_id（最近重跑工作流）与记录不一致")
    if asset.last_rerun_at != record.finished_at:
        problems.append("平面字段 last_rerun_at（最近重跑时间）与记录不一致")
    if asset.last_rerun_status != record.status:
        problems.append("平面字段 last_rerun_status（最近重跑状态）与记录不一致")
    if asset.last_rerun_conclusion != record.conclusion:
        problems.append("平面字段 last_rerun_conclusion（最近重跑结论）与记录不一致")
    if record.asset_path != asset.relative_path.replace("\\", "/").rstrip("/"):
        problems.append("记录资产路径与登记路径不一致")
    if record.status != "passed" or record.exit_code != 0:
        problems.append("记录状态不是 passed（通过）且退出码 0")
    if asset.status != "registered":
        problems.append("资产当前状态不是 registered（已登记）")
    if not record.asset_hash_before or not _HEX_SHA256_RE.fullmatch(record.asset_hash_before):
        problems.append("缺少有效的执行前资产目录哈希")
    if not record.asset_hash_after or not _HEX_SHA256_RE.fullmatch(record.asset_hash_after):
        problems.append("缺少有效的执行后资产目录哈希")
    if record.asset_hash_before != record.asset_hash_after:
        problems.append("执行前后资产目录哈希不一致")
    if record.run_method != asset.run_method:
        problems.append("资产运行方法已经变化")
    if not record.command or record.command != _safe_command(asset.run_method):
        problems.append("记录命令与当前登记运行方法不一致")
    if record.timeout_seconds is None or not (0 < record.timeout_seconds <= MAX_TIMEOUT_SECONDS):
        problems.append("记录超时参数无效")
    if not record.started_at or not record.finished_at or record.duration_seconds is None:
        problems.append("记录缺少完整开始、结束时间或时长")
    if record.duration_seconds is not None and record.duration_seconds < 0:
        problems.append("记录时长不能为负数")
    if not isinstance(record.output_bytes, int) or record.output_bytes < 0:
        problems.append("记录输出字节数无效")
    if not isinstance(record.output_sha256, str) or not _HEX_SHA256_RE.fullmatch(record.output_sha256):
        problems.append("记录输出哈希无效")
    if not record.platform or not record.executable:
        problems.append("记录缺少平台或可执行程序事实")
    try:
        normalized_path = _normalized_asset_path(asset.relative_path)
        asset_directory = _validate_asset_directory(project_root, normalized_path)
        command = _command_from_run_method(asset.run_method)
        _validate_command_executable(asset_directory, command)
        _cwd, cwd_relative = _command_cwd(
            project_root,
            normalized_path,
            asset_directory,
            command,
        )
        if record.cwd != cwd_relative:
            problems.append("记录工作目录与当前运行方法推导结果不一致")
        current_hash = compute_asset_directory_hash(asset_directory)
        if current_hash != record.asset_hash_after:
            problems.append("当前资产目录哈希已变化")
    except (OSError, ValueError) as exc:
        problems.append(f"当前资产目录或运行方法无法重新核对：{exc}")
    if not record.conclusion:
        problems.append("记录缺少本轮具体技术结论")
    try:
        _validated_conclusion(record.conclusion)
    except ValueError as exc:
        problems.append(str(exc))
    if record.record_id != compute_spike_rerun_record_id(record):
        problems.append("记录编号与完整机器事实不一致")
    return problems


def _safe_command(run_method: str) -> list[str]:
    try:
        return _command_from_run_method(run_method)
    except ValueError:
        return []


def historical_asset_has_current_success(
    project_root: str,
    asset: state_mod.SpikeAssetRegistration,
    workflow_id: str,
) -> bool:
    """判断历史资产是否仍有可作为当前验收依据的完整机器证据。"""

    return not _record_problems(project_root, asset, workflow_id)


def historical_asset_success_problems(
    project_root: str,
    asset: state_mod.SpikeAssetRegistration,
    workflow_id: str,
) -> list[str]:
    """返回历史资产当前机器证据失效原因，供追踪门禁给出具体阻塞信息。"""

    return _record_problems(project_root, asset, workflow_id)
