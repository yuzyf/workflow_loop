import json
import sys
from pathlib import Path

from workflow_loop.artifact_validation import validate_test_execution_results
from workflow_loop.project import create_project
from workflow_loop.state import StageState, WorkflowState, load_state, save_state
from workflow_loop.test_execution import (
    prepare_task,
    run_prepared_tasks,
    validate_command,
    validate_command_entries,
    validate_prepared_tasks,
)
from workflow_loop.verification import compute_code_snapshot_hash, compute_test_code_snapshot_hash


WORKFLOW_ID = "2026-07-28-1300-test-execution"
TOPIC = "上传文件"


def _pytest_command(entry: str) -> list[str]:
    return [sys.executable, "-m", "pytest", entry, "-q"]


def _write_test_documents(tmp_path, *, command_label="通过"):
    (tmp_path / "qa").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "upload.py").write_text(
        "from pathlib import Path\n\n"
        "def upload_file(target, content):\n"
        "    Path(target).write_text(content, encoding='utf-8')\n",
        encoding="utf-8",
    )
    (tmp_path / "qa" / f"{TOPIC}_测试计划.md").write_text(
        f"""# {TOPIC}测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 产品入口 | 代码入口 | 测试入口 | 准备数据 | 执行动作 | 观察位置 | 预期结果 | 不通过表现 | 证据要求 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [AC-01：上传完成](../acceptance/{TOPIC}_验收计划.md#ac-01) | <a id=\"tc-01\"></a>[TC-01 验证上传完成](#tc-01) | 无 | 自动化测试 | 上传命令 | `src/upload.py::upload_file` | `tests/test_upload.py::test_upload` | 创建隔离临时目录 | 调用上传入口写入文件 | 临时目录中的目标文件 | 目标文件存在且内容正确 | 文件缺失或内容错误 | 结构化报告和目标文件内容 |

## 2. 针对性回归范围

暂无

## 3. 测试条件要求

暂无

## 4. 未决测试条件

暂无

## 5. 上下游文档

- 上游验收计划：[验收计划](../acceptance/{TOPIC}_验收计划.md)
""",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_upload.py").write_text(
        """from src.upload import upload_file


def test_upload(tmp_path):
    \"\"\"Workflow-Test
    主题：上传文件
    测试项：TC-01 验证上传完成
    验收条件：AC-01 上传完成
    测试方式：自动化测试
    测试层级：命令测试
    产品入口：上传命令
    测试入口：`tests/test_upload.py::test_upload`
    代码入口：`src/upload.py::upload_file`
    准备数据：创建隔离临时目录
    执行动作：调用上传入口写入文件
    关键断言：目标文件存在且内容正确
    预期证据：结构化报告和目标文件内容
    \"\"\"
    target = tmp_path / "uploaded.txt"
    upload_file(target, "saved")
    assert target.read_text(encoding="utf-8") == "saved"
""",
        encoding="utf-8",
    )
    (tmp_path / "qa" / "索引.md").write_text(
        f"""# 测试计划索引

## {WORKFLOW_ID}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 实施记录 | 测试计划 | 测试结果 |
|---|---|---|---|---|---|---|
| 1 | {TOPIC} | 无 | [{TOPIC}验收计划](../acceptance/{TOPIC}_验收计划.md) | [{TOPIC}实施记录](../impl/{TOPIC}_实施记录.md) | [{TOPIC}测试计划](./{TOPIC}_测试计划.md) | `./{TOPIC}_测试结果.md`（待生成） |
""",
        encoding="utf-8",
    )


def _state(tmp_path):
    create_project(str(tmp_path))
    state = WorkflowState(
        workflow_id=WORKFLOW_ID,
        intent="from_scratch",
        current_stage="test_execution",
        topics=[TOPIC],
        stages={"test_execution": StageState(status="in_progress")},
    )
    state.verification.test_code_hash = compute_test_code_snapshot_hash(str(tmp_path))
    save_state(str(tmp_path), state)
    return state


def test_qa_template_uses_the_same_seven_column_contract_as_execution():
    """模板副本必须同步，并使用执行器实际读取的七列索引格式。"""
    repository_root = Path(__file__).parents[1]
    packaged_path = (
        repository_root
        / "src"
        / "workflow_loop"
        / "data"
        / "Template_Repository"
        / "qa"
        / "test_plan.md"
    )
    active_path = repository_root / ".workflow_loop" / "Template_Repository" / "qa" / "test_plan.md"
    packaged = packaged_path.read_text(encoding="utf-8")

    assert active_path.read_text(encoding="utf-8") == packaged
    assert (
        "| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 实施记录 | 测试计划 | 测试结果 |"
        in packaged
    )
    assert "../impl/<主题 A 文件标识>_实施记录.md" in packaged
    assert "`./<主题文件标识>_测试结果.md`（待生成）" in packaged
    assert "`./<主题 A 文件标识>_测试结果.md`（待生成）" in packaged
    assert "`qa/<主题文件标识>_测试结果.md`（待生成）" not in packaged
    assert "`qa/<主题 A 文件标识>_测试结果.md`（待生成）" not in packaged


def test_prepare_registers_real_argv_and_plan_dependencies(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-04 正式任务按测试项独立登记
    验收条件：AC-04 正式执行范围可以审查
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：测试项按参数数组、入口、依赖和超时独立登记
    测试入口：tests/test_test_execution.py::test_prepare_registers_real_argv_and_plan_dependencies
    代码入口：workflow_loop.test_execution.prepare_task
    """
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    command = _pytest_command("tests/test_upload.py::test_upload")

    task = prepare_task(
        str(tmp_path),
        state,
        TOPIC,
        "TC-01",
        command,
        timeout_seconds=12,
        report_adapter="pytest-junitxml",
    )

    assert task.command[: len(command)] == command
    assert task.command[-3:-1] == ["-p", "workflow_loop.test_report"]
    assert task.command[-1].startswith("--junitxml=")
    assert task.report_adapter == "pytest-junitxml"
    assert task.report_path == f".workflow_loop/test_reports/{WORKFLOW_ID}/{TOPIC}/TC-01.xml"
    assert task.test_entries == ["tests/test_upload.py::test_upload"]
    assert task.dependencies == []
    assert task.timeout_seconds == 12
    assert task.status == "pending"


def test_run_success_writes_current_record_but_not_formal_result(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-06 测试结果严格匹配当前机器记录
    验收条件：AC-06 正式测试结果与机器记录一致
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：真实运行只产生机器事实而不由程序伪造正式结论文档
    测试入口：tests/test_test_execution.py::test_run_success_writes_current_record_but_not_formal_result
    代码入口：workflow_loop.test_execution.run_prepared_tasks
    """
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    command = _pytest_command("tests/test_upload.py::test_upload")
    prepare_task(
        str(tmp_path), state, TOPIC, "TC-01", command,
        report_adapter="pytest-junitxml",
    )

    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=1)
    loaded = load_state(str(tmp_path))
    task = loaded.stages["test_execution"].test_tasks[TOPIC]["TC-01"]

    assert attempts[0].status == "passed"
    assert task.status == "passed"
    assert task.current_record is not None
    assert task.current_record.exit_code == 0
    assert task.current_record.command[: len(command)] == command
    assert not (tmp_path / "qa" / f"{TOPIC}_测试结果.md").exists()


def test_rerun_keeps_current_success_without_executing_it_twice(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-04 正式任务按测试项独立登记
    验收条件：AC-04 正式执行范围可以审查
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：已通过且未变化的登记任务不会被同一次阶段重复执行
    测试入口：tests/test_test_execution.py::test_rerun_keeps_current_success_without_executing_it_twice
    代码入口：workflow_loop.test_execution.run_prepared_tasks
    """
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    command = _pytest_command("tests/test_upload.py::test_upload")
    prepare_task(
        str(tmp_path), state, TOPIC, "TC-01", command,
        report_adapter="pytest-junitxml",
    )
    assert len(run_prepared_tasks(str(tmp_path), state, parallelism=1)) == 1

    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=1)

    assert attempts == []


def test_failed_rerun_clears_previous_current_success_and_result(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-06 测试结果严格匹配当前机器记录
    验收条件：AC-06 正式测试结果与机器记录一致
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：重新执行失败后旧通过记录和旧正式结果立即失效
    测试入口：tests/test_test_execution.py::test_failed_rerun_clears_previous_current_success_and_result
    代码入口：workflow_loop.test_execution.run_prepared_tasks
    """
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    success_command = _pytest_command("tests/test_upload.py::test_upload")
    prepare_task(
        str(tmp_path), state, TOPIC, "TC-01", success_command,
        report_adapter="pytest-junitxml",
    )
    assert run_prepared_tasks(str(tmp_path), state, parallelism=1)[0].status == "passed"
    (tmp_path / "qa" / f"{TOPIC}_测试结果.md").write_text("旧的通过结果", encoding="utf-8")
    index_path = tmp_path / "qa" / "索引.md"
    index_path.write_text(
        index_path.read_text(encoding="utf-8").replace(
            f"`./{TOPIC}_测试结果.md`（待生成）",
            f"[{TOPIC}测试结果](./{TOPIC}_测试结果.md)",
        ),
        encoding="utf-8",
    )

    test_path = tmp_path / "tests" / "test_upload.py"
    test_path.write_text(
        test_path.read_text(encoding="utf-8").replace(
            'assert target.read_text(encoding="utf-8") == "saved"',
            'assert target.read_text(encoding="utf-8") == "definitely-wrong"',
        ),
        encoding="utf-8",
    )
    failure_command = _pytest_command("tests/test_upload.py::test_upload")
    prepare_task(
        str(tmp_path), state, TOPIC, "TC-01", failure_command,
        report_adapter="pytest-junitxml",
    )
    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=1)
    loaded = load_state(str(tmp_path))
    task = loaded.stages["test_execution"].test_tasks[TOPIC]["TC-01"]

    assert attempts[0].status == "failed"
    assert task.status == "needs_action"
    assert task.current_record is None
    assert not (tmp_path / "qa" / f"{TOPIC}_测试结果.md").exists()


def test_test_command_rejects_shell_operators():
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-04 正式任务按测试项独立登记
    验收条件：AC-04 正式执行范围可以审查
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：拒绝把多条命令串成无法逐项审查的测试任务
    测试入口：tests/test_test_execution.py::test_test_command_rejects_shell_operators
    代码入口：workflow_loop.test_execution.validate_command
    """
    assert validate_command(["pytest", "tests/test_upload.py"]) == (True, "")
    ok, detail = validate_command(["pytest", "tests", "&&", "echo", "bad"])
    assert ok is False
    assert "命令串联" in detail


def test_test_command_must_select_the_registered_test_entry():
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-04 正式任务按测试项独立登记
    验收条件：AC-04 正式执行范围可以审查
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：实际命令必须精确选择登记入口且不能用临时代码冒充测试
    测试入口：tests/test_test_execution.py::test_test_command_must_select_the_registered_test_entry
    代码入口：workflow_loop.test_execution.validate_command_entries
    """
    entry = "tests/test_upload.py::test_upload"
    ok, detail = validate_command_entries(
        [sys.executable, "-c", "raise SystemExit(0)"],
        [entry],
    )
    assert ok is False
    assert "临时代码" in detail

    ok, detail = validate_command_entries(
        [sys.executable, "-m", "pytest", "tests/test_other.py", "-q"],
        [entry],
    )
    assert ok is False
    assert entry in detail

    ok, detail = validate_command_entries(_pytest_command("tests"), [entry])
    assert ok is False
    assert entry in detail

    assert validate_command_entries(
        _pytest_command("tests/test_upload.py"),
        [entry],
    ) == (True, "")
    assert validate_command_entries(_pytest_command(entry), [entry]) == (True, "")


def test_prepared_task_validation_reports_all_independent_task_errors(tmp_path):
    """Workflow-Test
    主题：门禁失败一次展示完整可处理原因且快照范围准确
    测试项：TC-03 执行前登记一次展示全部独立错误
    验收条件：AC-03 登记问题一次完整展示
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：同一任务的命令、超时、目录、依赖和入口错误在一次校验中全部定位
    测试入口：tests/test_test_execution.py::test_prepared_task_validation_reports_all_independent_task_errors
    代码入口：workflow_loop.test_execution.validate_prepared_tasks
    """
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    task = prepare_task(
        str(tmp_path),
        state,
        TOPIC,
        "TC-01",
        _pytest_command("tests/test_upload.py::test_upload"),
        report_adapter="pytest-junitxml",
    )
    task.command = ["pytest", "tests/test_other.py", "&&", "echo", "bad"]
    task.timeout_seconds = 0
    task.cwd = "not-a-directory"
    task.dependencies = ["TC-99"]
    task.test_entries = ["tests/test_other.py::test_other"]

    ok, detail = validate_prepared_tasks(str(tmp_path), state)

    assert ok is False
    assert "测试任务登记校验失败（共 " in detail
    assert "主题：上传文件；测试项：TC-01；字段：执行命令" in detail
    assert "主题：上传文件；测试项：TC-01；字段：超时时间" in detail
    assert "主题：上传文件；测试项：TC-01；字段：工作目录" in detail
    assert "主题：上传文件；测试项：TC-01；字段：前置测试项" in detail
    assert "主题：上传文件；测试项：TC-01；字段：测试入口" in detail


def test_prepared_task_validation_marks_tasks_unchecked_when_plan_cannot_parse(tmp_path):
    """Workflow-Test
    主题：门禁失败一次展示完整可处理原因且快照范围准确
    测试项：TC-03 执行前登记一次展示全部独立错误
    验收条件：AC-03 登记问题一次完整展示
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：测试计划无法解析时明确说明登记任务未检查的原因
    测试入口：tests/test_test_execution.py::test_prepared_task_validation_marks_tasks_unchecked_when_plan_cannot_parse
    代码入口：workflow_loop.test_execution.validate_prepared_tasks
    """
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    prepare_task(
        str(tmp_path),
        state,
        TOPIC,
        "TC-01",
        _pytest_command("tests/test_upload.py::test_upload"),
        report_adapter="pytest-junitxml",
    )
    plan_path = tmp_path / "qa" / f"{TOPIC}_测试计划.md"
    plan_path.write_text("# 损坏的测试计划\n", encoding="utf-8")

    ok, detail = validate_prepared_tasks(str(tmp_path), state)

    assert ok is False
    assert "主题：上传文件；测试项：未检查；字段：测试计划；问题：无法解析" in detail
    assert "主题：上传文件；测试项：TC-01；字段：登记任务；问题：未检查" in detail


def test_prepared_task_validation_reports_missing_registration_without_crashing(tmp_path):
    """Workflow-Test
    主题：门禁失败一次展示完整可处理原因且快照范围准确
    测试项：TC-03 执行前登记一次展示全部独立错误
    验收条件：AC-03 登记问题一次完整展示
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：漏登记任务只报告缺失，不读取不存在任务的字段
    测试入口：tests/test_test_execution.py::test_prepared_task_validation_reports_missing_registration_without_crashing
    代码入口：workflow_loop.test_execution.validate_prepared_tasks
    """
    _write_test_documents(tmp_path)
    state = _state(tmp_path)

    ok, detail = validate_prepared_tasks(str(tmp_path), state)

    assert ok is False
    assert "主题：上传文件；测试项：TC-01；字段：登记任务；问题：尚未登记测试命令" in detail


def test_result_gate_matches_current_execution_record_and_command(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-06 测试结果严格匹配当前机器记录
    验收条件：AC-06 正式测试结果与机器记录一致
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：正式结果逐字段匹配当前机器事实且篡改退出码会被门禁拒绝
    测试入口：tests/test_test_execution.py::test_result_gate_matches_current_execution_record_and_command
    代码入口：workflow_loop.artifact_validation.validate_test_execution_results
    """
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    command = _pytest_command("tests/test_upload.py::test_upload")
    prepare_task(
        str(tmp_path), state, TOPIC, "TC-01", command,
        report_adapter="pytest-junitxml",
    )
    assert run_prepared_tasks(str(tmp_path), state, parallelism=1)[0].status == "passed"
    loaded = load_state(str(tmp_path))
    record = loaded.stages["test_execution"].test_tasks[TOPIC]["TC-01"].current_record
    assert record is not None
    entry_text = json.dumps(record.test_entries, ensure_ascii=False, separators=(",", ":"))
    command_text = json.dumps(record.command, ensure_ascii=False, separators=(",", ":"))
    output_tail = json.dumps(record.output_tail, ensure_ascii=False)
    environment = f"平台={record.platform}；可执行文件={record.executable}"
    (tmp_path / "qa" / f"{TOPIC}_测试结果.md").write_text(
        f"""# 【主题测试结果】{TOPIC}

- 工作流编号：{WORKFLOW_ID}
- 验收主题：{TOPIC}
- 自动化测试结果：通过
- 人工验收状态：无需人工验收

## 3. 测试项结果

### TC-01：验证上传完成

- 对应验收条件：AC-01 上传完成
- 机器记录编号：{record.record_id}
- 工作目录：项目根
- 测试入口：{entry_text}
- 执行命令：{command_text}
- 超时（秒）：{record.timeout_seconds}
- 运行环境：{environment}
- 开始时间：{record.started_at}
- 结束时间：{record.finished_at}
- 时长（秒）：{record.duration_seconds}
- 退出码：{record.exit_code}
- 输出摘要：{output_tail}
- 输出哈希：{record.output_sha256}
- 输出字节数：{record.output_bytes}
- 报告适配器：{record.report_adapter}
- 报告哈希：{record.report_hash}
- 报告字节数：{record.report_size}
- 精确匹配测试入口：{json.dumps(record.matched_test_entries, ensure_ascii=False, separators=(",", ":"))}
- 实际执行数：{record.executed_count}
- 跳过数：{record.skipped_count}
- 失败数：{record.failed_count}
- 错误数：{record.error_count}
- 产品代码哈希：{record.code_snapshot_hash}
- 测试代码哈希：{record.test_code_hash}
- 实际结果：命令退出码为 0，测试入口完成执行
- 自动化测试结果：通过
- 证据：机器记录 {record.record_id}
""",
        encoding="utf-8",
    )

    ok, detail = validate_test_execution_results(str(tmp_path), WORKFLOW_ID, [TOPIC])

    assert ok is True, detail

    result_path = tmp_path / "qa" / f"{TOPIC}_测试结果.md"
    result_path.write_text(
        result_path.read_text(encoding="utf-8")
        .replace("退出码：0", "退出码：1")
        .replace(f"报告哈希：{record.report_hash}", "报告哈希：错误哈希")
        .replace("- 实际结果：命令退出码为 0，测试入口完成执行\n", ""),
        encoding="utf-8",
    )
    ok, detail = validate_test_execution_results(str(tmp_path), WORKFLOW_ID, [TOPIC])
    assert ok is False
    assert "退出码" in detail
    assert "报告哈希" in detail
    assert "缺少实际结果" in detail
    assert detail.startswith("1. ")


def _write_dependency_topic(
    tmp_path: Path,
    topic: str,
    entry_name: str,
    *,
    body: str | None = None,
) -> None:
    (tmp_path / "qa").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / f"{entry_name}.py").write_text(
        "def run():\n    return True\n",
        encoding="utf-8",
    )
    if body is None:
        body = (
            f"    from src.{entry_name} import run\n"
            "    assert run() is True"
        )
    (tmp_path / "qa" / f"{topic}_测试计划.md").write_text(
        f"""# {topic}测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 产品入口 | 代码入口 | 测试入口 | 准备数据 | 执行动作 | 观察位置 | 预期结果 | 不通过表现 | 证据要求 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [AC-01：{topic}完成](../acceptance/{topic}_验收计划.md#ac-01) | <a id=\"tc-01\"></a>[TC-01 验证{topic}完成](#tc-01) | 无 | 自动化测试 | {topic}命令 | `src/{entry_name}.py::run` | `tests/test_{entry_name}.py::test_{entry_name}` | 创建隔离测试数据 | 调用{topic}真实入口 | 命令退出状态和业务结果 | {topic}完成 | 命令失败或业务结果不正确 | 结构化报告和业务结果 |
""",
        encoding="utf-8",
    )
    (tmp_path / "tests" / f"test_{entry_name}.py").write_text(
        f'''def test_{entry_name}():
    """Workflow-Test
    主题：{topic}
    测试项：TC-01 验证{topic}完成
    验收条件：AC-01 {topic}完成
    测试方式：自动化测试
    测试层级：命令测试
    产品入口：{topic}命令
    测试入口：`tests/test_{entry_name}.py::test_{entry_name}`
    代码入口：`src/{entry_name}.py::run`
    准备数据：创建隔离测试数据
    执行动作：调用{topic}真实入口
    关键断言：{topic}完成
    预期证据：结构化报告和业务结果
    """
{body}
''',
        encoding="utf-8",
    )


def _dependency_state(tmp_path: Path, topics: list[str]) -> WorkflowState:
    create_project(str(tmp_path))
    state = WorkflowState(
        workflow_id=WORKFLOW_ID,
        intent="from_scratch",
        current_stage="test_execution",
        topics=topics,
        stages={"test_execution": StageState(status="in_progress")},
    )
    state.verification.test_code_hash = compute_test_code_snapshot_hash(str(tmp_path))
    save_state(str(tmp_path), state)
    return state


def test_topic_dependencies_run_predecessor_before_dependent_topic(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-04 正式任务按测试项独立登记
    验收条件：AC-04 正式执行范围可以审查
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：并行执行时仍按主题前置关系先运行前置主题
    测试入口：tests/test_test_execution.py::test_topic_dependencies_run_predecessor_before_dependent_topic
    代码入口：workflow_loop.test_execution.run_prepared_tasks
    """
    first = "准备上传环境"
    second = "上传文件"
    _write_dependency_topic(
        tmp_path,
        first,
        "prepare_upload",
        body='''    from pathlib import Path
    import time
    time.sleep(0.15)
    with Path("order.txt").open("a", encoding="utf-8") as stream:
        stream.write("准备上传环境\\n")''',
    )
    _write_dependency_topic(
        tmp_path,
        second,
        "upload_file",
        body='''    from pathlib import Path
    with Path("order.txt").open("a", encoding="utf-8") as stream:
        stream.write("上传文件\\n")''',
    )
    (tmp_path / "qa" / "索引.md").write_text(
        f"""# 测试计划索引

## {WORKFLOW_ID}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 实施记录 | 测试计划 | 测试结果 |
|---|---|---|---|---|---|---|
| 1 | {first} | 无 | [验收计划](../acceptance/{first}_验收计划.md) | [实施记录](../impl/{first}_实施记录.md) | [测试计划](./{first}_测试计划.md) | `./{first}_测试结果.md`（待生成） |
| 2 | {second} | {first} | [验收计划](../acceptance/{second}_验收计划.md) | [实施记录](../impl/{second}_实施记录.md) | [测试计划](./{second}_测试计划.md) | `./{second}_测试结果.md`（待生成） |
""",
        encoding="utf-8",
    )
    order_path = tmp_path / "order.txt"
    state = _dependency_state(tmp_path, [first, second])
    prepare_task(
        str(tmp_path),
        state,
        first,
        "TC-01",
        _pytest_command("tests/test_prepare_upload.py::test_prepare_upload"),
        report_adapter="pytest-junitxml",
    )
    prepare_task(
        str(tmp_path),
        state,
        second,
        "TC-01",
        _pytest_command("tests/test_upload_file.py::test_upload_file"),
        report_adapter="pytest-junitxml",
    )

    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=2)

    assert [attempt.status for attempt in attempts] == ["passed", "passed"]
    assert order_path.read_text(encoding="utf-8").splitlines() == [first, second]


def test_failed_predecessor_topic_blocks_dependent_topic(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-04 正式任务按测试项独立登记
    验收条件：AC-04 正式执行范围可以审查
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：前置主题失败时依赖主题不执行并明确记录阻塞
    测试入口：tests/test_test_execution.py::test_failed_predecessor_topic_blocks_dependent_topic
    代码入口：workflow_loop.test_execution.run_prepared_tasks
    """
    first = "准备上传环境"
    second = "上传文件"
    third = "确认上传结果"
    independent = "记录审计信息"
    _write_dependency_topic(tmp_path, first, "prepare_upload", body="    assert False")
    _write_dependency_topic(tmp_path, second, "upload_file")
    _write_dependency_topic(tmp_path, third, "confirm_upload")
    _write_dependency_topic(tmp_path, independent, "record_audit")
    (tmp_path / "qa" / "索引.md").write_text(
        f"""# 测试计划索引

## {WORKFLOW_ID}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 实施记录 | 测试计划 | 测试结果 |
|---|---|---|---|---|---|---|
| 1 | {first} | 无 | [验收计划](../acceptance/{first}_验收计划.md) | [实施记录](../impl/{first}_实施记录.md) | [测试计划](./{first}_测试计划.md) | `./{first}_测试结果.md`（待生成） |
| 2 | {second} | {first} | [验收计划](../acceptance/{second}_验收计划.md) | [实施记录](../impl/{second}_实施记录.md) | [测试计划](./{second}_测试计划.md) | `./{second}_测试结果.md`（待生成） |
| 3 | {third} | {second} | [验收计划](../acceptance/{third}_验收计划.md) | [实施记录](../impl/{third}_实施记录.md) | [测试计划](./{third}_测试计划.md) | `./{third}_测试结果.md`（待生成） |
| 4 | {independent} | 无 | [验收计划](../acceptance/{independent}_验收计划.md) | [实施记录](../impl/{independent}_实施记录.md) | [测试计划](./{independent}_测试计划.md) | `./{independent}_测试结果.md`（待生成） |
""",
        encoding="utf-8",
    )
    state = _dependency_state(tmp_path, [first, second, third, independent])
    prepare_task(
        str(tmp_path),
        state,
        first,
        "TC-01",
        _pytest_command("tests/test_prepare_upload.py::test_prepare_upload"),
        report_adapter="pytest-junitxml",
    )
    prepare_task(
        str(tmp_path),
        state,
        second,
        "TC-01",
        _pytest_command("tests/test_upload_file.py::test_upload_file"),
        report_adapter="pytest-junitxml",
    )
    prepare_task(
        str(tmp_path),
        state,
        third,
        "TC-01",
        _pytest_command("tests/test_confirm_upload.py::test_confirm_upload"),
        report_adapter="pytest-junitxml",
    )
    prepare_task(
        str(tmp_path),
        state,
        independent,
        "TC-01",
        _pytest_command("tests/test_record_audit.py::test_record_audit"),
        report_adapter="pytest-junitxml",
    )

    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=2)
    statuses = {(attempt.topic, attempt.test_id): attempt.status for attempt in attempts}
    persisted = load_state(str(tmp_path))
    persisted_tasks = persisted.stages["test_execution"].test_tasks

    assert statuses[(first, "TC-01")] == "failed"
    assert statuses[(second, "TC-01")] == "blocked"
    assert statuses[(third, "TC-01")] == "blocked"
    assert statuses[(independent, "TC-01")] == "passed"
    assert persisted_tasks[first]["TC-01"].status == "needs_action"
    assert persisted_tasks[second]["TC-01"].status == "blocked"
    assert persisted_tasks[third]["TC-01"].status == "blocked"
    assert persisted_tasks[independent]["TC-01"].status == "passed"
