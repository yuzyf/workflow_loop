# 主题：删除文件不再阻塞基线准备
# Workflow-Test: TC-01 删除从未提交文件也放行
# 产品入口：workflow gate impl --prepare-code（实施前基线准备）
# 代码入口：src/workflow_loop/rollback.py::prepare_impl
# 测试入口：tests/test_gate_delete_files.py::test_delete_uncommitted_file_passes_prepare
# 准备数据：进场快照有文件、从未提交 Git、实施中删除
# 执行动作：执行实施前基线准备
# 预期结果（关键断言）：准备成功，回退清单登记无副本
# 预期证据：pytest JUnit XML 报告
import json
import os
import subprocess

from workflow_loop import rollback as rollback_mod
from workflow_loop import state as state_mod


def _build_project_with_snapshot(tmp_path, tracked_content="print('a')\n"):
    """建一个带进场快照的项目：文件存在于快照但工作区已删。"""
    root = str(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)

    victim = os.path.join(root, "victim.py")
    with open(victim, "w", encoding="utf-8") as stream:
        stream.write(tracked_content)
    # victim.py 不提交（从未提交过 Git）
    keeper = os.path.join(root, "keeper.py")
    with open(keeper, "w", encoding="utf-8") as stream:
        stream.write("print('keep')\n")
    subprocess.run(["git", "add", "keeper.py"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)

    # 进场快照：victim.py 存在（content_hash 用真实内容哈希，模拟进场时记录）
    victim_hash = None
    with open(victim, "rb") as stream:
        import hashlib

        victim_hash = hashlib.sha256(stream.read()).hexdigest()
    with open(keeper, "rb") as stream:
        keeper_hash = hashlib.sha256(stream.read()).hexdigest()
    snapshot = {
        "version": 1,
        "files": [
            {"path": "victim.py", "exists": True, "type": "file", "content_hash": victim_hash},
            {"path": "keeper.py", "exists": True, "type": "file", "content_hash": keeper_hash},
        ],
    }
    return root, snapshot


def test_delete_uncommitted_file_passes_prepare(tmp_path):
    """AC-02：删除从未提交的文件，prepare 放行并登记无副本。"""
    root, snapshot = _build_project_with_snapshot(tmp_path)
    # 实施中删除 victim.py
    os.remove(os.path.join(root, "victim.py"))

    wf_state = state_mod.WorkflowState(
        workflow_id="wf-del-1",
        intent="product_change",
        current_stage="impl",
    )
    from workflow_loop.state import GateState, StageState

    stage = StageState()
    stage.gate = GateState()
    stage.gate.discussion_complete = True
    stage.code_baseline_hash = "some-hash"
    wf_state.stages["impl"] = stage
    wf_state.topics = ["主题A"]

    # 计划登记 victim.py：先保存 state（表定位读 state.workflow_id），再写表
    state_mod.save_state(root, wf_state)
    records_dir = os.path.join(root, ".workflow_loop", "records", "wf-del-1")
    os.makedirs(records_dir, exist_ok=True)
    table = {
        "表版本": "4",
        "工作流编号": "wf-del-1",
        "验收主题": "主题A",
        "代码修改计划": [
            {
                "顺序": "1",
                "文件": "victim.py",
                "类、函数或配置项": "新增",
                "当前逻辑": "暂无现有逻辑",
                "计划修改内容": "写文件后删除",
                "数据、状态或输出变化": "文件删除",
                "对应验收条件": "AC-02",
                "前置步骤": "无",
            }
        ],
    }
    with open(
        os.path.join(records_dir, "impl_record_主题A.json"), "w", encoding="utf-8"
    ) as stream:
        json.dump(table, stream, ensure_ascii=False)

    wf_state.meta[rollback_mod.IMPL_COMPLETE_BASELINE_SNAPSHOT_KEY] = snapshot

    summary, _paths = rollback_mod.prepare_impl(root, wf_state)
    assert "完整" in summary, f"prepare 应成功完成：{summary}"
    manifest_path = os.path.join(
        root, rollback_mod._manifest_rel_path(wf_state.workflow_id)
    )
    assert os.path.isfile(manifest_path), "删除从未提交文件时回退清单必须生成"

    with open(manifest_path, encoding="utf-8") as stream:
        manifest = json.load(stream)
    entry = manifest.get("entries", {}).get("victim.py", {})
    assert entry.get("original_exists") is False, "回退清单应登记该文件原本不存在"
    assert entry.get("no_copy_reason"), "无副本原因必须登记"
    assert "Git" in entry["no_copy_reason"] or "无副本" in entry["no_copy_reason"]


def test_deleted_committed_file_uses_git_baseline(tmp_path):
    """AC-01：删除已提交文件时用 Git 提交内容补副本（现有自证路径）。"""
    import hashlib

    root = str(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    victim = os.path.join(root, "victim.py")
    with open(victim, "w", encoding="utf-8") as stream:
        stream.write("print('committed')\n")
    subprocess.run(["git", "add", "victim.py"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)

    # 进场快照记录的哈希 = 提交内容哈希（进场时文件就是 HEAD 内容）
    with open(victim, "rb") as stream:
        content = stream.read()
    entry_hash = hashlib.sha256(content).hexdigest()

    # 实施中删除
    os.remove(victim)

    baseline, detail = rollback_mod._trusted_git_head_baseline(
        root, "victim.py", expected_content_hash=entry_hash
    )
    assert baseline is not None, "删除已提交文件必须能从 HEAD 补副本"
    assert b"committed" in baseline[0]
    assert "两个哈希完全一致" in detail
