import shlex
import sys
from pathlib import Path

from workflow_loop.artifact_validation import validate_test_execution_results
from workflow_loop.project import create_project
from workflow_loop.state import StageState, WorkflowState, load_state, save_state
from workflow_loop.test_execution import (
    prepare_task,
    run_prepared_tasks,
    validate_command,
)
from workflow_loop.verification import compute_code_snapshot_hash, compute_test_code_snapshot_hash


WORKFLOW_ID = "2026-07-28-1300-test-execution"
TOPIC = "上传文件"


def _write_test_documents(tmp_path, *, command_label="通过"):
    (tmp_path / "qa").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "qa" / f"{TOPIC}_plan.md").write_text(
        f"""# {TOPIC}测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：上传完成](../acceptance/{TOPIC}_plan.md#ac-01) | <a id=\"tc-01\"></a>[TC-01 验证上传完成](#tc-01) | 无 | 自动化测试 | 检查上传结果 | 文件被保存 | 保留执行证据 |

## 2. 针对性回归范围

暂无

## 3. 测试条件要求

暂无

## 4. 未决测试条件

暂无

## 5. 上下游文档

- 上游验收计划：[验收计划](../acceptance/{TOPIC}_plan.md)
""",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_upload.py").write_text(
        """def test_upload():
    \"\"\"Workflow-Test
    主题：上传文件
    测试项：TC-01 验证上传完成
    验收条件：AC-01 上传完成
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：运行上传命令后检查文件已经保存
    测试入口：tests/test_upload.py::test_upload
    代码入口：src/upload.py 的 upload_file()
    \"\"\"
    assert True
""",
        encoding="utf-8",
    )
    (tmp_path / "qa" / "index.md").write_text(
        f"""# 测试计划索引

## {WORKFLOW_ID}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 测试结果 |
|---|---|---|---|---|---|
| 1 | {TOPIC} | 无 | [{TOPIC}验收计划](../acceptance/{TOPIC}_plan.md) | [{TOPIC}测试计划](./{TOPIC}_plan.md) | [{TOPIC}测试结果](./{TOPIC}_result.md) |
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


def test_prepare_registers_real_argv_and_plan_dependencies(tmp_path):
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    command = [sys.executable, "-c", "raise SystemExit(0)"]

    task = prepare_task(str(tmp_path), state, TOPIC, "TC-01", command, timeout_seconds=12)

    assert task.command == command
    assert task.test_entries == ["tests/test_upload.py::test_upload"]
    assert task.dependencies == []
    assert task.timeout_seconds == 12
    assert task.status == "pending"


def test_run_success_writes_current_record_but_not_formal_result(tmp_path):
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    command = [sys.executable, "-c", "raise SystemExit(0)"]
    prepare_task(str(tmp_path), state, TOPIC, "TC-01", command)

    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=1)
    loaded = load_state(str(tmp_path))
    task = loaded.stages["test_execution"].test_tasks[TOPIC]["TC-01"]

    assert attempts[0].status == "passed"
    assert task.status == "passed"
    assert task.current_record is not None
    assert task.current_record.exit_code == 0
    assert task.current_record.command == command
    assert not (tmp_path / "qa" / f"{TOPIC}_result.md").exists()


def test_rerun_keeps_current_success_without_executing_it_twice(tmp_path):
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    command = [sys.executable, "-c", "raise SystemExit(0)"]
    prepare_task(str(tmp_path), state, TOPIC, "TC-01", command)
    assert len(run_prepared_tasks(str(tmp_path), state, parallelism=1)) == 1

    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=1)

    assert attempts == []


def test_failed_rerun_clears_previous_current_success_and_result(tmp_path):
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    success_command = [sys.executable, "-c", "raise SystemExit(0)"]
    prepare_task(str(tmp_path), state, TOPIC, "TC-01", success_command)
    assert run_prepared_tasks(str(tmp_path), state, parallelism=1)[0].status == "passed"
    (tmp_path / "qa" / f"{TOPIC}_result.md").write_text("旧的通过结果", encoding="utf-8")

    failure_command = [sys.executable, "-c", "raise SystemExit(1)"]
    prepare_task(str(tmp_path), state, TOPIC, "TC-01", failure_command)
    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=1)
    loaded = load_state(str(tmp_path))
    task = loaded.stages["test_execution"].test_tasks[TOPIC]["TC-01"]

    assert attempts[0].status == "failed"
    assert task.status == "needs_action"
    assert task.current_record is None
    assert not (tmp_path / "qa" / f"{TOPIC}_result.md").exists()


def test_test_command_rejects_shell_operators():
    assert validate_command(["pytest", "tests/test_upload.py"]) == (True, "")
    ok, detail = validate_command(["pytest", "tests", "&&", "echo", "bad"])
    assert ok is False
    assert "命令串联" in detail


def test_result_gate_matches_current_execution_record_and_command(tmp_path):
    _write_test_documents(tmp_path)
    state = _state(tmp_path)
    command = [sys.executable, "-c", "raise SystemExit(0)"]
    prepare_task(str(tmp_path), state, TOPIC, "TC-01", command)
    assert run_prepared_tasks(str(tmp_path), state, parallelism=1)[0].status == "passed"
    command_text = shlex.join(command)
    (tmp_path / "qa" / f"{TOPIC}_result.md").write_text(
        f"""# 【主题测试结果】{TOPIC}

- 工作流编号：{WORKFLOW_ID}
- 验收主题：{TOPIC}
- 自动化测试结果：通过
- 人工验收状态：无需人工验收

## 3. 测试项结果

### TC-01：验证上传完成

- 对应验收条件：AC-01 上传完成
- 测试入口：tests/test_upload.py::test_upload
- 执行命令：{command_text}
- 退出码：0
- 实际结果：命令退出码为 0，测试入口完成执行
- 自动化测试结果：通过
- 证据：State Snapshot 中的当前执行记录
""",
        encoding="utf-8",
    )

    ok, detail = validate_test_execution_results(str(tmp_path), WORKFLOW_ID, [TOPIC])

    assert ok is True, detail

    result_path = tmp_path / "qa" / f"{TOPIC}_result.md"
    result_path.write_text(result_path.read_text(encoding="utf-8").replace("退出码：0", "退出码：1"), encoding="utf-8")
    ok, detail = validate_test_execution_results(str(tmp_path), WORKFLOW_ID, [TOPIC])
    assert ok is False
    assert "退出码 0" in detail


def _write_dependency_topic(tmp_path: Path, topic: str, entry_name: str) -> None:
    (tmp_path / "qa").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "qa" / f"{topic}_plan.md").write_text(
        f"""# {topic}测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：{topic}完成](../acceptance/{topic}_plan.md#ac-01) | <a id=\"tc-01\"></a>[TC-01 验证{topic}完成](#tc-01) | 无 | 自动化测试 | 检查{topic} | {topic}完成 | 保留执行证据 |
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
    测试目标：检查{topic}对应的真实命令完成
    测试入口：tests/test_{entry_name}.py::test_{entry_name}
    代码入口：src/{entry_name}.py 的 run()
    """
    assert True
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
    first = "准备上传环境"
    second = "上传文件"
    _write_dependency_topic(tmp_path, first, "prepare_upload")
    _write_dependency_topic(tmp_path, second, "upload_file")
    (tmp_path / "qa" / "index.md").write_text(
        f"""# 测试计划索引

## {WORKFLOW_ID}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 测试结果 |
|---|---|---|---|---|---|
| 1 | {first} | 无 | [验收计划](../acceptance/{first}_plan.md) | [测试计划](./{first}_plan.md) | [测试结果](./{first}_result.md) |
| 2 | {second} | {first} | [验收计划](../acceptance/{second}_plan.md) | [测试计划](./{second}_plan.md) | [测试结果](./{second}_result.md) |
""",
        encoding="utf-8",
    )
    recorder = tmp_path / "record_order.py"
    recorder.write_text(
        """from pathlib import Path
import sys
import time

if sys.argv[1] == "first":
    time.sleep(0.15)
with Path(sys.argv[3]).open("a", encoding="utf-8") as stream:
    stream.write(sys.argv[2] + "\\n")
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
        [sys.executable, str(recorder), "first", first, str(order_path)],
    )
    prepare_task(
        str(tmp_path),
        state,
        second,
        "TC-01",
        [sys.executable, str(recorder), "second", second, str(order_path)],
    )

    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=2)

    assert [attempt.status for attempt in attempts] == ["passed", "passed"]
    assert order_path.read_text(encoding="utf-8").splitlines() == [first, second]


def test_failed_predecessor_topic_blocks_dependent_topic(tmp_path):
    first = "准备上传环境"
    second = "上传文件"
    _write_dependency_topic(tmp_path, first, "prepare_upload")
    _write_dependency_topic(tmp_path, second, "upload_file")
    (tmp_path / "qa" / "index.md").write_text(
        f"""# 测试计划索引

## {WORKFLOW_ID}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 测试结果 |
|---|---|---|---|---|---|
| 1 | {first} | 无 | [验收计划](../acceptance/{first}_plan.md) | [测试计划](./{first}_plan.md) | [测试结果](./{first}_result.md) |
| 2 | {second} | {first} | [验收计划](../acceptance/{second}_plan.md) | [测试计划](./{second}_plan.md) | [测试结果](./{second}_result.md) |
""",
        encoding="utf-8",
    )
    state = _dependency_state(tmp_path, [first, second])
    prepare_task(
        str(tmp_path),
        state,
        first,
        "TC-01",
        [sys.executable, "-c", "raise SystemExit(1)"],
    )
    prepare_task(
        str(tmp_path),
        state,
        second,
        "TC-01",
        [sys.executable, "-c", "raise SystemExit(0)"],
    )

    attempts = run_prepared_tasks(str(tmp_path), state, parallelism=2)
    statuses = {(attempt.topic, attempt.test_id): attempt.status for attempt in attempts}

    assert statuses[(first, "TC-01")] == "failed"
    assert statuses[(second, "TC-01")] == "blocked"
