import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


# state.json 的相对路径（相对于项目根）
# 放在 .workflow_loop/ 下，和 journal.jsonl、project.json 同级
STATE_FILE = os.path.join(".workflow_loop", "state.json")


# 单个 stage 的 3 道闸状态（门禁策略第一版：顺序硬性）
# 三道闸依次推进：讨论完毕 → 代码校验 → 用户确认
# 跳步直接报错，不能跳过前一道直接调后一道
@dataclass
class GateState:
    # 第 1 道闸：用户确认讨论完毕（AI 和用户已经用提示词充分讨论）
    discussion_complete: bool = False
    # 第 2 道闸：代码侧校验通过（文件存在 / 内容哈希匹配等）
    code_validated: bool = False
    # 第 3 道闸：用户确认产出写完了（最终由用户拍板，AI 不得代确认）
    user_confirmed: bool = False


@dataclass
class TestExecutionRecord:
    """一个测试项本次成功执行后的机器记录。

    这里保存程序判断"这次是否真的执行过"的机器事实：命令、工作目录、超时、
    时间、时长、退出码、输出摘要、输出哈希和执行时的代码版本。
    可读的测试结论和证据由主题测试结果文档记录，并逐项引用这里的记录编号。
    """

    test_entries: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    # 项目内工作目录（相对项目根；空表示项目根）
    cwd: str = ""
    timeout_seconds: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    exit_code: int | None = None
    status: str = "passed"
    environment: dict[str, str] = field(default_factory=dict)
    code_snapshot_hash: str | None = None
    test_code_hash: str | None = None
    # 机器记录编号：验收记录和结果文档用它引用这次精确执行
    record_id: str | None = None
    # 有界输出事实：末尾摘要、完整输出哈希和字节数
    output_tail: str = ""
    output_sha256: str | None = None
    output_bytes: int | None = None
    platform: str = ""
    executable: str = ""
    # 结构化测试报告机器事实；None 表示旧记录没有该项事实，不能继续算成功。
    report_adapter: str | None = None
    report_hash: str | None = None
    report_size: int | None = None
    executed_count: int | None = None
    skipped_count: int | None = None
    failed_count: int | None = None
    error_count: int | None = None
    matched_test_entries: list[str] | None = None


@dataclass
class TestTaskState:
    """测试执行前登记的一个测试项任务。"""

    test_entries: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    # 项目内工作目录（相对项目根；空表示项目根）
    cwd: str = ""
    dependencies: list[str] = field(default_factory=list)
    timeout_seconds: int = 600
    # 由程序登记的报告适配器和项目内临时报告路径。
    report_adapter: str | None = None
    report_path: str | None = None
    status: str = "pending"
    prepared_at: str | None = None
    last_error: str | None = None
    current_record: TestExecutionRecord | None = None


@dataclass
class AcceptanceCriterionRecord:
    """一条验收条件当前仍有效的验收记录。"""

    topic: str = ""
    criterion_id: str = ""
    method: str = ""
    result: str = "passed"
    actual_result: str = ""
    user_answer: str | None = None
    evidence: str = ""
    confirmed_at: str | None = None
    acceptance_plan_hash: str | None = None
    impl_hash: str | None = None
    test_result_hash: str | None = None
    test_ids: list[str] = field(default_factory=list)
    # 作为验收依据的机器测试记录编号列表；自动化或混合验收指向精确执行事实
    test_record_ids: list[str] = field(default_factory=list)
    record_id: str | None = None


# 单个 stage 的完整状态
# 嵌套在 WorkflowState.stages 字典里，key 是 stage 名（如 "spec" / "impl"）
@dataclass
class StageState:
    # stage 生命周期状态：pending（没开始）→ in_progress（AI 在做）→ gated（等门禁）→ done（过了门禁）
    status: str = "pending"
    # 期望产出的文件路径列表（相对项目根），可能多个（如 spec/产品总说明.md + spec/功能_*.md）
    artifact_paths: list[str] = field(default_factory=list)
    # 产出文件首次出现的时间戳（ISO 8601 UTC），用于 journal 追溯
    artifact_produced_at: str | None = None
    # 用户确认讨论完成时保存的文件基线时间；用于判断本阶段是否真的修改了产物
    artifact_baseline_captured_at: str | None = None
    # 基线文件哈希，key 是项目根下的相对路径，value 是 SHA256；文件当时不存在时为 None
    artifact_baseline_hashes: dict[str, str | None] = field(default_factory=dict)
    # impl 阶段进入时的代码快照哈希；用于阻止实施计划确认前修改代码
    code_baseline_hash: str | None = None
    # test_code 阶段进入时的测试代码快照哈希；用于确认本阶段确实新增或修改了测试代码
    test_code_baseline_hash: str | None = None
    # test_code 阶段进入时的非测试代码快照哈希；用于阻止测试阶段偷偷修改产品代码
    non_test_code_baseline_hash: str | None = None
    # 用户确认代码在实施计划确认前已经存在时，保存被确认的代码快照哈希
    existing_code_accepted_hash: str | None = None
    # 上游变化后，用户确认当前测试代码仍符合最新测试计划时保存的测试代码快照哈希
    existing_test_code_accepted_hash: str | None = None
    # workflow discuss 读取的全局规范、阶段模板和补充规范的组合哈希。
    # 材料变化后，旧的讨论确认自动失效，必须重新阅读后再过门禁。
    discussion_material_hash: str | None = None
    # impl 阶段用户最后确认的实施计划哈希；计划调整重新确认后更新
    plan_confirmed_hash: str | None = None
    # test_execution 阶段的任务登记：第一层 key 是主题，第二层 key 是 TC 编号。
    test_tasks: dict[str, dict[str, TestTaskState]] = field(default_factory=dict)
    # topic_acceptance 阶段的当前有效验收记录：第一层 key 是主题，第二层 key 是 AC 编号。
    acceptance_records: dict[str, dict[str, AcceptanceCriterionRecord]] = field(default_factory=dict)
    # 该 stage 的 3 道闸状态，嵌套 dataclass
    gate: GateState = field(default_factory=GateState)


# 架构文档双阶段完成度标记（CONTEXT.md "Architecture Gate Marks"）
# 同一份 spec/代码架构设计.md 的两种完成度，不是两个无关文件
@dataclass
class ArchitectureState:
    # 初步架构完成：前段架构 stage（code_design/revise_code_design/project_design_init）--confirmed 后置 true
    preliminary_done: bool = False
    # 最终设计同步完成：末段 update_code_design --confirmed 后置 true
    # 文件存在只是必要条件，不得因已存在而自动跳过最终设计同步
    detailed_done: bool = False


@dataclass
class RecoveryContext:
    """上游变化或用户主动退回后，解释为什么重新经过当前阶段。"""

    # 引发退回的阶段，例如 test_plan（测试计划阶段）
    source_stage: str | None = None
    # 用户确认的返回目标阶段（workflow return --to 的目标）
    return_target: str | None = None
    # 发生退回的具体原因
    reason: str | None = None
    # 需要重新确认或重新执行的阶段，按原路径顺序保存
    affected_stages: list[str] = field(default_factory=list)
    # 用户确认的直接受影响主题；空列表表示未按主题区分
    affected_topics: list[str] = field(default_factory=list)
    # 发生时间 ISO 8601 UTC
    created_at: str | None = None


# Verification Invalidation 的哈希绑定（CONTEXT.md "Verification Invalidation"）
# 通过状态只对绑定的上游内容有效；上游变化时下游门禁清零
@dataclass
class VerificationState:
    # 实施代码 + impl/ 下全部实施记录的 SHA256 哈希
    # 在 gate impl --confirmed 时记录；测试代码或测试结果变化不会改写它
    impl_hash: str | None = None
    # qa/<主题文件标识>_测试计划.md 内容的 SHA256 哈希
    # 在 gate test_plan --confirmed 时记录；变化时使主题执行、最终全量回归和整体验收失效
    test_plan_hash: str | None = None
    # acceptance/索引.md 和 acceptance/<主题文件标识>_验收计划.md 内容的 SHA256 哈希
    # 在 gate acceptance_plan --confirmed 时记录；变化时退回测试计划和后续阶段
    acceptance_plan_hash: str | None = None
    # test_code 确认后的测试代码、测试配置和统一测试入口哈希
    # 在 gate test_code --confirmed 时记录；变化时退回 test_code
    test_code_hash: str | None = None
    # qa/<主题文件标识>_测试结果.md 内容的 SHA256 哈希
    # 在 gate test_execution --confirmed 时记录；变化时使主题验收及后续阶段失效
    test_result_hash: str | None = None
    # acceptance/<主题文件标识>_验收结果.md 内容的 SHA256 哈希
    # 在 gate topic_acceptance --confirmed 时记录；变化时使最终回归及后续阶段失效
    acceptance_result_hash: str | None = None
    # 最终回归执行状态的 SHA256 哈希
    # 在 gate regression_test --confirmed 时记录；代码或状态变化时清零后续验收
    regression_test_result_hash: str | None = None


# 最终全量回归状态；由 regression_test 阶段自动执行项目统一测试入口写入。
# 修改前全量测试基线（旧 TestBaselineState）已经删除：读取旧状态时忽略该字段，
# 不再写回；实施前没有任何全量测试执行路径。
@dataclass
class RegressionTestState:
    # 项目配置中的统一测试入口（当前平台实际选中的参数数组）
    entry: list[str] = field(default_factory=list)
    # 实际执行的命令参数数组
    command: list[str] = field(default_factory=list)
    # 项目内工作目录（相对项目根；空表示项目根）
    cwd: str = ""
    # 最终全量入口允许运行的最长秒数
    timeout_seconds: int | None = None
    # 开始和结束时间（ISO 8601 UTC）
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    # not_run / passed / failed / timeout / error / unavailable
    status: str = "not_run"
    # 测试进程退出码；无法启动或超时时为空
    exit_code: int | None = None
    # 执行时对应的完整代码快照哈希
    code_snapshot_hash: str | None = None
    # 机器记录编号：追踪表和整体验收用它引用这次精确执行
    record_id: str | None = None
    # 有界输出事实
    output_tail: str = ""
    output_sha256: str | None = None
    output_bytes: int | None = None
    platform: str = ""
    executable: str = ""


# 穿刺阶段开始时的设计文档基线
# 门2用它判断穿刺结论要求修改设计时，相关文档是否真的发生了变化
@dataclass
class SpikeBaselineState:
    # 记录基线的时间；非空表示已经完成基线记录，即使某个文件当时不存在
    captured_at: str | None = None
    # spec/产品总说明.md 及其功能清单链接文档的整体 SHA256 哈希
    product_design_hash: str | None = None
    # 参与产品设计整体哈希的相对路径，便于状态检查和问题定位
    product_design_paths: list[str] = field(default_factory=list)
    # spec/代码架构设计.md 的 SHA256 哈希
    code_design_hash: str | None = None
    # 旧工作流已经进入 spike，但旧 state.json 没有保存入场基线
    # True 表示无法可靠还原穿刺开始前的设计内容，不能假装当前文件就是旧基线
    legacy_unavailable: bool = False


@dataclass
class RollbackState:
    """当前 Run 的实施代码回退清单。"""

    manifest_path: str | None = None
    manifest_hash: str | None = None
    prepared_at: str | None = None
    plan_hash: str | None = None
    code_baseline_hash: str | None = None
    planned_paths: list[str] = field(default_factory=list)
    # 整轮作废的逐项恢复进度：恢复开始、全部项目已恢复、临时副本清理完成。
    # 逐项状态保存在回退清单文件中；部分作废不会被写成整体恢复完成。
    restore_started_at: str | None = None
    # abort 已经恢复代码、但临时副本尚未清理完成时记录时间。
    # 重试 abort 只继续清理，不能再次覆盖用户在恢复后做的新修改。
    restored_at: str | None = None
    cleanup_completed_at: str | None = None


@dataclass
class LightTaskState:
    """无需开发任务的最小状态，不使用研发阶段和三道门。"""

    # discussion（讨论中）→ execution（执行中）→ result_confirmed（结果已确认）
    phase: str = "discussion"
    # 用户确认讨论完成时，记录双方达成共识的任务范围
    task_summary: str = ""
    # 用户确认讨论完成时，记录完成后如何核对真实结果
    verification_method: str = ""
    # 最近一次由用户单独批准的难撤销操作；完整历史保存在 journal.jsonl
    last_approved_action: str = ""
    # 用户核对并确认的实际结果；作废时则记录当时的真实状态
    result_summary: str = ""


# 整个 workflow Run 的当前快照，对应 state.json 的完整结构
# 每次 CLI 调用都是新进程，state 必须落盘，下次进程启动时读回来
@dataclass
class WorkflowState:
    # 启动时生成，格式 YYYY-MM-DD-HHmm-<intent>，用于 journal 追溯和文件名
    workflow_id: str
    # 工作意图：from_scratch / product_change / bugfix / light_task（替代旧 entry/scenario）
    intent: str
    # Run 生命周期：active（进行中）/ completed（done 收工）/ aborted（abort 作废）
    # 替代用 current_stage=completed 推断 Run 状态的旧模型
    run_status: str = "active"
    # 当前 stage 名（如 "spec" / "impl" / ...）；末段 --confirmed 后临时置 "completed"，由 done 确认
    current_stage: str = ""
    # 启动时间 ISO 8601 UTC
    started_at: str = ""
    # done 时写结束时间（run_status=completed）；abort 时为 None
    ended_at: str | None = None
    # abort 时写作废时间（run_status=aborted）；done 时为 None
    aborted_at: str | None = None
    # 旧版单主题字段。只用于读取旧 state.json；新流程使用 topics。
    topic: str | None = None
    # 本次需求的全部验收主题。修 bug 在 reproduce 确认，其他意图在 acceptance_plan 确认。
    topics: list[str] = field(default_factory=list)
    # 从零做清场确认标记：workflow start --intent from_scratch --confirm-clean 时置 true
    clean_confirmed: bool = False
    # spike 跳过标记：gate spike --skip 时置 true
    spike_skipped: bool = False
    # PathComposer 在 start 时解析出的完整 stage 名顺序，固定不再变
    # 后续命令（discuss/gate）读这个列表找当前 stage 对应的策略类
    stage_path: list[str] = field(default_factory=list)
    # 每个 stage 的细粒度状态，key 是 stage 名
    stages: dict[str, StageState] = field(default_factory=dict)
    # 架构门禁标记（初步/详细），见 ArchitectureState
    architecture: ArchitectureState = field(default_factory=ArchitectureState)
    # 验证绑定哈希，见 VerificationState
    verification: VerificationState = field(default_factory=VerificationState)
    # 最终全量回归状态，见 RegressionTestState
    regression_test: RegressionTestState = field(default_factory=RegressionTestState)
    # 穿刺进入时的产品设计和代码设计基线
    spike_baseline: SpikeBaselineState = field(default_factory=SpikeBaselineState)
    # 实施前保存的真实文件内容；只用于整个 Run 中止时恢复代码
    rollback: RollbackState = field(default_factory=RollbackState)
    # 上游失效或用户主动退回后的恢复说明；用于 status 和“下一步”解释当前阶段
    recovery: RecoveryContext = field(default_factory=RecoveryContext)
    # 无需开发任务的简单流程状态；三种完整研发意图中为空
    light_task: LightTaskState | None = None
    # 自由扩展口子（hooks 等后面用，第一版为空）
    meta: dict = field(default_factory=dict)


# 生成 ISO 8601 UTC 时间戳，microsecond=0 让时间戳更干净
# 供 state 的 started_at/ended_at/aborted_at 和 journal 的 ts 字段复用
def now_iso() -> str:
    # datetime.now(timezone.utc) 拿到 UTC 时间
    # .replace(microsecond=0) 去掉微秒
    # .isoformat() 转 ISO 8601 字符串
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# 把 WorkflowState dataclass 转成可 JSON 序列化的 dict
# asdict 会递归把 dataclass 转成 dict，包括嵌套的 StageState 和 GateState
def state_to_dict(state: WorkflowState) -> dict:
    return asdict(state)


def execution_task_has_current_success(task: TestTaskState) -> bool:
    """统一判断测试任务是否有完整、严格且可复用的当前成功事实。"""

    record = task.current_record
    if task.status != "passed" or record is None:
        return False
    integer_facts = (
        record.report_size,
        record.executed_count,
        record.skipped_count,
        record.failed_count,
        record.error_count,
    )
    if any(type(value) is not int for value in integer_facts):
        return False
    if not task.test_entries or len(set(task.test_entries)) != len(task.test_entries):
        return False
    matched = record.matched_test_entries
    return (
        record.status == "passed"
        and record.exit_code == 0
        and record.command == task.command
        and len(record.test_entries) == len(task.test_entries)
        and set(record.test_entries) == set(task.test_entries)
        and task.report_adapter in {"vitest-junit", "pytest-junitxml"}
        and record.report_adapter == task.report_adapter
        and bool(task.report_path)
        and isinstance(record.report_hash, str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", record.report_hash))
        and record.report_size > 0
        and record.executed_count > 0
        and record.skipped_count == 0
        and record.failed_count == 0
        and record.error_count == 0
        and isinstance(matched, list)
        and len(matched) == len(task.test_entries)
        and set(matched) == set(task.test_entries)
        and record.executed_count + record.skipped_count == len(matched)
        and bool(record.code_snapshot_hash)
        and bool(record.test_code_hash)
    )


def compute_test_execution_record_id(
    record: TestExecutionRecord,
    topic: str,
    test_id: str,
) -> str:
    """生成覆盖进程、报告、目标和代码事实的稳定机器记录编号。"""

    payload = asdict(record)
    payload["record_id"] = None
    encoded = json.dumps(
        {"topic": topic, "test_id": test_id, "record": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:8]
    compact_time = (record.started_at or "").replace(":", "").replace("-", "")
    return f"RUN-{compact_time}-{digest}"


def _test_execution_record_from_dict(data: dict | None) -> TestExecutionRecord | None:
    if not isinstance(data, dict):
        return None
    command = data.get("command", [])
    if isinstance(command, str):
        command = [command] if command else []
    return TestExecutionRecord(
        test_entries=data.get("test_entries", []),
        command=command,
        cwd=data.get("cwd", ""),
        timeout_seconds=data.get("timeout_seconds"),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        duration_seconds=data.get("duration_seconds"),
        exit_code=data.get("exit_code"),
        status=data.get("status", "passed"),
        environment=data.get("environment", {}),
        code_snapshot_hash=data.get("code_snapshot_hash"),
        test_code_hash=data.get("test_code_hash"),
        record_id=data.get("record_id"),
        output_tail=data.get("output_tail", ""),
        output_sha256=data.get("output_sha256"),
        output_bytes=data.get("output_bytes"),
        platform=data.get("platform", ""),
        executable=data.get("executable", ""),
        report_adapter=data.get("report_adapter"),
        report_hash=data.get("report_hash"),
        report_size=data.get("report_size"),
        executed_count=data.get("executed_count"),
        skipped_count=data.get("skipped_count"),
        failed_count=data.get("failed_count"),
        error_count=data.get("error_count"),
        matched_test_entries=data.get("matched_test_entries"),
    )


def _test_task_from_dict(data: dict) -> TestTaskState:
    return TestTaskState(
        test_entries=data.get("test_entries", []),
        command=data.get("command", []),
        cwd=data.get("cwd", ""),
        dependencies=data.get("dependencies", []),
        timeout_seconds=data.get("timeout_seconds", 600),
        report_adapter=data.get("report_adapter"),
        report_path=data.get("report_path"),
        status=data.get("status", "pending"),
        prepared_at=data.get("prepared_at"),
        last_error=data.get("last_error"),
        current_record=_test_execution_record_from_dict(data.get("current_record")),
    )


def _acceptance_record_from_dict(data: dict) -> AcceptanceCriterionRecord:
    return AcceptanceCriterionRecord(
        topic=data.get("topic", ""),
        criterion_id=data.get("criterion_id", ""),
        method=data.get("method", ""),
        result=data.get("result", "passed"),
        actual_result=data.get("actual_result", ""),
        user_answer=data.get("user_answer"),
        evidence=data.get("evidence", ""),
        confirmed_at=data.get("confirmed_at"),
        acceptance_plan_hash=data.get("acceptance_plan_hash"),
        impl_hash=data.get("impl_hash"),
        test_result_hash=data.get("test_result_hash"),
        test_ids=data.get("test_ids", []),
        test_record_ids=data.get("test_record_ids", []),
        record_id=data.get("record_id"),
    )


def _regression_state_from_dict(data: dict) -> RegressionTestState:
    """兼容旧状态：entry/command 由字符串转为参数数组，新机器字段缺省。"""
    entry = data.get("entry")
    if isinstance(entry, str):
        entry = [entry] if entry else []
    command = data.get("command")
    if isinstance(command, str):
        command = [command] if command else []
    return RegressionTestState(
        entry=entry or [],
        command=command or [],
        cwd=data.get("cwd", ""),
        timeout_seconds=data.get("timeout_seconds"),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        duration_seconds=data.get("duration_seconds"),
        status=data.get("status", "not_run"),
        exit_code=data.get("exit_code"),
        code_snapshot_hash=data.get("code_snapshot_hash"),
        record_id=data.get("record_id"),
        output_tail=data.get("output_tail", ""),
        output_sha256=data.get("output_sha256"),
        output_bytes=data.get("output_bytes"),
        platform=data.get("platform", ""),
        executable=data.get("executable", ""),
    )


# 从 dict 反序列化成 WorkflowState dataclass
# 手动重建嵌套的 StageState 和 GateState，因为 dataclass 不自动处理嵌套 dict→dataclass
def state_from_dict(data: dict) -> WorkflowState:
    # 先把 stages dict 里的每个 stage 从裸 dict 重建为 StageState dataclass
    stages = {}
    # 遍历 state.json 里的 stages 字典，逐个重建
    for stage_name, stage_data in data.get("stages", {}).items():
        # 从 stage_data 重建 GateState（3 道闸）
        gate_data = stage_data.get("gate", {})
        gate = GateState(
            discussion_complete=gate_data.get("discussion_complete", False),
            code_validated=gate_data.get("code_validated", False),
            user_confirmed=gate_data.get("user_confirmed", False),
        )
        # 从 stage_data 重建 StageState
        stages[stage_name] = StageState(
            status=stage_data.get("status", "pending"),
            artifact_paths=stage_data.get("artifact_paths", []),
            artifact_produced_at=stage_data.get("artifact_produced_at"),
            artifact_baseline_captured_at=stage_data.get("artifact_baseline_captured_at"),
            artifact_baseline_hashes=stage_data.get("artifact_baseline_hashes", {}),
            code_baseline_hash=stage_data.get("code_baseline_hash"),
            test_code_baseline_hash=stage_data.get("test_code_baseline_hash"),
            non_test_code_baseline_hash=stage_data.get("non_test_code_baseline_hash"),
            existing_code_accepted_hash=stage_data.get("existing_code_accepted_hash"),
            existing_test_code_accepted_hash=stage_data.get("existing_test_code_accepted_hash"),
            discussion_material_hash=stage_data.get("discussion_material_hash"),
            plan_confirmed_hash=stage_data.get("plan_confirmed_hash"),
            test_tasks={
                topic: {
                    test_id: _test_task_from_dict(task_data)
                    for test_id, task_data in topic_tasks.items()
                }
                for topic, topic_tasks in stage_data.get("test_tasks", {}).items()
            },
            acceptance_records={
                topic: {
                    criterion_id: _acceptance_record_from_dict(record_data)
                    for criterion_id, record_data in topic_records.items()
                }
                for topic, topic_records in stage_data.get("acceptance_records", {}).items()
            },
            gate=gate,
        )
    # 读 architecture 字段（架构门禁标记）
    arch_data = data.get("architecture", {})
    # 读 verification 字段（验证绑定哈希）
    verification_data = data.get("verification", {})
    # 旧状态中的修改前全量测试基线（test_baseline）已经删除业务用途：
    # 读取时直接忽略，不再写回，本轮旧过渡执行记录不能影响实施。
    # 读 regression_test 字段；旧 state.json 没有时按未执行处理
    regression_test_data = data.get("regression_test", {})
    # 读 spike_baseline 字段；旧 state.json 没有时按未记录处理
    spike_baseline_data = data.get("spike_baseline", {})
    # 读 rollback 字段；旧 state.json 没有时表示尚未准备代码回退基线
    rollback_data = data.get("rollback", {})
    # 读 recovery 字段；旧 state.json 没有时表示当前不是失效恢复流程
    recovery_data = data.get("recovery", {})
    # 读无需开发任务状态；旧状态和三种完整研发意图中为空
    light_task_data = data.get("light_task")
    # 兼容旧版单主题 state.json：没有 topics 时把 topic 转成单元素列表。
    legacy_topic = data.get("topic")
    topics = data.get("topics", [])
    if not topics and legacy_topic:
        topics = [legacy_topic]

    # 重建最外层的 WorkflowState
    return WorkflowState(
        workflow_id=data["workflow_id"],
        intent=data["intent"],
        run_status=data.get("run_status", "active"),
        current_stage=data.get("current_stage", ""),
        started_at=data.get("started_at", ""),
        ended_at=data.get("ended_at"),
        aborted_at=data.get("aborted_at"),
        topic=legacy_topic,
        topics=topics,
        clean_confirmed=data.get("clean_confirmed", False),
        spike_skipped=data.get("spike_skipped", False),
        stage_path=data.get("stage_path", []),
        stages=stages,
        architecture=ArchitectureState(
            preliminary_done=arch_data.get("preliminary_done", False),
            detailed_done=arch_data.get("detailed_done", False),
        ),
        verification=VerificationState(
            impl_hash=verification_data.get("impl_hash"),
            test_plan_hash=verification_data.get("test_plan_hash"),
            acceptance_plan_hash=verification_data.get("acceptance_plan_hash"),
            test_code_hash=verification_data.get("test_code_hash"),
            test_result_hash=verification_data.get("test_result_hash"),
            acceptance_result_hash=verification_data.get("acceptance_result_hash"),
            regression_test_result_hash=verification_data.get("regression_test_result_hash"),
        ),
        regression_test=_regression_state_from_dict(regression_test_data),
        spike_baseline=SpikeBaselineState(
            captured_at=spike_baseline_data.get("captured_at"),
            product_design_hash=spike_baseline_data.get("product_design_hash"),
            product_design_paths=spike_baseline_data.get("product_design_paths", []),
            code_design_hash=spike_baseline_data.get("code_design_hash"),
            legacy_unavailable=spike_baseline_data.get("legacy_unavailable", False),
        ),
        rollback=RollbackState(
            manifest_path=rollback_data.get("manifest_path"),
            manifest_hash=rollback_data.get("manifest_hash"),
            prepared_at=rollback_data.get("prepared_at"),
            plan_hash=rollback_data.get("plan_hash"),
            code_baseline_hash=rollback_data.get("code_baseline_hash"),
            planned_paths=rollback_data.get("planned_paths", []),
            restore_started_at=rollback_data.get("restore_started_at"),
            restored_at=rollback_data.get("restored_at"),
            cleanup_completed_at=rollback_data.get("cleanup_completed_at"),
        ),
        recovery=RecoveryContext(
            source_stage=recovery_data.get("source_stage"),
            return_target=recovery_data.get("return_target"),
            reason=recovery_data.get("reason"),
            affected_stages=recovery_data.get("affected_stages", []),
            affected_topics=recovery_data.get("affected_topics", []),
            created_at=recovery_data.get("created_at"),
        ),
        light_task=(
            LightTaskState(
                phase=light_task_data.get("phase", "discussion"),
                task_summary=light_task_data.get("task_summary", ""),
                verification_method=light_task_data.get("verification_method", ""),
                last_approved_action=light_task_data.get("last_approved_action", ""),
                result_summary=light_task_data.get("result_summary", ""),
            )
            if isinstance(light_task_data, dict)
            else None
        ),
        meta=data.get("meta", {}),
    )


# 从被管理项目的 .workflow_loop/state.json 读取 state
# 如果文件不存在（还没 start 过），返回 None 让调用方处理
# project_root 是被管理项目的根目录路径
def load_state(project_root: str) -> WorkflowState | None:
    # 拼出 state.json 的完整路径（项目根 + .workflow_loop/state.json）
    path = os.path.join(project_root, STATE_FILE)
    # 文件不存在说明还没 start，返回 None
    if not os.path.exists(path):
        return None
    # 读文件、解析 JSON
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 反序列化成 WorkflowState
    return state_from_dict(data)


# 把 WorkflowState 写到被管理项目的 .workflow_loop/state.json
# ensure_ascii=False 让中文不被转义成 \uXXXX；indent=2 让文件可读
def save_state(project_root: str, state: WorkflowState) -> None:
    # 拼出 state.json 的完整路径
    path = os.path.join(project_root, STATE_FILE)
    # 确保目录存在（第一次写时 .workflow_loop/ 可能还没建）
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 序列化 dataclass → dict
    data = state_to_dict(state)
    # 临时文件必须和 state.json 在同一目录，os.replace 才能原子替换。
    fd, temp_path = tempfile.mkstemp(
        prefix=".state.",
        suffix=".tmp",
        dir=os.path.dirname(path),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


# 判断当前项目是否有进行中的 Run（Active Run Guard 用）
# state.json 存在且 run_status=active → True（禁止再 start）
# state.json 不存在 / completed / aborted → False（允许新 start）
def is_active_run(project_root: str) -> bool:
    # 读 state
    state = load_state(project_root)
    # state 存在且 run_status 是 active 才返回 True
    return state is not None and state.run_status == "active"
