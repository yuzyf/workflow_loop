import os
import subprocess
import sys
import shutil

# workflow CLI 的安装路径（~/.local/bin/workflow）
WORKFLOW_CMD = os.path.join(os.path.expanduser("~"), ".local", "bin", "workflow")


# 测试辅助函数：在指定 cwd 下执行 workflow 命令，返回 (returncode, stdout, stderr)
def _run(args, cwd):
    # 启动子进程执行 workflow 命令
    result = subprocess.run(
        [WORKFLOW_CMD] + args,
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
    # 执行 start（不带 --confirm-clean）
    code, out, _ = _run(["start", "--intent", "from_scratch"], str(tmp_path))
    # 验证返回码 0
    assert code == 0
    # 验证输出包含"过程产物"提示
    assert "过程产物" in out
    # 验证输出包含 spec
    assert "spec" in out
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
