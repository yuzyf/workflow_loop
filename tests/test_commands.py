import os
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
    assert "已有项目设计初始化提示词" in out
    assert "具备安全的本地运行条件时，必须实际运行" in out
    assert "运行确认" in out
    assert "【附加流程模版: Template_Repository/spec/spec.md】" in out
    assert "【附加流程模版: Template_Repository/code_design/code_design.md】" in out
    assert "产品设计文档模板" in out
    assert "代码架构设计文档模板" in out
    assert "一次建立相互一致的三类设计文档和一份调查证据" in out
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


def test_old_plan_first_state_migrates_to_acceptance_plan_first(tmp_path):
    _setup_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], str(tmp_path))
    state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    with open(state_path) as f:
        data = __import__("json").load(f)

    old_path = [
        "spec", "code_design", "spike", "plan", "acceptance_plan",
        "test_plan", "impl", "test", "acceptance", "update_code_design",
    ]
    old_stages = {}
    for stage_name in old_path:
        old_stages[stage_name] = data["stages"].get(stage_name, {
            "status": "pending",
            "artifact_paths": [],
            "artifact_produced_at": None,
            "gate": {
                "discussion_complete": False,
                "code_validated": False,
                "user_confirmed": False,
            },
        })
    for stage_name in ["spec", "code_design", "spike"]:
        old_stages[stage_name]["status"] = "done"
        old_stages[stage_name]["gate"] = {
            "discussion_complete": True,
            "code_validated": True,
            "user_confirmed": True,
        }
    old_stages["plan"]["status"] = "in_progress"
    old_stages["plan"]["gate"]["discussion_complete"] = True
    data["stage_path"] = old_path
    data["stages"] = old_stages
    data["current_stage"] = "plan"
    with open(state_path, "w") as f:
        __import__("json").dump(data, f)

    code, out, _ = _run(["status"], str(tmp_path))

    assert code == 0
    assert "当前 stage: acceptance_plan" in out
    with open(state_path) as f:
        migrated = __import__("json").load(f)
    assert migrated["stage_path"] == [
        "spec", "code_design", "spike", "acceptance_plan", "test_plan",
        "plan", "topic_execution", "regression_test", "overall_acceptance",
        "update_code_design",
    ]
    assert migrated["stages"]["plan"]["gate"]["discussion_complete"] is False


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
        "acceptance/",
    ]


def test_acceptance_plan_confirmation_records_topics_and_project_history(tmp_path):
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
