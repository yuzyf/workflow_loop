import copy
import os

from workflow_loop.project import create_project, load_project, register_topics, save_project
from workflow_loop.state import (
    WorkflowState,
    StageState,
    GateState,
    RegressionTestState,
    TestExecutionRecord as ExecutionRecord,
    TestTaskState as ExecutionTask,
    save_state,
)
from workflow_loop.verification import (
    compute_file_hash, compute_impl_hash, compute_test_plan_hash,
    compute_acceptance_plan_hash, compute_test_result_hash,
    compute_acceptance_result_hash,
    compute_code_snapshot_hash, compute_regression_test_result_hash,
    compute_non_test_code_snapshot_hash, compute_test_code_snapshot_hash,
    compute_product_design_hash, compute_code_design_hash,
    get_linked_product_design_paths, check_invalidation, clear_stage_gates,
    clear_completed_material_recovery, recovery_stage_action,
    compute_registered_file_snapshot, compute_document_snapshot,
    compute_test_plan_document_snapshot, compute_acceptance_plan_document_snapshot,
    inspect_invalidation, apply_invalidation,
)


# 测试辅助函数：构造一个已经进入后半段、带验证哈希的 WorkflowState
def _make_state(project_root, impl_hash=None, test_plan_hash=None, acceptance_plan_hash=None, test_result_hash=None):
    stage_path = [
        "acceptance_plan", "impl", "test_plan", "test_code",
        "test_execution", "topic_acceptance",
        "regression_test", "overall_acceptance", "update_code_design",
    ]
    state = WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        current_stage="regression_test",
        started_at="2026-07-20T00:00:00+00:00",
        stage_path=stage_path,
        topics=["test_topic"],
    )
    state.stages = {
        stage_name: StageState(
            status="done",
            gate=GateState(True, True, True),
        )
        for stage_name in stage_path
    }
    state.stages["regression_test"].status = "in_progress"
    # 写入 impl_hash（impl --confirmed 时记录）
    state.verification.impl_hash = impl_hash
    # 写入 test_plan_hash（test_plan --confirmed 时记录）
    state.verification.test_plan_hash = test_plan_hash
    # 写入 acceptance_plan_hash（acceptance_plan --confirmed 时记录）
    state.verification.acceptance_plan_hash = acceptance_plan_hash
    # 写入 test_result_hash（test --confirmed 时记录）
    state.verification.test_result_hash = test_result_hash
    # 返回构造好的 state
    return state


# 测试 compute_file_hash：对单个文件计算 SHA256，文件不存在时返回 None
def test_compute_file_hash(tmp_path):
    # 拼出测试文件路径
    path = os.path.join(str(tmp_path), "test.txt")
    # 写入二进制内容
    with open(path, "wb") as f:
        f.write(b"hello world")
    # 计算文件哈希
    h = compute_file_hash(str(tmp_path), "test.txt")
    # 验证哈希非空
    assert h is not None
    # 验证 SHA256 长度为 64 字符
    assert len(h) == 64
    # 验证文件不存在时返回 None（不抛异常）
    assert compute_file_hash(str(tmp_path), "nonexistent.txt") is None


def test_product_design_hash_uses_only_linked_feature_documents(tmp_path):
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "产品总说明.md").write_text(
        "[功能 A](./功能_a.md)\n[外部文档](https://example.com)\n",
        encoding="utf-8",
    )
    (spec_dir / "功能_a.md").write_text("A", encoding="utf-8")
    (spec_dir / "功能_已删除.md").write_text("old", encoding="utf-8")

    paths = get_linked_product_design_paths(str(tmp_path))
    first_hash, _ = compute_product_design_hash(str(tmp_path))
    (spec_dir / "功能_已删除.md").write_text("changed old", encoding="utf-8")
    second_hash, _ = compute_product_design_hash(str(tmp_path))

    assert paths == ["spec/产品总说明.md", "spec/功能_a.md"]
    assert first_hash == second_hash


def test_product_and_code_design_hash_change_with_content(tmp_path):
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "产品总说明.md").write_text("[功能 A](./功能_a.md)\n", encoding="utf-8")
    (spec_dir / "功能_a.md").write_text("A", encoding="utf-8")
    (spec_dir / "代码架构设计.md").write_text("code v1", encoding="utf-8")

    product_hash_1, _ = compute_product_design_hash(str(tmp_path))
    code_hash_1 = compute_code_design_hash(str(tmp_path))
    (spec_dir / "功能_a.md").write_text("A changed", encoding="utf-8")
    (spec_dir / "代码架构设计.md").write_text("code v2", encoding="utf-8")

    product_hash_2, _ = compute_product_design_hash(str(tmp_path))
    code_hash_2 = compute_code_design_hash(str(tmp_path))
    assert product_hash_1 != product_hash_2
    assert code_hash_1 != code_hash_2


# 测试 compute_impl_hash 包含代码快照：impl 记录 + 项目代码任一变化都会改变哈希
def test_compute_impl_hash_includes_code_snapshot(tmp_path):
    # 创建 impl 目录
    impl_dir = os.path.join(str(tmp_path), "impl")
    os.makedirs(impl_dir)
    # 写入实施记录文件
    with open(os.path.join(impl_dir, "test_topic_实施记录.md"), "w") as f:
        f.write("impl record")
    # 第一次计算 impl 哈希
    h1 = compute_impl_hash(str(tmp_path), "test_topic")
    # 第二次计算（无变化）
    h2 = compute_impl_hash(str(tmp_path), "test_topic")
    # 验证两次哈希一致（确定性）
    assert h1 == h2
    # 新增一个代码文件
    with open(os.path.join(str(tmp_path), "new_code.py"), "w") as f:
        f.write("print('hello')")
    # 再次计算 impl 哈希
    h3 = compute_impl_hash(str(tmp_path), "test_topic")
    # 验证代码变化后哈希改变（用于 invalidation 检测）
    assert h1 != h3


def test_compute_impl_hash_ignores_test_code_changes(tmp_path):
    impl_dir = os.path.join(str(tmp_path), "impl")
    tests_dir = os.path.join(str(tmp_path), "tests")
    os.makedirs(impl_dir)
    os.makedirs(tests_dir)
    with open(os.path.join(impl_dir, "test_topic_实施记录.md"), "w") as stream:
        stream.write("impl record")
    with open(os.path.join(tests_dir, "test_topic.py"), "w") as stream:
        stream.write("def test_one(): pass")

    before = compute_impl_hash(str(tmp_path), "test_topic")
    with open(os.path.join(tests_dir, "test_topic.py"), "w") as stream:
        stream.write("def test_one(): assert True")

    assert compute_impl_hash(str(tmp_path), "test_topic") == before


def test_structured_pyproject_changes_are_split_between_test_and_product_hashes(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-03 测试代码追踪标识准确绑定要求
    验收条件：AC-03 测试代码能够追踪到产品要求
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：测试工具配置和开发依赖组只改变测试代码哈希而正式产品配置改变产品代码哈希
    测试入口：tests/test_verification.py::test_structured_pyproject_changes_are_split_between_test_and_product_hashes
    代码入口：workflow_loop.verification._split_pyproject_config
    """
    create_project(str(tmp_path))
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "demo"
version = "0.1.0"

[project.optional-dependencies]
test = ["pytest>=7"]

[dependency-groups]
dev = ["pytest>=7"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
        encoding="utf-8",
    )
    test_before = compute_test_code_snapshot_hash(str(tmp_path))
    product_before = compute_non_test_code_snapshot_hash(str(tmp_path))

    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'testpaths = ["tests"]',
            'testpaths = ["tests", "integration"]',
        ),
        encoding="utf-8",
    )

    assert compute_test_code_snapshot_hash(str(tmp_path)) != test_before
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) == product_before

    test_after = compute_test_code_snapshot_hash(str(tmp_path))
    product_after = compute_non_test_code_snapshot_hash(str(tmp_path))
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'dev = ["pytest>=7"]',
            'dev = ["pytest>=7", "pyyaml>=6"]',
        ),
        encoding="utf-8",
    )

    assert compute_test_code_snapshot_hash(str(tmp_path)) != test_after
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) == product_after

    test_after = compute_test_code_snapshot_hash(str(tmp_path))
    product_after = compute_non_test_code_snapshot_hash(str(tmp_path))
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'version = "0.1.0"',
            'version = "0.2.0"',
        ),
        encoding="utf-8",
    )

    assert compute_test_code_snapshot_hash(str(tmp_path)) == test_after
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) != product_after


def test_test_prefixed_source_module_stays_in_product_hash(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-03 测试代码追踪标识准确绑定要求
    验收条件：AC-03 测试代码能够追踪到产品要求
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：产品源码中的 test_ 前缀模块归入产品哈希，真测试目录和明确测试后缀归入测试哈希
    测试入口：tests/test_verification.py::test_test_prefixed_source_module_stays_in_product_hash
    代码入口：workflow_loop.verification.compute_non_test_code_snapshot_hash 和 compute_test_code_snapshot_hash
    """
    create_project(str(tmp_path))
    product_module = tmp_path / "src" / "workflow_loop" / "test_execution.py"
    directory_test = tmp_path / "tests" / "test_execution.py"
    suffix_test = tmp_path / "src" / "components" / "button.test.ts"
    product_module.parent.mkdir(parents=True)
    directory_test.parent.mkdir(parents=True)
    suffix_test.parent.mkdir(parents=True)
    product_module.write_text("PRODUCT = 1\n", encoding="utf-8")
    directory_test.write_text("def test_execution(): pass\n", encoding="utf-8")
    suffix_test.write_text("test('button', () => {})\n", encoding="utf-8")

    product_before = compute_non_test_code_snapshot_hash(str(tmp_path))
    test_before = compute_test_code_snapshot_hash(str(tmp_path))
    product_module.write_text("PRODUCT = 2\n", encoding="utf-8")

    product_after = compute_non_test_code_snapshot_hash(str(tmp_path))
    test_after = compute_test_code_snapshot_hash(str(tmp_path))
    assert product_after != product_before
    assert test_after == test_before

    directory_test.write_text("def test_execution(): assert True\n", encoding="utf-8")
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) == product_after
    assert compute_test_code_snapshot_hash(str(tmp_path)) != test_after

    test_after = compute_test_code_snapshot_hash(str(tmp_path))
    suffix_test.write_text("test('button', () => { expect(true) })\n", encoding="utf-8")
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) == product_after
    assert compute_test_code_snapshot_hash(str(tmp_path)) != test_after


def test_test_entry_command_and_script_are_part_of_test_code_hash(tmp_path):
    create_project(str(tmp_path))
    script = tmp_path / "scripts" / "test_all.sh"
    script.parent.mkdir()
    script.write_text("#!/usr/bin/env bash\necho one\n", encoding="utf-8")
    project = load_project(str(tmp_path))
    assert project is not None
    project.test_entry = "bash scripts/test_all.sh"
    save_project(str(tmp_path), project)

    before = compute_test_code_snapshot_hash(str(tmp_path))
    product_before = compute_non_test_code_snapshot_hash(str(tmp_path))
    script.write_text("#!/usr/bin/env bash\necho two\n", encoding="utf-8")

    assert compute_test_code_snapshot_hash(str(tmp_path)) != before
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) == product_before


def test_common_cross_language_test_filenames_are_part_of_test_hash(tmp_path):
    create_project(str(tmp_path))
    paths = [
        tmp_path / "src" / "parser_test.go",
        tmp_path / "lib" / "parser_spec.rb",
        tmp_path / "ui" / "button.test.tsx",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test v1\n", encoding="utf-8")

    test_before = compute_test_code_snapshot_hash(str(tmp_path))
    product_before = compute_non_test_code_snapshot_hash(str(tmp_path))
    paths[0].write_text("test v2\n", encoding="utf-8")

    assert compute_test_code_snapshot_hash(str(tmp_path)) != test_before
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) == product_before


def test_cpp_product_test_and_qmake_files_are_classified_separately(tmp_path):
    create_project(str(tmp_path))
    product_file = tmp_path / "src" / "uploader.cpp"
    test_file = tmp_path / "src" / "uploader_test.cpp"
    project_file = tmp_path / "workflow_loop.pro"
    product_file.parent.mkdir(parents=True)
    product_file.write_text("int upload() { return 1; }\n", encoding="utf-8")
    test_file.write_text("void testUpload() {}\n", encoding="utf-8")
    project_file.write_text("SOURCES += src/uploader.cpp\n", encoding="utf-8")

    test_before = compute_test_code_snapshot_hash(str(tmp_path))
    product_before = compute_non_test_code_snapshot_hash(str(tmp_path))
    test_file.write_text("void testUpload() { verify(); }\n", encoding="utf-8")

    assert compute_test_code_snapshot_hash(str(tmp_path)) != test_before
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) == product_before

    test_after = compute_test_code_snapshot_hash(str(tmp_path))
    product_after = compute_non_test_code_snapshot_hash(str(tmp_path))
    product_file.write_text("int upload() { return 2; }\n", encoding="utf-8")
    project_file.write_text("SOURCES += src/uploader.cpp\nDEFINES += V2\n", encoding="utf-8")

    assert compute_test_code_snapshot_hash(str(tmp_path)) == test_after
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) != product_after


def test_confirmed_test_code_change_returns_to_test_code(tmp_path):
    create_project(str(tmp_path))
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_demo.py"
    test_file.write_text("def test_demo():\n    assert True\n", encoding="utf-8")
    state = _make_state(str(tmp_path))
    state.verification.test_code_hash = compute_test_code_snapshot_hash(str(tmp_path))
    test_file.write_text("def test_demo():\n    assert 1 == 1\n", encoding="utf-8")

    invalidations = check_invalidation(state, str(tmp_path))

    assert invalidations == [("test_code", "test_code 及全部后续阶段")]
    assert state.current_stage == "test_code"
    assert state.verification.test_code_hash is None


def test_active_snapshot_ignores_unregistered_build_and_dependency_files(tmp_path):
    create_project(str(tmp_path))
    source = tmp_path / "src" / "core.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    generated = tmp_path / ".next" / "bundle.js"
    generated.parent.mkdir()
    generated.write_text("one\n", encoding="utf-8")
    dependency = tmp_path / "node_modules" / "pkg.js"
    dependency.parent.mkdir()
    dependency.write_text("one\n", encoding="utf-8")
    state = _make_state(str(tmp_path))
    state.rollback.planned_paths = ["src/core.py"]
    save_state(str(tmp_path), state)

    baseline = compute_non_test_code_snapshot_hash(str(tmp_path))
    generated.write_text("two\n", encoding="utf-8")
    dependency.write_text("two\n", encoding="utf-8")
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) == baseline

    source.write_text("value = 2\n", encoding="utf-8")
    assert compute_non_test_code_snapshot_hash(str(tmp_path)) != baseline


def test_active_snapshot_without_registered_paths_does_not_guess_core_code(tmp_path):
    create_project(str(tmp_path))
    source = tmp_path / "src" / "core.py"
    generated = tmp_path / ".next" / "bundle.js"
    dependency = tmp_path / "node_modules" / "pkg.js"
    source.parent.mkdir()
    generated.parent.mkdir()
    dependency.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    generated.write_text("one\n", encoding="utf-8")
    dependency.write_text("one\n", encoding="utf-8")
    state = _make_state(str(tmp_path))
    state.topics = []
    save_state(str(tmp_path), state)

    baseline = compute_non_test_code_snapshot_hash(str(tmp_path))
    source.write_text("value = 2\n", encoding="utf-8")
    generated.write_text("two\n", encoding="utf-8")
    dependency.write_text("two\n", encoding="utf-8")

    assert compute_non_test_code_snapshot_hash(str(tmp_path)) == baseline


def test_test_snapshot_uses_only_test_plan_entries_and_registered_runner(tmp_path):
    create_project(str(tmp_path))
    register_topics(str(tmp_path), ["test_topic"])
    source = tmp_path / "src" / "core.py"
    test_file = tmp_path / "tests" / "test_core.py"
    runner = tmp_path / "tools" / "run_tests.py"
    generated = tmp_path / ".next" / "test_core.js"
    for path, content in (
        (source, "def run():\n    return 1\n"),
        (test_file, "def test_run():\n    assert True\n"),
        (runner, "print('run')\n"),
        (generated, "one\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    qa_plan = tmp_path / "qa" / "test_topic_测试计划.md"
    qa_plan.parent.mkdir()
    qa_plan.write_text(
        """## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 产品入口 | 代码入口 | 测试入口 | 准备数据 | 执行动作 | 观察位置 | 预期结果 | 不通过表现 | 证据要求 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [AC-01：结果可见](../acceptance/test_topic_验收计划.md#ac-01) | <a id="tc-01"></a>[TC-01 验证结果](#tc-01) | 无 | 自动化测试 | 项目命令 | `src/core.py::run` | `tests/test_core.py::test_run` | 创建隔离数据 | 调用真实入口 | 返回值 | 返回值为 1 | 返回值不是 1 | 结构化报告 |
""",
        encoding="utf-8",
    )
    state = _make_state(str(tmp_path))
    state.rollback.planned_paths = ["src/core.py"]
    save_state(str(tmp_path), state)
    project = load_project(str(tmp_path))
    project.test_entry = {"default": ["python", "tools/run_tests.py"]}
    save_project(str(tmp_path), project)

    baseline = compute_test_code_snapshot_hash(str(tmp_path))
    generated.write_text("two\n", encoding="utf-8")
    assert compute_test_code_snapshot_hash(str(tmp_path)) == baseline

    test_file.write_text("def test_run():\n    assert 1 == 1\n", encoding="utf-8")
    assert compute_test_code_snapshot_hash(str(tmp_path)) != baseline
    test_baseline = compute_test_code_snapshot_hash(str(tmp_path))
    runner.write_text("print('changed')\n", encoding="utf-8")
    assert compute_test_code_snapshot_hash(str(tmp_path)) != test_baseline


def test_invalidation_inspection_lists_exact_changes_before_one_apply(tmp_path):
    create_project(str(tmp_path))
    register_topics(str(tmp_path), ["test_topic"])
    source = tmp_path / "src" / "core.py"
    impl_index = tmp_path / "impl" / "索引.md"
    impl_record = tmp_path / "impl" / "test_topic_实施记录.md"
    source.parent.mkdir()
    impl_index.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    impl_index.write_text("index one\n", encoding="utf-8")
    impl_record.write_text("record one\n", encoding="utf-8")

    state = _make_state(str(tmp_path))
    state.rollback.planned_paths = ["src/core.py"]
    state.verification.test_plan_hash = "later-binding"
    save_state(str(tmp_path), state)
    state.verification.impl_hash = compute_impl_hash(str(tmp_path), state.topics)
    state.meta["registered_snapshots"] = {
        "impl": compute_registered_file_snapshot(str(tmp_path), scope="product"),
        "impl_documents": compute_document_snapshot(
            str(tmp_path),
            ["impl/索引.md", "impl/test_topic_实施记录.md"],
        ),
    }
    save_state(str(tmp_path), state)
    source.write_text("value = 2\n", encoding="utf-8")
    impl_record.write_text("record two\n", encoding="utf-8")
    before = copy.deepcopy(state)

    inspection = inspect_invalidation(state, str(tmp_path))

    assert inspection.source_stage == "impl"
    assert state == before
    locations = {item.location for item in inspection.diagnostics if item.kind == "error"}
    assert "src/core.py" in locations
    assert "impl/test_topic_实施记录.md" in locations
    assert any(
        item.kind == "not_checked" and "test_plan" in item.check_id
        for item in inspection.diagnostics
    )

    invalidations = apply_invalidation(state, str(tmp_path), inspection)

    assert invalidations == [("impl", "impl 及全部后续阶段")]
    assert state.current_stage == "impl"
    assert state.verification.impl_hash is None
    assert state.verification.test_plan_hash is None


def _write_two_topic_impl_inputs(tmp_path, topics):
    (tmp_path / "impl").mkdir(exist_ok=True)
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "impl" / "索引.md").write_text("# 实施索引\n", encoding="utf-8")
    code_paths = {}
    for index, topic in enumerate(topics, start=1):
        code_path = f"src/topic_{index}.py"
        code_paths[topic] = code_path
        (tmp_path / code_path).write_text(
            f"def run_topic_{index}():\n    return {index}\n",
            encoding="utf-8",
        )
        (tmp_path / "impl" / f"{topic}_实施记录.md").write_text(
            f"""# {topic}实施记录

### 2.2 代码修改计划

| 顺序 | 文件 | 类、函数或配置项 | 当前逻辑 | 计划修改的具体逻辑 | 数据、状态或输出变化 | 对应验收条件 | 前置步骤 |
|---|---|---|---|---|---|---|---|
| 1 | {code_path} | run_topic_{index} | 返回旧值 | 返回主题值 | 调用后得到主题值 | AC-01 | 无 |
""",
            encoding="utf-8",
        )
    return code_paths


def _write_two_topic_traceability(tmp_path, topics):
    rows = [
        (
            f"| [产品设计](./spec/产品总说明.md) | "
            f"[{topic}](./acceptance/{topic}_验收计划.md) | AC-01 | "
            f"[测试计划 {topic}](./qa/{topic}_测试计划.md) | "
            f"[实施计划 {topic}](./impl/{topic}_实施记录.md#2-实施前计划) | "
            f"[实施记录 {topic}](./impl/{topic}_实施记录.md#3-实施后记录) | "
            f"[测试结果 {topic}](./qa/{topic}_测试结果.md) | "
            f"[验收结果 {topic}](./acceptance/{topic}_验收结果.md) | 已更新 |"
        )
        for topic in topics
    ]
    (tmp_path / "需求交付追踪表.md").write_text(
        """# 需求交付追踪表

## test

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
"""
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )


def test_impl_invalidation_only_clears_the_topic_that_owns_changed_code(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-03 只使直接受影响主题结果失效
    验收条件：AC-03 只清除真实受影响的结果
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：两个独立主题中只有一个主题登记的核心代码变化时保留另一个主题事实
    测试入口：tests/test_verification.py::test_impl_invalidation_only_clears_the_topic_that_owns_changed_code
    代码入口：workflow_loop.verification.inspect_invalidation 和 apply_invalidation
    """
    topics = ["上传文件", "查看状态"]
    create_project(str(tmp_path))
    register_topics(str(tmp_path), topics)
    code_paths = _write_two_topic_impl_inputs(tmp_path, topics)
    _write_two_topic_traceability(tmp_path, topics)

    state = _make_state(str(tmp_path))
    state.topics = topics
    state.rollback.planned_paths = list(code_paths.values())
    save_state(str(tmp_path), state)
    state.stages["test_execution"].test_tasks = {
        topic: {"TC-01": ExecutionTask(status="passed")}
        for topic in topics
    }
    state.stages["topic_acceptance"].acceptance_records = {
        topic: {"AC-01": object()}
        for topic in topics
    }
    state.verification.impl_hash = compute_impl_hash(str(tmp_path), topics)
    state.meta["registered_snapshots"] = {
        "impl": compute_registered_file_snapshot(str(tmp_path), scope="product"),
        "impl_documents": compute_document_snapshot(
            str(tmp_path),
            ["impl/索引.md", *[f"impl/{topic}_实施记录.md" for topic in topics]],
        ),
    }
    for topic in topics:
        for suffix, directory in (("测试结果", "qa"), ("验收结果", "acceptance")):
            path = tmp_path / directory / f"{topic}_{suffix}.md"
            path.parent.mkdir(exist_ok=True)
            path.write_text(f"{topic} old result\n", encoding="utf-8")

    changed_topic, kept_topic = topics
    (tmp_path / code_paths[changed_topic]).write_text(
        "def run_topic_1():\n    return 100\n",
        encoding="utf-8",
    )

    inspection = inspect_invalidation(state, str(tmp_path))

    assert inspection.source_stage == "impl"
    assert inspection.affected_topics == (changed_topic,)
    assert any(
        item.location == code_paths[changed_topic] and item.actual == "内容修改"
        for item in inspection.diagnostics
    )

    apply_invalidation(state, str(tmp_path), inspection)

    assert changed_topic not in state.stages["test_execution"].test_tasks
    assert kept_topic in state.stages["test_execution"].test_tasks
    assert changed_topic not in state.stages["topic_acceptance"].acceptance_records
    assert kept_topic in state.stages["topic_acceptance"].acceptance_records
    assert not (tmp_path / "qa" / f"{changed_topic}_测试结果.md").exists()
    assert not (tmp_path / "acceptance" / f"{changed_topic}_验收结果.md").exists()
    assert (tmp_path / "qa" / f"{kept_topic}_测试结果.md").is_file()
    assert (tmp_path / "acceptance" / f"{kept_topic}_验收结果.md").is_file()
    traceability = (tmp_path / "需求交付追踪表.md").read_text(encoding="utf-8")
    changed_row = next(line for line in traceability.splitlines() if f"acceptance/{changed_topic}_验收计划.md" in line)
    kept_row = next(line for line in traceability.splitlines() if f"acceptance/{kept_topic}_验收计划.md" in line)
    assert "待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新" in changed_row
    assert f"测试结果 {kept_topic}" in kept_row
    assert state.recovery.affected_topics == [changed_topic]


def test_shared_test_plan_index_change_affects_all_topics(tmp_path):
    topics = ["上传文件", "查看状态"]
    create_project(str(tmp_path))
    register_topics(str(tmp_path), topics)
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    (qa_dir / "索引.md").write_text("# 测试索引 v1\n", encoding="utf-8")
    for topic in topics:
        (qa_dir / f"{topic}_测试计划.md").write_text(
            f"# {topic}测试计划\n",
            encoding="utf-8",
        )
    state = _make_state(str(tmp_path))
    state.topics = topics
    state.verification.test_plan_hash = compute_test_plan_hash(str(tmp_path), topics)
    state.meta["registered_snapshots"] = {
        "test_plan_documents": compute_document_snapshot(
            str(tmp_path),
            ["qa/索引.md", *[f"qa/{topic}_测试计划.md" for topic in topics]],
        )
    }
    (qa_dir / "索引.md").write_text("# 测试索引 v2\n", encoding="utf-8")

    inspection = inspect_invalidation(state, str(tmp_path))

    assert inspection.source_stage == "test_plan"
    assert inspection.affected_topics == tuple(topics)
    assert any(
        item.location == "qa/索引.md" and item.actual == "内容修改"
        for item in inspection.diagnostics
    )


def test_test_result_link_transition_does_not_invalidate_test_plan(tmp_path):
    """测试执行写回结果链接属于下游状态，不应清空已确认测试计划。"""
    topic = "test_topic"
    create_project(str(tmp_path))
    register_topics(str(tmp_path), [topic])
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    plan_path = qa_dir / f"{topic}_测试计划.md"
    plan_path.write_text("# 测试计划\n\n计划内容保持不变\n", encoding="utf-8")
    index = (
        "# 测试索引\n\n"
        "## test\n\n"
        "| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 实施记录 | 测试计划 | 测试结果 |\n"
        "|---|---|---|---|---|---|---|\n"
        f"| 1 | {topic} | 无 | [验收](../acceptance/{topic}_验收计划.md) | "
        f"[实施](../impl/{topic}_实施记录.md) | [计划](./{topic}_测试计划.md) | "
        f"`./{topic}_测试结果.md`（待生成） |\n"
    )
    (qa_dir / "索引.md").write_text(index, encoding="utf-8")

    state = _make_state(str(tmp_path))
    state.workflow_id = "test"
    state.topics = [topic]
    state.verification.test_plan_hash = compute_test_plan_hash(str(tmp_path), [topic])
    state.meta["registered_snapshots"] = {
        "test_plan_documents": compute_test_plan_document_snapshot(str(tmp_path), [topic])
    }

    before_hash = state.verification.test_plan_hash
    result_path = qa_dir / f"{topic}_测试结果.md"
    result_path.write_text("# 结果\n", encoding="utf-8")
    (qa_dir / "索引.md").write_text(index.replace(
        f"`./{topic}_测试结果.md`（待生成）",
        f"[结果](./{topic}_测试结果.md)",
    ), encoding="utf-8")

    assert compute_test_plan_hash(str(tmp_path), [topic]) == before_hash
    inspection = inspect_invalidation(state, str(tmp_path))
    assert inspection.changed is False


def test_acceptance_result_link_transition_does_not_invalidate_acceptance_plan(tmp_path):
    """主题验收写回结果链接属于下游状态，不应清空已确认验收计划。"""
    topic = "test_topic"
    create_project(str(tmp_path))
    register_topics(str(tmp_path), [topic])
    acceptance_dir = tmp_path / "acceptance"
    acceptance_dir.mkdir()
    plan_path = acceptance_dir / f"{topic}_验收计划.md"
    plan_path.write_text("# 验收计划\n\n验收条件保持不变\n", encoding="utf-8")
    index = (
        "# 验收索引\n\n"
        "## test\n\n"
        "| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |\n"
        "|---|---|---|---|---|\n"
        f"| 1 | {topic} | 无 | [计划](./{topic}_验收计划.md) | "
        f"`./{topic}_验收结果.md`（待生成） |\n"
    )
    (acceptance_dir / "索引.md").write_text(index, encoding="utf-8")

    state = _make_state(str(tmp_path))
    state.workflow_id = "test"
    state.topics = [topic]
    state.verification.acceptance_plan_hash = compute_acceptance_plan_hash(
        str(tmp_path), [topic]
    )
    state.meta["registered_snapshots"] = {
        "acceptance_plan_documents": compute_acceptance_plan_document_snapshot(
            str(tmp_path), [topic]
        )
    }

    before_hash = state.verification.acceptance_plan_hash
    result_path = acceptance_dir / f"{topic}_验收结果.md"
    result_path.write_text("# 结果\n", encoding="utf-8")
    (acceptance_dir / "索引.md").write_text(index.replace(
        f"`./{topic}_验收结果.md`（待生成）",
        f"[结果](./{topic}_验收结果.md)",
    ), encoding="utf-8")

    assert compute_acceptance_plan_hash(str(tmp_path), [topic]) == before_hash
    inspection = inspect_invalidation(state, str(tmp_path))
    assert inspection.changed is False


def test_test_plan_change_preserves_confirmed_implementation(tmp_path):
    create_project(str(tmp_path))
    register_topics(str(tmp_path), ["test_topic"])
    impl_dir = tmp_path / "impl"
    qa_dir = tmp_path / "qa"
    impl_dir.mkdir()
    qa_dir.mkdir()
    (impl_dir / "test_topic_实施记录.md").write_text("implemented", encoding="utf-8")
    plan = qa_dir / "test_topic_测试计划.md"
    plan.write_text("plan one", encoding="utf-8")
    impl_hash = compute_impl_hash(str(tmp_path), ["test_topic"])
    plan_hash = compute_test_plan_hash(str(tmp_path), ["test_topic"])
    state = _make_state(str(tmp_path), impl_hash=impl_hash, test_plan_hash=plan_hash)
    impl_gate = state.stages["impl"].gate
    plan.write_text("plan two", encoding="utf-8")

    invalidations = check_invalidation(state, str(tmp_path))

    assert invalidations == [("test_plan", "test_plan 及全部后续阶段（保留 impl）")]
    assert state.current_stage == "test_plan"
    assert state.verification.impl_hash == impl_hash
    assert state.stages["impl"].gate == impl_gate
    assert state.stages["impl"].status == "done"


# 测试 check_invalidation 在无变化时返回空列表（impl 哈希一致）
def test_check_invalidation_no_change(tmp_path):
    # 创建 impl 目录
    impl_dir = os.path.join(str(tmp_path), "impl")
    os.makedirs(impl_dir)
    # 写入实施记录
    with open(os.path.join(impl_dir, "test_topic_实施记录.md"), "w") as f:
        f.write("impl record")
    # 计算 impl 哈希
    impl_hash = compute_impl_hash(str(tmp_path), "test_topic")
    # 构造 state，绑定 impl_hash
    state = _make_state(str(tmp_path), impl_hash=impl_hash)
    # 检查 invalidation
    invalidations = check_invalidation(state, str(tmp_path))
    # 验证无 invalidation
    assert invalidations == []


# 测试实施内容变化时退回 impl（实施阶段）
def test_check_invalidation_impl_changed(tmp_path):
    # 创建 impl 目录
    impl_dir = os.path.join(str(tmp_path), "impl")
    os.makedirs(impl_dir)
    # 写入原始实施记录
    with open(os.path.join(impl_dir, "test_topic_实施记录.md"), "w") as f:
        f.write("original")
    # 计算 impl 哈希
    impl_hash = compute_impl_hash(str(tmp_path), "test_topic")
    # 构造 state，绑定 impl_hash
    state = _make_state(str(tmp_path), impl_hash=impl_hash)
    state.stages["test_execution"].test_tasks = {
        "test_topic": {
            "TC-01": ExecutionTask(
                status="passed",
                current_record=ExecutionRecord(
                    status="passed",
                    exit_code=0,
                    code_snapshot_hash="old-code",
                    test_code_hash="old-test-code",
                ),
            )
        }
    }
    state.regression_test = RegressionTestState(status="passed", exit_code=0)
    qa_result = tmp_path / "qa" / "test_topic_测试结果.md"
    acceptance_result = tmp_path / "acceptance" / "test_topic_验收结果.md"
    qa_result.parent.mkdir(exist_ok=True)
    acceptance_result.parent.mkdir(exist_ok=True)
    qa_result.write_text("old test result", encoding="utf-8")
    acceptance_result.write_text("old acceptance result", encoding="utf-8")
    # 修改 impl 记录内容（触发 invalidation）
    with open(os.path.join(impl_dir, "test_topic_实施记录.md"), "w") as f:
        f.write("changed")
    # 检查 invalidation
    invalidations = check_invalidation(state, str(tmp_path))
    # 验证有 1 条 invalidation
    assert len(invalidations) == 1
    # 验证实施变化会让主题测试、主题验收、最终回归和整体验收失效
    assert invalidations[0] == (
        "impl",
        "impl 及全部后续阶段",
    )
    assert state.current_stage == "impl"
    assert state.stages["impl"].status == "in_progress"
    assert state.stages["regression_test"].gate.code_validated is False
    assert state.verification.impl_hash is None
    assert state.stages["test_execution"].test_tasks == {}
    assert not qa_result.exists()
    assert not acceptance_result.exists()
    assert state.regression_test.status == "not_run"
    assert state.recovery.source_stage == "impl"
    assert "原测试计划、测试和验收结果不能继续代表当前实现" in state.recovery.reason
    assert recovery_stage_action(state, "test_code") is not None


def test_acceptance_result_change_returns_to_regression_test(tmp_path):
    acceptance_dir = os.path.join(str(tmp_path), "acceptance")
    os.makedirs(acceptance_dir)
    result_path = os.path.join(acceptance_dir, "test_topic_验收结果.md")
    with open(result_path, "w") as stream:
        stream.write("original")
    state = _make_state(str(tmp_path))
    state.verification.acceptance_result_hash = compute_acceptance_result_hash(
        str(tmp_path),
        "test_topic",
    )
    with open(result_path, "w") as stream:
        stream.write("changed")

    invalidations = check_invalidation(state, str(tmp_path))

    assert invalidations == [
        ("topic_acceptance", "regression_test、overall_acceptance 和 update_code_design")
    ]
    assert state.current_stage == "regression_test"


def test_regression_code_change_returns_to_regression_test(tmp_path):
    code_path = tmp_path / "app.py"
    code_path.write_text("VERSION = 1\n", encoding="utf-8")

    state = _make_state(str(tmp_path))
    state.regression_test = RegressionTestState(
        entry="scripts/test_all.sh",
        command="scripts/test_all.sh",
        started_at="2026-07-20T00:00:00+00:00",
        finished_at="2026-07-20T00:01:00+00:00",
        status="passed",
        exit_code=0,
        code_snapshot_hash=compute_code_snapshot_hash(str(tmp_path)),
        output_tail="134 passed",
    )
    save_state(str(tmp_path), state)
    state.verification.regression_test_result_hash = compute_regression_test_result_hash(
        str(tmp_path)
    )
    save_state(str(tmp_path), state)

    code_path.write_text("VERSION = 2\n", encoding="utf-8")

    invalidations = check_invalidation(state, str(tmp_path))

    assert invalidations == [
        ("regression_test", "regression_test、overall_acceptance 和 update_code_design")
    ]
    assert state.current_stage == "regression_test"
    assert state.verification.regression_test_result_hash is None


# 测试验收计划变化时退回 acceptance_plan（验收计划）
def test_check_invalidation_acceptance_plan_changed(tmp_path):
    # 创建 acceptance 目录
    acc_dir = os.path.join(str(tmp_path), "acceptance")
    os.makedirs(acc_dir)
    # 写入原始 acceptance plan
    with open(os.path.join(acc_dir, "test_topic_验收计划.md"), "w") as f:
        f.write("original")
    # 计算 acceptance_plan 哈希
    ap_hash = compute_acceptance_plan_hash(str(tmp_path), "test_topic")
    # 构造 state，绑定 acceptance_plan_hash
    state = _make_state(str(tmp_path), acceptance_plan_hash=ap_hash)
    state.stages["test_plan"].artifact_produced_at = "before"
    state.stages["test_plan"].artifact_baseline_captured_at = "before"
    state.stages["test_plan"].artifact_baseline_hashes = {"qa/索引.md": "old"}
    state.stages["impl"].code_baseline_hash = "old-code-baseline"
    # 修改 acceptance plan 内容（触发 invalidation）
    with open(os.path.join(acc_dir, "test_topic_验收计划.md"), "w") as f:
        f.write("changed")
    # 检查 invalidation
    invalidations = check_invalidation(state, str(tmp_path))
    # 验证有 1 条 invalidation
    assert len(invalidations) == 1
    # 验证验收计划变化会让测试计划、实施计划和执行结果失效
    assert invalidations[0] == (
        "acceptance_plan",
        "acceptance_plan 及全部后续阶段",
    )
    assert state.current_stage == "acceptance_plan"
    assert state.stages["acceptance_plan"].status == "in_progress"
    assert state.stages["test_plan"].gate.code_validated is False
    assert state.verification.acceptance_plan_hash is None
    assert state.stages["test_plan"].artifact_produced_at is None
    assert state.stages["test_plan"].artifact_baseline_captured_at is None
    assert state.stages["test_plan"].artifact_baseline_hashes == {}
    assert state.stages["impl"].code_baseline_hash is None
    assert state.recovery.source_stage == "acceptance_plan"
    assert recovery_stage_action(state, "impl").startswith("重新核对实施计划")


def test_recovery_actions_distinguish_recheck_from_rerun(tmp_path):
    """Workflow-Test
    主题：返回上游或整轮作废后状态与项目内容正确恢复
    测试项：TC-04 返回后区分重新核对和重新执行
    验收条件：AC-04 复用内容必须重新核对
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：返回后计划和既有代码先重新核对而测试执行和主题验收必须重新执行
    测试入口：tests/test_verification.py::test_recovery_actions_distinguish_recheck_from_rerun
    代码入口：workflow_loop.verification.recovery_stage_action
    """
    state = _make_state(str(tmp_path))
    state.recovery.source_stage = "test_plan"
    state.recovery.reason = "测试范围变化"
    state.recovery.affected_stages = [
        "test_plan",
        "impl",
        "test_code",
        "test_execution",
        "topic_acceptance",
    ]

    assert "不一致时才修改代码" in recovery_stage_action(state, "impl")
    assert "确认既有测试代码" in recovery_stage_action(state, "test_code")
    assert "重新登记并执行" in recovery_stage_action(state, "test_execution")
    assert "重新逐条验收" in recovery_stage_action(state, "topic_acceptance")


def test_completed_material_recovery_reason_is_cleared_after_source_stage(tmp_path):
    state = _make_state(str(tmp_path))
    state.current_stage = "topic_acceptance"
    state.stages["test_execution"].status = "done"
    state.recovery.source_stage = "test_execution"
    state.recovery.reason = "当前阶段的流程模板或规范已经更新，旧讨论结论必须重新确认"
    state.recovery.affected_stages = ["test_execution", "topic_acceptance"]

    assert clear_completed_material_recovery(state) is True
    assert state.recovery.source_stage is None
    assert state.recovery.reason is None


def test_content_invalidation_recovery_reason_is_cleared_after_source_stage(tmp_path):
    state = _make_state(str(tmp_path))
    state.current_stage = "impl"
    state.stages["test_plan"].status = "done"
    state.recovery.source_stage = "test_plan"
    state.recovery.reason = "测试项、测试方式或测试范围已经改变，后续实施和测试必须重新核对"
    state.recovery.affected_stages = ["test_plan", "impl", "test_code"]

    assert clear_completed_material_recovery(state) is True
    assert state.recovery.source_stage is None
    assert state.recovery.reason is None


def test_new_acceptance_topic_invalidates_confirmed_plan(tmp_path):
    create_project(str(tmp_path))
    acc_dir = tmp_path / "acceptance"
    acc_dir.mkdir()
    (acc_dir / "test_topic_验收计划.md").write_text("original", encoding="utf-8")
    register_topics(str(tmp_path), ["test_topic"])

    state = _make_state(str(tmp_path))
    state.verification.acceptance_plan_hash = compute_acceptance_plan_hash(
        str(tmp_path),
        ["test_topic"],
    )
    save_state(str(tmp_path), state)

    (acc_dir / "new_topic_验收计划.md").write_text("new", encoding="utf-8")
    invalidations = check_invalidation(state, str(tmp_path))

    assert invalidations == [("acceptance_plan", "acceptance_plan 及全部后续阶段")]
    assert state.current_stage == "acceptance_plan"
