import os
import json
import subprocess
import sys
import shutil

# 使用当前 pytest 解释器加载仓库源码，避免测试误跑全局安装的旧版本
WORKFLOW_CMD = [sys.executable, "-m", "workflow_loop.cli"]


# 测试辅助函数：在指定 cwd 下执行 workflow 命令，返回 (returncode, stdout, stderr)
def _run(args, cwd):
    # 启动子进程执行 workflow 命令
    result = subprocess.run(
        WORKFLOW_CMD + args,
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    # 返回三元组
    return result.returncode, result.stdout, result.stderr


# 测试辅助函数：在 tmp_path 下初始化一个已安装的项目
def _setup_project(tmp_path):
    # 创建 .workflow_loop 目录（确保 install-project 能写入）
    os.makedirs(os.path.join(str(tmp_path), ".workflow_loop"), exist_ok=True)
    # 执行 install-project
    code, out, err = _run(["install-project"], str(tmp_path))
    # 验证安装成功
    assert code == 0, f"install-project failed: {out} {err}"


def _advance_to_spike(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    _run(["gate", "spec", "--discuss-done"], str(tmp_path))
    spec_dir = os.path.join(str(tmp_path), "spec")
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "product.md"), "w") as f:
        f.write("# Product\n\n[功能](./feature_example.md)\n")
    with open(os.path.join(spec_dir, "feature_example.md"), "w") as f:
        f.write("# 【功能】Example\n")
    _run(["gate", "spec"], str(tmp_path))
    _run(["gate", "spec", "--confirmed"], str(tmp_path))
    _run(["gate", "code_design", "--discuss-done"], str(tmp_path))
    with open(os.path.join(spec_dir, "architecture_code_design.md"), "w") as f:
        f.write("# Architecture\n")
    _run(["gate", "code_design"], str(tmp_path))
    _run(["gate", "code_design", "--confirmed"], str(tmp_path))
    state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    with open(state_path) as f:
        return __import__("json").load(f)["workflow_id"]


def _write_valid_spike_documents(tmp_path, workflow_id):
    spec_dir = os.path.join(str(tmp_path), "spec")
    with open(os.path.join(spec_dir, "spike_index.md"), "w") as f:
        f.write(f"""# 【穿刺】穿刺清单

- 工作流编号：{workflow_id}

## SP-001 确认真实接口返回

- 真实场景：用户执行真实业务操作
- 要验证的不确定性：接口实际返回哪些字段
- 验证结果用于决定什么：决定接口解析和错误处理
- 结论文档：[确认真实接口返回](./spike_real_api_response.md)
- 穿刺状态：已确认
- 是否阻塞后续：否
- 产品设计影响：无需修改
- 代码设计影响：无需修改
- 后续处理阶段：无
""")

    with open(os.path.join(spec_dir, "spike_real_api_response.md"), "w") as f:
        f.write(f"""# 【穿刺】确认真实接口返回

- 工作流编号：{workflow_id}
- 穿刺项编号：SP-001

## 1. 真实场景与不确定性

用户执行真实业务操作时，代码需要读取真实接口返回字段。

## 2. 验证结果用于决定什么

结果用于决定接口解析和错误处理怎样设计。

## 3. 已知事实与验证范围

- 当前代码没有保存真实返回。
- 本次只调用真实只读接口。

## 4. 验证方法

- 使用的方法：调用真实只读接口
- 临时内容位置：无
- 执行步骤：执行真实请求并保存脱敏输出
- 外部影响：只读，不修改外部数据

## 5. 实际执行记录

- 执行时间：2026-07-23T12:00:00+08:00
- 运行环境：macOS，测试接口版本 v1
- 实际命令：curl 调用真实接口，凭据已省略
- 真实输入或样本：真实账号下的只读查询，响应哈希 abc123
- 执行失败：无

## 6. 实际观察结果

接口返回 data.items、error.code 和 error.message。

## 7. 结论

- 结果状态：已确认
- 是否阻塞后续：否
- 已确认内容：确认真实成功和失败返回字段
- 仍未确认内容：无

## 8. 对后续工作的影响

- 产品设计影响：无需修改
- 产品设计更新位置：无
- 代码设计影响：无需修改
- 代码设计更新位置：无
- 剩余风险：无
- 后续处理阶段：无
- 后续需要检查什么：无
""")


def _write_valid_acceptance_documents(tmp_path, workflow_id, topics):
    acceptance_dir = os.path.join(str(tmp_path), "acceptance")
    os.makedirs(acceptance_dir, exist_ok=True)
    rows = []
    for topic in topics:
        with open(os.path.join(acceptance_dir, f"{topic}_plan.md"), "w") as f:
            f.write(f"""# 【验收主题】{topic}

## 1. 本次需求与验收目标

用户完成 {topic}。

## 2. 产品设计依据

- [产品设计](../spec/product.md)

## 3. 验收范围

- 验收 {topic}。

## 4. 验收条件

### AC-01：{topic}完成

- 条件与触发：用户执行 {topic}。
- 预期结果：用户得到 {topic} 的结果。
- 产品设计依据：[产品设计](../spec/product.md)

## 5. 完成判定

- AC-01 通过。

## 6. 上下游文档

- [需求交付追踪表](../traceability.md)
- `../qa/{topic}_plan.md`
""")
        rows.append(
            f"| [产品设计](./spec/product.md) | "
            f"[{topic}](./acceptance/{topic}_plan.md) | "
            f"AC-01：{topic}完成 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |"
        )

    with open(os.path.join(str(tmp_path), "traceability.md"), "w") as f:
        f.write(f"""# 需求交付追踪表

## {workflow_id}

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}
""")
    index_rows = []
    for order, topic in enumerate(topics, start=1):
        index_rows.append(
            f"| {order} | {topic} | 无 | "
            f"[验收计划](./{topic}_plan.md) | [验收结果](./{topic}_result.md) |"
        )
    with open(os.path.join(acceptance_dir, "index.md"), "w") as f:
        f.write(f"""# 验收主题索引

## {workflow_id}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
|---|---|---|---|---|
{chr(10).join(index_rows)}
""")
# 测试 workflow start 无 intent 且无 active Run 时：列出可选意图
def test_start_no_intent_no_run(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 执行 start（不带 --intent）
    code, out, _ = _run(["start"], str(tmp_path))
    # 验证返回码 0
    assert code == 0
    # 验证提示"无可进行中 Run"
    assert "无可进行中 Run" in out
    # 验证列出 from_scratch 意图
    assert "from_scratch" in out
    # 验证列出 product_change 意图
    assert "product_change" in out
    # 验证列出 bugfix 意图
    assert "bugfix" in out


# 测试 workflow start --intent from_scratch 在无过程产物时：直接启动工作流
def test_start_with_intent_from_scratch_no_artifacts(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 执行 start --intent from_scratch
    code, out, _ = _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 验证返回码 0
    assert code == 0
    # 验证输出包含"工作流启动"
    assert "工作流启动" in out
    # 验证输出包含 from_scratch
    assert "from_scratch" in out
    # 验证输出包含 spec（首个 stage）
    assert "spec" in out


# 测试 discuss 在阶段提示词前完整加载全局写作规范
def test_discuss_loads_global_writing_standard_before_stage_docs(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))

    code, out, _ = _run(["discuss"], str(tmp_path))

    assert code == 0
    assert "【全局写作规范】" in out
    assert "能用普通人听得懂的话" in out
    assert out.index("【角色定义】") < out.index("【全局写作规范】")
    assert out.index("【全局写作规范】") < out.index("【流程模版】")
    assert out.index("【流程模版】") < out.index("【流程规范】")


def test_code_design_discuss_prints_product_driven_architecture_rules(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    code, out, _ = _run(["gate", "spec", "--discuss-done"], str(tmp_path))
    assert code == 0, out

    spec_dir = os.path.join(str(tmp_path), "spec")
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "product.md"), "w") as f:
        f.write("# Product\n")
    with open(os.path.join(spec_dir, "feature_example.md"), "w") as f:
        f.write("# 【功能】Example\n")

    code, out, _ = _run(["gate", "spec"], str(tmp_path))
    assert code == 0, out
    code, out, _ = _run(["gate", "spec", "--confirmed"], str(tmp_path))
    assert code == 0, out

    code, out, _ = _run(["discuss"], str(tmp_path))

    assert code == 0
    assert "code_design stage" in out
    assert "代码架构设计师（初步）" in out
    assert "产品设计决定代码设计" in out
    assert "架构图只表达代码分层" in out
    assert "由产品职责推导代码架构" in out
    assert "只列函数名不算完成" in out
    assert "场景B" not in out


def test_discuss_done_records_spec_baseline_once(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))

    code, out, _ = _run(["gate", "spec", "--discuss-done"], str(tmp_path))
    assert code == 0, out
    state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    with open(state_path) as f:
        first = __import__("json").load(f)["stages"]["spec"]

    assert first["artifact_baseline_captured_at"] is not None
    assert first["artifact_baseline_hashes"] == {"spec/product.md": None}

    spec_dir = os.path.join(str(tmp_path), "spec")
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "product.md"), "w") as f:
        f.write("# Product\n")

    code, out, _ = _run(["gate", "spec", "--discuss-done"], str(tmp_path))
    assert code == 0, out
    with open(state_path) as f:
        second = __import__("json").load(f)["stages"]["spec"]

    assert second["artifact_baseline_captured_at"] == first["artifact_baseline_captured_at"]
    assert second["artifact_baseline_hashes"] == first["artifact_baseline_hashes"]


def test_project_design_init_discuss_prints_investigation_and_output_rules(tmp_path):
    _setup_project(tmp_path)
    code, out, _ = _run(["start", "--intent", "product_change"], str(tmp_path))
    assert code == 0, out

    code, out, _ = _run(["discuss"], str(tmp_path))

    assert code == 0
    assert "project_design_init stage" in out
    assert "项目设计初始化调查证据文档模板" in out
    assert "具备安全的本地运行条件时，必须实际运行" in out
    assert "运行确认" in out
    assert "【附加流程模版: Template_Repository/spec/spec.md】" in out
    assert "【附加流程模版: Template_Repository/code_design/code_design.md】" in out
    assert "产品设计文档模板" in out
    assert "代码架构设计文档模板" in out
    assert "一次建立相互一致的产品文档、代码架构文档" in out
    assert "spec/project_design_init_evidence.md" in out


# 测试 workflow start 在已有 active Run 时拒绝再次启动（防止并发 Run 互相覆盖 state）
def test_active_run_guard(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 先启动一次 Run
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 再次尝试启动
    code, out, _ = _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 验证返回码 1（拒绝）
    assert code == 1
    # 验证提示已有进行中 Run
    assert "进行中 Run" in out or "active" in out


# 测试 workflow start --intent from_scratch 在存在过程产物且未 --confirm-clean 时：列出产物但不启动
def test_start_from_scratch_with_artifacts_no_confirm(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 创建 spec 目录
    spec_dir = os.path.join(str(tmp_path), "spec")
    os.makedirs(spec_dir)
    # 写入旧的 product.md
    with open(os.path.join(spec_dir, "product.md"), "w") as f:
        f.write("old product")
    # 清场规则是删除整个命中目录，目录内的其他文件也不会保留
    with open(os.path.join(spec_dir, "user_file.txt"), "w") as f:
        f.write("also removed")
    # 执行 start（不带 --confirm-clean）
    code, out, _ = _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 验证返回码 0
    assert code == 0
    # 验证输出包含"过程产物"提示
    assert "过程产物" in out
    # 验证输出包含 spec
    assert "spec" in out
    assert "删除整个目录及其中全部内容" in out
    assert "不会保留这些目录中的其他文件" in out
    # 验证旧产物未被清理
    assert os.path.exists(os.path.join(spec_dir, "product.md"))
    # 拼出 state.json 路径
    state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    # 验证未启动 Run（state.json 不存在）
    assert not os.path.exists(state_path)


# 测试 workflow start --intent from_scratch --confirm-clean 在存在过程产物时：清理后启动
def test_start_from_scratch_with_artifacts_confirm_clean(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 创建 spec 目录
    spec_dir = os.path.join(str(tmp_path), "spec")
    os.makedirs(spec_dir)
    # 写入旧的 product.md
    with open(os.path.join(spec_dir, "product.md"), "w") as f:
        f.write("old product")
    # 执行 start --confirm-clean
    code, out, _ = _run(["start", "--intent", "from_scratch", "--confirm-clean"], str(tmp_path))
    # 验证返回码 0
    assert code == 0
    # 验证输出包含"工作流启动"
    assert "工作流启动" in out
    # 验证输出包含"已清理"
    assert "已清理" in out
    # 验证旧产物目录被清理
    assert not os.path.exists(spec_dir)


# 测试 workflow abort 在有 active Run 时：作废当前 Run
def test_abort_active_run(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 先启动一个 Run
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 执行 abort
    code, out, _ = _run(["abort"], str(tmp_path))
    # 验证返回码 0
    assert code == 0
    # 验证输出包含"作废"
    assert "作废" in out


# 测试 workflow abort 在无 Run 时：报错（不能凭空 abort）
def test_abort_no_run(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 执行 abort（无 active Run）
    code, out, _ = _run(["abort"], str(tmp_path))
    # 验证返回码 1
    assert code == 1
    # 验证提示还没启动
    assert "还没启动" in out or "aborted" in out or "active" in out


# 测试 workflow done 在 stage 未全部完成时：拒绝收工
def test_done_with_incomplete_stages(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 启动一个 Run（只到 spec stage，后续 stage 未推进）
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 执行 done
    code, out, _ = _run(["done"], str(tmp_path))
    # 验证返回码 1（拒绝）
    assert code == 1
    # 验证提示未完成
    assert "未完成" in out or "completed" in out


# 测试 workflow gate --skip 只能用于 spike stage（其他 stage 不允许跳过）
def test_gate_skip_only_for_spike(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 启动一个 Run
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 对 spec stage 尝试 --skip
    code, out, _ = _run(["gate", "spec", "--skip"], str(tmp_path))
    # 验证返回码 1（拒绝）
    assert code == 1
    # 验证提示 spike（说明 --skip 只允许 spike）
    assert "spike" in out


def test_gate_cannot_skip_spike_before_current_stage(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))

    code, out, _ = _run(["gate", "spike", "--skip"], str(tmp_path))

    assert code == 1
    assert "当前 stage 是 spec" in out
    assert "下一步：" in out
    assert "workflow discuss" in out
    assert "workflow gate spec --discuss-done" in out


def test_gate_rejects_all_normal_operations_for_non_current_stage(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))

    for flags in (["--discuss-done"], [], ["--confirmed"]):
        code, out, _ = _run(["gate", "spike", *flags], str(tmp_path))
        assert code == 1
        assert "当前 stage 是 spec" in out
        assert "不能操作 spike" in out
        assert "下一步：" in out
        assert "workflow discuss" in out
        assert "workflow gate spec --discuss-done" in out


def test_wrong_stage_gate_prints_acceptance_plan_stage_next_step(tmp_path):
    _setup_project(tmp_path)
    _advance_to_spike(tmp_path)
    _run(["gate", "spike", "--skip"], str(tmp_path))

    code, out, _ = _run(["gate", "spike", "--discuss-done"], str(tmp_path))

    assert code == 1
    assert "当前 stage 是 acceptance_plan" in out
    assert "不能操作 spike" in out
    assert "下一步：" in out
    assert "workflow discuss" in out
    assert "workflow gate acceptance_plan --discuss-done" in out


def test_status_refreshes_acceptance_plan_artifact_paths_without_stage_order_change(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    with open(state_path) as f:
        data = __import__("json").load(f)
    data["stages"]["acceptance_plan"]["artifact_paths"] = ["acceptance/"]
    with open(state_path, "w") as f:
        __import__("json").dump(data, f)

    code, out, _ = _run(["status"], str(tmp_path))

    assert code == 0, out
    with open(state_path) as f:
        migrated = __import__("json").load(f)
    assert migrated["stages"]["acceptance_plan"]["artifact_paths"] == [
        "traceability.md",
        "acceptance/index.md",
        "acceptance/",
    ]


def test_acceptance_plan_confirmation_records_topics_and_project_history(tmp_path):
    """Workflow-Test
    主题：验收计划按用户需求生成可判断完成条件
    测试项：TC-01 主题确认后才登记验收主题
    验收条件：AC-01 验收主题在生成主题文档前已经完整确认
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：用户确认验收计划后，当前主题才写入工作流状态和项目主题历史
    测试入口：tests/test_commands.py::test_acceptance_plan_confirmation_records_topics_and_project_history
    代码入口：workflow gate acceptance_plan --confirmed 调用 src/workflow_loop/cli.py 的 cmd_gate()
    """
    _advance_to_spike(tmp_path)
    _run(["gate", "spike", "--skip"], str(tmp_path))
    with open(os.path.join(str(tmp_path), ".workflow_loop", "state.json")) as f:
        workflow_id = __import__("json").load(f)["workflow_id"]
    _write_valid_acceptance_documents(tmp_path, workflow_id, ["上传文件", "查看状态"])

    _run(["gate", "acceptance_plan", "--discuss-done"], str(tmp_path))
    code, out, _ = _run(["gate", "acceptance_plan"], str(tmp_path))
    assert code == 0, out
    code, out, _ = _run(["gate", "acceptance_plan", "--confirmed"], str(tmp_path))
    assert code == 0, out

    with open(os.path.join(str(tmp_path), ".workflow_loop", "state.json")) as f:
        state = __import__("json").load(f)
    with open(os.path.join(str(tmp_path), ".workflow_loop", "project.json")) as f:
        project = __import__("json").load(f)

    assert state["topics"] == ["上传文件", "查看状态"]
    assert state["current_stage"] == "test_plan"
    assert project["topic_history"] == ["上传文件", "查看状态"]


def test_test_plan_gate_runs_and_records_unified_test_entry(tmp_path):
    _setup_project(tmp_path)
    code, out, err = _run(["start", "--intent", "from_scratch"], str(tmp_path))
    assert code == 0, f"start failed: {out} {err}"

    state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    with open(state_path) as f:
        state = json.load(f)
    workflow_id = state["workflow_id"]
    state["current_stage"] = "test_plan"
    state["topics"] = ["上传文件"]
    state["topic"] = "上传文件"
    state["stages"]["test_plan"]["status"] = "in_progress"
    state["stages"]["test_plan"]["artifact_paths"] = ["qa/index.md"]
    state["stages"]["test_plan"]["gate"]["discussion_complete"] = True
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    acceptance_dir = tmp_path / "acceptance"
    acceptance_dir.mkdir()
    (acceptance_dir / "上传文件_plan.md").write_text(
        "# 上传文件验收计划\n\n### AC-01：上传完成\n",
        encoding="utf-8",
    )
    (acceptance_dir / "index.md").write_text(
        f"""# 验收主题索引

## {workflow_id}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
|---|---|---|---|---|
| 1 | 上传文件 | 无 | [验收计划](./上传文件_plan.md) | [验收结果](./上传文件_result.md) |
""",
        encoding="utf-8",
    )
    (qa_dir / "index.md").write_text(
        f"""# 测试计划索引

## {workflow_id}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 测试结果 |
|---|---|---|---|---|---|
| 1 | 上传文件 | 无 | [验收计划](../acceptance/上传文件_plan.md) | [测试计划](./上传文件_plan.md) | [测试结果](./上传文件_result.md) |
""",
        encoding="utf-8",
    )
    (qa_dir / "上传文件_plan.md").write_text(
        f"""# 上传文件测试计划

- 工作流编号：{workflow_id}
- 上游验收计划：[验收计划](../acceptance/上传文件_plan.md)

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：上传完成](../acceptance/上传文件_plan.md#ac-01) | <a id="tc-01"></a>[TC-01 验证上传完成](#tc-01) | 无 | 自动化测试 | 检查上传流程 | 观察到上传完成 | 保留执行证据 |

## 2. 针对性回归范围

暂无

## 3. 测试条件要求

暂无

## 4. 未决测试条件

暂无

## 5. 上下游文档

- 上游验收计划：[验收计划](../acceptance/上传文件_plan.md)
- 下游实施计划：[实施计划](../impl/index.md)
- 下游测试结果：[测试结果](./上传文件_result.md)
""",
        encoding="utf-8",
    )
    (tmp_path / "traceability.md").write_text(
        f"""# 需求交付追踪表

## {workflow_id}

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
| [产品设计](./spec/product.md) | [上传文件](./acceptance/上传文件_plan.md) | AC-01：上传完成 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
""",
        encoding="utf-8",
    )
    entry = tmp_path / "scripts" / "test_all.sh"
    entry.parent.mkdir()
    entry.write_text("#!/usr/bin/env bash\nset -eu\necho all-pass\n", encoding="utf-8")
    entry.chmod(0o755)

    code, out, err = _run(["gate", "test_plan"], str(tmp_path))
    assert code == 0, f"test_plan gate failed: {out} {err}"
    assert "修改前全量测试" in out

    with open(state_path) as f:
        gated_state = json.load(f)
    assert gated_state["test_baseline"]["status"] == "passed"
    assert gated_state["test_baseline"]["exit_code"] == 0
    assert gated_state["stages"]["test_plan"]["gate"]["code_validated"] is True

    code, out, err = _run(["gate", "test_plan", "--confirmed"], str(tmp_path))
    assert code == 0, f"test_plan confirmation failed: {out} {err}"
    with open(state_path) as f:
        confirmed_state = json.load(f)
    assert confirmed_state["current_stage"] == "impl"

    with open(tmp_path / ".workflow_loop" / "journal.jsonl") as f:
        journal = [json.loads(line) for line in f if line.strip()]
    assert any(
        entry["action"] in {"修改前全量测试", "修改前全量测试复用"}
        and entry.get("status") == "passed"
        for entry in journal
    )
    traceability = (tmp_path / "traceability.md").read_text(encoding="utf-8")
    assert "./qa/上传文件_plan.md" in traceability


def test_entering_spike_records_product_and_code_design_baseline(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    _run(["gate", "spec", "--discuss-done"], str(tmp_path))
    spec_dir = os.path.join(str(tmp_path), "spec")
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "product.md"), "w") as f:
        f.write("# Product\n\n[功能](./feature_example.md)\n")
    with open(os.path.join(spec_dir, "feature_example.md"), "w") as f:
        f.write("# 【功能】Example\n")

    _run(["gate", "spec"], str(tmp_path))
    _run(["gate", "spec", "--confirmed"], str(tmp_path))
    _run(["gate", "code_design", "--discuss-done"], str(tmp_path))
    with open(os.path.join(spec_dir, "architecture_code_design.md"), "w") as f:
        f.write("# Architecture\n")
    _run(["gate", "code_design"], str(tmp_path))
    code, out, _ = _run(["gate", "code_design", "--confirmed"], str(tmp_path))
    assert code == 0, out

    with open(os.path.join(str(tmp_path), ".workflow_loop", "state.json")) as f:
        data = __import__("json").load(f)

    assert data["current_stage"] == "spike"
    assert data["spike_baseline"]["captured_at"] is not None
    assert data["spike_baseline"]["product_design_hash"] is not None
    assert data["spike_baseline"]["code_design_hash"] is not None
    assert data["spike_baseline"]["product_design_paths"] == [
        "spec/feature_example.md",
        "spec/product.md",
    ]


def test_impl_discuss_done_requires_loading_impl_materials_first(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))

    state_path = tmp_path / ".workflow_loop" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_stage"] = "impl"
    state["stages"]["impl"]["status"] = "in_progress"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    code, out, _ = _run(["gate", "impl", "--discuss-done"], str(tmp_path))

    assert code == 0
    assert "还没有通过 workflow discuss 加载实施阶段的全部材料" in out
    assert "先调 `workflow discuss`" in out


def test_test_code_discuss_loads_workflow_and_code_development_standards(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))

    state_path = tmp_path / ".workflow_loop" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_stage"] = "test_code"
    state["stages"]["test_code"]["status"] = "in_progress"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    code, out, _ = _run(["gate", "test_code", "--discuss-done"], str(tmp_path))
    assert code == 0
    assert "还没有通过 workflow discuss 加载测试代码阶段的流程规范和代码开发规范" in out

    code, out, err = _run(["discuss"], str(tmp_path))
    assert code == 0, f"discuss failed: {out} {err}"
    assert "【流程规范】" in out
    assert "# 测试代码阶段工作规范" in out
    assert "【代码开发规范: Standardized_Repository/qa/test_code_implementation.md】" in out
    assert "# 测试代码开发规范" in out

    code, out, err = _run(["gate", "test_code", "--discuss-done"], str(tmp_path))
    assert code == 0, f"test_code discuss gate failed: {out} {err}"
    assert "test_code 讨论完毕" in out


def test_impl_discuss_done_accepts_legacy_material_load_record_for_current_workflow(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))

    state_path = tmp_path / ".workflow_loop" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_stage"] = "impl"
    state["stages"]["impl"]["status"] = "in_progress"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    journal_path = tmp_path / ".workflow_loop" / "journal.jsonl"
    legacy_entry = {
        "ts": state["started_at"],
        "action": "提示词加载",
        "actor": "workflow.py",
        "stage": "impl",
        "prompt_doc": "Template_Repository/impl/impl.md",
        "standard_doc": "Standardized_Repository/impl/impl.md",
        "additional_standard_docs": [
            "Standardized_Repository/impl/code_implementation.md"
        ],
    }
    with journal_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(legacy_entry) + "\n")

    code, out, _ = _run(["gate", "impl", "--discuss-done"], str(tmp_path))

    assert code == 0
    assert "还没有通过 workflow discuss 加载实施阶段的全部材料" not in out
    assert "当前工作流还没有确认验收主题" in out


def test_impl_rebaseline_requires_materials_and_records_current_code(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))

    state_path = tmp_path / ".workflow_loop" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_stage"] = "impl"
    state["stages"]["impl"]["status"] = "in_progress"
    state["stages"]["impl"]["code_baseline_hash"] = "old-baseline"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    code, out, _ = _run(["gate", "impl", "--rebaseline"], str(tmp_path))
    assert code == 0
    assert "必须先通过 workflow discuss" in out

    _run(["discuss"], str(tmp_path))
    code, out, err = _run(["gate", "impl", "--rebaseline"], str(tmp_path))
    assert code == 0, f"rebaseline failed: {out} {err}"
    assert "实施前代码基线已重设" in out

    updated_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert updated_state["stages"]["impl"]["code_baseline_hash"] != "old-baseline"
    journal = [
        json.loads(line)
        for line in (tmp_path / ".workflow_loop" / "journal.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert any(
        entry.get("action") == "实施代码基线重设"
        and entry.get("workflow_id") == updated_state["workflow_id"]
        for entry in journal
    )


def test_impl_accept_existing_code_records_hash_and_allows_unchanged_code(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))

    state_path = tmp_path / ".workflow_loop" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_stage"] = "impl"
    state["stages"]["impl"]["status"] = "in_progress"
    state["stages"]["impl"]["gate"]["discussion_complete"] = True
    state["stages"]["impl"]["code_baseline_hash"] = "old-baseline"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    # 该测试只验证状态命令分支；完整实施文档由已有门禁测试覆盖。
    journal_path = tmp_path / ".workflow_loop" / "journal.jsonl"
    journal_path.write_text("", encoding="utf-8")

    code, out, _ = _run(["gate", "impl", "--accept-existing-code"], str(tmp_path))

    assert code == 0
    assert "既有代码确认失败" in out


def test_test_prepare_requires_current_test_execution_materials(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    state_path = tmp_path / ".workflow_loop" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_stage"] = "test_execution"
    state["stages"]["test_execution"]["status"] = "in_progress"
    state["stages"]["test_execution"]["discussion_material_hash"] = None
    state_path.write_text(json.dumps(state), encoding="utf-8")

    code, out, err = _run(
        [
            "test",
            "prepare",
            "--topic",
            "上传文件",
            "--tc",
            "TC-01",
            "--",
            "pytest",
        ],
        str(tmp_path),
    )

    assert code == 0, err
    assert "还没有通过 workflow discuss 加载当前测试执行模板和规范" in out


def test_workflow_return_clears_only_affected_topic_results_and_regression_state(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    workflow_id = json.loads(
        (tmp_path / ".workflow_loop" / "state.json").read_text(encoding="utf-8")
    )["workflow_id"]
    topic = "上传文件"
    _write_valid_acceptance_documents(tmp_path, workflow_id, [topic])
    qa_result = tmp_path / "qa" / f"{topic}_result.md"
    acceptance_result = tmp_path / "acceptance" / f"{topic}_result.md"
    qa_result.parent.mkdir(exist_ok=True)
    qa_result.write_text("old test result", encoding="utf-8")
    acceptance_result.write_text("old acceptance result", encoding="utf-8")

    state_path = tmp_path / ".workflow_loop" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_stage"] = "topic_acceptance"
    state["topics"] = [topic]
    state["stages"]["topic_acceptance"]["status"] = "in_progress"
    state["stages"]["test_execution"]["test_tasks"] = {
        topic: {"TC-01": {"status": "passed", "current_record": {"status": "passed", "exit_code": 0}}}
    }
    state["verification"]["test_result_hash"] = "old-test-result"
    state["verification"]["acceptance_result_hash"] = "old-acceptance-result"
    state["verification"]["regression_test_result_hash"] = "old-regression"
    state["regression_test"] = {"status": "passed", "exit_code": 0}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    code, out, err = _run(
        [
            "return",
            "--to",
            "test_code",
            "--topic",
            topic,
            "--reason",
            "测试代码错误，需要重写后重新执行",
        ],
        str(tmp_path),
    )

    assert code == 0, err
    assert "工作流已退回" in out
    updated = json.loads(state_path.read_text(encoding="utf-8"))
    assert updated["current_stage"] == "test_code"
    assert updated["stages"]["test_execution"]["test_tasks"] == {}
    assert updated["regression_test"]["status"] == "not_run"
    assert updated["verification"]["acceptance_result_hash"] is None
    assert updated["verification"]["regression_test_result_hash"] is None
    assert not qa_result.exists()
    assert not acceptance_result.exists()


def test_spike_discuss_prints_real_uncertainty_rules(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    _run(["gate", "spec", "--discuss-done"], str(tmp_path))
    spec_dir = os.path.join(str(tmp_path), "spec")
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "product.md"), "w") as f:
        f.write("# Product\n\n[功能](./feature_example.md)\n")
    with open(os.path.join(spec_dir, "feature_example.md"), "w") as f:
        f.write("# 【功能】Example\n")
    _run(["gate", "spec"], str(tmp_path))
    _run(["gate", "spec", "--confirmed"], str(tmp_path))
    _run(["gate", "code_design", "--discuss-done"], str(tmp_path))
    with open(os.path.join(spec_dir, "architecture_code_design.md"), "w") as f:
        f.write("# Architecture\n")
    _run(["gate", "code_design"], str(tmp_path))
    _run(["gate", "code_design", "--confirmed"], str(tmp_path))

    code, out, _ = _run(["discuss"], str(tmp_path))

    assert code == 0
    assert "技术不确定性验证工程师" in out
    assert "真实场景" in out
    assert "已经能从现有事实确认的内容不需要穿刺" in out
    assert "spec/spike_index.md" in out


def test_old_spike_state_migrates_artifact_path_even_with_baseline(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    _run(["gate", "spec", "--discuss-done"], str(tmp_path))
    spec_dir = os.path.join(str(tmp_path), "spec")
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "product.md"), "w") as f:
        f.write("# Product\n\n[功能](./feature_example.md)\n")
    with open(os.path.join(spec_dir, "feature_example.md"), "w") as f:
        f.write("# 【功能】Example\n")
    _run(["gate", "spec"], str(tmp_path))
    _run(["gate", "spec", "--confirmed"], str(tmp_path))
    _run(["gate", "code_design", "--discuss-done"], str(tmp_path))
    with open(os.path.join(spec_dir, "architecture_code_design.md"), "w") as f:
        f.write("# Architecture\n")
    _run(["gate", "code_design"], str(tmp_path))
    _run(["gate", "code_design", "--confirmed"], str(tmp_path))

    state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    with open(state_path) as f:
        data = __import__("json").load(f)
    assert data["spike_baseline"]["captured_at"] is not None
    data["stages"]["spike"]["artifact_paths"] = ["spec/"]
    with open(state_path, "w") as f:
        __import__("json").dump(data, f)

    code, out, _ = _run(["gate", "spike", "--discuss-done"], str(tmp_path))

    assert code == 0, out
    assert "['spec/spike_index.md']" in out
    with open(state_path) as f:
        migrated = __import__("json").load(f)
    assert migrated["stages"]["spike"]["artifact_paths"] == ["spec/spike_index.md"]


def test_old_spike_state_marks_missing_baseline_without_using_current_files(tmp_path):
    _advance_to_spike(tmp_path)
    state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    with open(state_path) as f:
        data = __import__("json").load(f)
    data["spike_baseline"] = {
        "captured_at": None,
        "product_design_hash": None,
        "product_design_paths": [],
        "code_design_hash": None,
        "legacy_unavailable": False,
    }
    with open(state_path, "w") as f:
        __import__("json").dump(data, f)

    code, out, _ = _run(["discuss"], str(tmp_path))

    assert code == 0, out
    with open(state_path) as f:
        migrated = __import__("json").load(f)
    assert migrated["spike_baseline"]["captured_at"] is None
    assert migrated["spike_baseline"]["product_design_hash"] is None
    assert migrated["spike_baseline"]["code_design_hash"] is None
    assert migrated["spike_baseline"]["legacy_unavailable"] is True


def test_spike_confirmation_revalidates_documents_after_gate_two(tmp_path):
    workflow_id = _advance_to_spike(tmp_path)
    _write_valid_spike_documents(tmp_path, workflow_id)
    _run(["gate", "spike", "--discuss-done"], str(tmp_path))
    code, out, _ = _run(["gate", "spike"], str(tmp_path))
    assert code == 0, out
    assert "代码校验通过" in out

    for filename in ["spike_index.md", "spike_real_api_response.md"]:
        path = os.path.join(str(tmp_path), "spec", filename)
        with open(path) as f:
            content = f.read()
        with open(path, "w") as f:
            f.write(content.replace("是否阻塞后续：否", "是否阻塞后续：是"))

    code, out, _ = _run(["gate", "spike", "--confirmed"], str(tmp_path))

    assert code == 0
    assert "用户确认前校验失败" in out
    state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    with open(state_path) as f:
        data = __import__("json").load(f)
    assert data["current_stage"] == "spike"
    assert data["stages"]["spike"]["gate"]["code_validated"] is False
    assert data["stages"]["spike"]["gate"]["user_confirmed"] is False


def test_spike_confirmation_cleans_tmp_and_records_journal(tmp_path):
    workflow_id = _advance_to_spike(tmp_path)
    _write_valid_spike_documents(tmp_path, workflow_id)
    spike_tmp = os.path.join(str(tmp_path), ".workflow_loop", "spike_tmp", "api_probe")
    os.makedirs(spike_tmp)
    with open(os.path.join(spike_tmp, "result.json"), "w") as f:
        f.write("{}")
    _run(["gate", "spike", "--discuss-done"], str(tmp_path))
    _run(["gate", "spike"], str(tmp_path))

    code, out, _ = _run(["gate", "spike", "--confirmed"], str(tmp_path))

    assert code == 0, out
    assert not os.path.exists(spike_tmp)
    journal_path = os.path.join(str(tmp_path), ".workflow_loop", "journal.jsonl")
    with open(journal_path) as f:
        journal = f.read()
    assert '"action": "spike 清理"' in journal
    assert '"cleaned_paths": ["api_probe"]' in journal


# 测试 workflow gate 强制顺序：第 2 道闸（code_validated）不能在第 1 道闸（discussion_complete）未过时直接 --confirmed
def test_gate_order_enforced(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 启动一个 Run
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 对 spec stage 直接 --confirmed（跳过 discussion_complete）
    code, out, _ = _run(["gate", "spec", "--confirmed"], str(tmp_path))
    # 验证返回码 1（拒绝）
    assert code == 1
    # 验证提示代码校验或 gate 相关
    assert "代码校验" in out or "code_validated" in out.lower() or "gate" in out.lower()


# 测试 workflow status 输出所有 stage 和架构双阶段标记
def test_status_shows_all_stages(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 启动一个 Run
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 执行 status
    code, out, _ = _run(["status"], str(tmp_path))
    # 验证返回码 0
    assert code == 0
    # 验证输出包含 spec
    assert "spec" in out
    # 验证输出包含 code_design
    assert "code_design" in out
    # 验证输出包含 spike
    assert "spike" in out
    # 验证输出包含 update_code_design（末段 stage）
    assert "update_code_design" in out
    # 验证输出包含 preliminary_done（架构初步完成标记）
    assert "preliminary_done" in out
    # 验证输出包含 detailed_done（架构详细完成标记）
    assert "detailed_done" in out
    # status 必须根据当前门禁状态直接告诉用户下一条命令
    assert "下一步：" in out
    assert "workflow discuss" in out


# 测试重复执行 install-project 不修改已存在的 AGENTS.md（CLI 层的保护逻辑）
def test_repeat_install_no_modify(tmp_path):
    # 初始化项目
    _setup_project(tmp_path)
    # 拼出 AGENTS.md 路径
    agents_path = os.path.join(str(tmp_path), "AGENTS.md")
    # 用户自定义 AGENTS.md 内容
    with open(agents_path, "w") as f:
        f.write("# Custom\n\nUser content.\n")
    # 再次执行 install-project
    code, out, _ = _run(["install-project"], str(tmp_path))
    # 验证返回码 0
    assert code == 0
    # 验证输出提示已经安装或未修改
    assert "已经安装" in out or "未修改" in out
    # 读回 AGENTS.md
    with open(agents_path) as f:
        content = f.read()
    # 验证用户自定义内容保留
    assert "Custom" in content
