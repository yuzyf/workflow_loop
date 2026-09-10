# 主题：退回核对无需修改有合法出口
# Workflow-Test: TC-01 声明加依据通过第二道门
# 产品入口：workflow gate spec（第二道门产物变化判定）
# 代码入口：src/workflow_loop/artifact_validation.py::changed_stage_paths
# 测试入口：tests/test_gate_no_change_declaration.py::test_declaration_with_rationale_releases_gate
# 准备数据：product_change 轮次退回 spec 后核对无需修改，表填声明，产物无变化
# 执行动作：调用产物变化判定
# 预期结果（关键断言）：返回通过并标注声明放行
# 预期证据：pytest JUnit XML 报告
import json
import os

from workflow_loop import artifact_validation
from workflow_loop import records as records_mod
from workflow_loop import state as state_mod


def _write_state_with_baseline(root, topics, declaration=None):
    """建一个带 spec 基线和 product_features 表（含声明）的 state。"""
    records_dir = os.path.join(root, ".workflow_loop", "records", "wf-decl-1")
    os.makedirs(records_dir, exist_ok=True)
    # spec 环节的表是轮次级 product_features；R47 声明填在它里面
    features_table = {
        "表版本": "4",
        "工作流编号": "wf-decl-1",
        "验收主题": "",
        "功能": [
            {
                "功能名称": "某功能",
                "一句话说明": "说明内容足够长度的占位文字",
                "对应场景": "修改已有产品",
                "功能文档路径": "./功能_某功能.md",
            }
        ],
        "填写说明": {},
    }
    if declaration is not None:
        features_table["核对结论"] = [declaration]
    with open(
        os.path.join(records_dir, "product_features_product_features.json"),
        "w",
        encoding="utf-8",
    ) as stream:
        json.dump(features_table, stream, ensure_ascii=False)

    internal = os.path.join(root, ".workflow_loop")
    os.makedirs(internal, exist_ok=True)
    # workflow_uses_tables 需要表存在或冻结版本；写 project.json + 冻结版本
    with open(os.path.join(internal, "project.json"), "w", encoding="utf-8") as stream:
        stream.write('{"installer_version": "0.3.9"}\n')

    wf_state = state_mod.WorkflowState(
        workflow_id="wf-decl-1",
        intent="product_change",
        current_stage="spec",
    )
    wf_state.topics = topics
    wf_state.table_format_version = "4"
    from workflow_loop.state import GateState, StageState

    stage = StageState()
    stage.gate = GateState()
    # 产物文件与基线一致（无变化）：基线哈希用文件真实内容哈希
    spec_dir = os.path.join(root, "spec")
    os.makedirs(spec_dir, exist_ok=True)
    overview_path = os.path.join(spec_dir, "产品总说明.md")
    with open(overview_path, "w", encoding="utf-8") as stream:
        stream.write("# 产品总说明\n")
    import hashlib

    with open(overview_path, "rb") as stream:
        real_hash = hashlib.sha256(stream.read()).hexdigest()
    stage.artifact_baseline_captured_at = "2026-09-10T00:00:00+00:00"
    stage.artifact_baseline_hashes = {"spec/产品总说明.md": real_hash}
    wf_state.stages["spec"] = stage

    # 产物文件与基线一致（无变化）
    spec_dir = os.path.join(root, "spec")
    os.makedirs(spec_dir, exist_ok=True)
    with open(os.path.join(spec_dir, "产品总说明.md"), "w", encoding="utf-8") as stream:
        stream.write("# 产品总说明\n")

    state_path = os.path.join(internal, "state.json")
    with open(state_path, "w", encoding="utf-8") as stream:
        json.dump(state_mod.state_to_dict(wf_state), stream, ensure_ascii=False)
    return wf_state


def _declaration_table(rationale):
    return {
        "表版本": "4",
        "工作流编号": "wf-decl-1",
        "验收主题": "主题A",
        "验收条件": [],
        "核对结论": [
            {"核对对象": "产品总说明第 1-9 章与功能文档", "核对依据": rationale}
        ],
        "验收目标说明": ["目标说明占位但足够长度的内容"],
        "需求来源": ["需求来源占位但足够长度的内容"],
        "产品设计依据": ["依据占位但足够长度的内容"],
        "本主题验收": ["范围占位但足够长度的内容"],
        "本主题不验收": ["范围外占位但足够长度的内容"],
        "完成判定": ["判定占位但足够长度的内容"],
    }


def test_declaration_with_rationale_releases_gate(tmp_path):
    """AC-01：声明加有效依据时，产物无变化也放行。"""
    root = str(tmp_path)
    declaration = {"核对对象": "产品总说明第 1-9 章与功能文档", "核对依据": "上游变化只影响测试范围，产品设计的规则和边界未变，逐章核对后确认无需修改"}
    wf_state = _write_state_with_baseline(root, ["主题A"], declaration)

    ok, detail, changed = artifact_validation.changed_stage_paths(
        root, "spec", ["spec/产品总说明.md"]
    )
    assert ok is True, "有效声明时产物无变化也必须放行"
    assert "核对结论：无需修改" in detail
    assert changed == []


def test_declaration_without_rationale_rejected(tmp_path):
    """AC-02：声明缺实质依据时不放行，维持原口径。"""
    root = str(tmp_path)
    declaration = {"核对对象": "产品总说明第 1-9 章与功能文档", "核对依据": "暂无"}
    wf_state = _write_state_with_baseline(root, ["主题A"], declaration)

    ok, detail, changed = artifact_validation.changed_stage_paths(
        root, "spec", ["spec/产品总说明.md"]
    )
    # 表模式下空变化按表判断产出仍返回 True，但 detail 不能是声明放行
    assert "核对结论：无需修改" not in detail, "缺实质依据的声明不能放行"


def test_changed_artifact_ignores_declaration(tmp_path):
    """AC-03：产物实际变化时声明不参与判定，按普通变化输出。"""
    root = str(tmp_path)
    declaration = {"核对对象": "产品总说明第 1-9 章与功能文档", "核对依据": "上游变化只影响测试范围，产品设计的规则和边界未变，逐章核对后确认无需修改"}
    wf_state = _write_state_with_baseline(root, ["主题A"], declaration)

    # 产物文件在基线之后实际被修改（内容变化 → 哈希对不上）
    overview_path = os.path.join(root, "spec", "产品总说明.md")
    with open(overview_path, "w", encoding="utf-8") as stream:
        stream.write("# 产品总说明\n\n本轮实际修改了设计内容。\n")

    ok, detail, changed = artifact_validation.changed_stage_paths(
        root, "spec", ["spec/产品总说明.md"]
    )
    assert ok is True
    assert "本阶段发生变化的文件" in detail, "实际变化必须按普通变化输出"
    assert "核对结论：无需修改" not in detail, "产物有实际变化时声明不能作为放行依据"
    assert "spec/产品总说明.md" in changed, "实际修改的产物必须出现在变化清单"


def test_rationale_substance_check():
    """AC-02：依据实质校验——占位词和短文本不算实质。"""
    assert records_mod.declaration_rationale_has_substance("上游变化不影响产品设计，规则和边界逐章核对确认无需修改")
    assert not records_mod.declaration_rationale_has_substance("暂无")
    assert not records_mod.declaration_rationale_has_substance("")
    assert not records_mod.declaration_rationale_has_substance("无")
    assert not records_mod.declaration_rationale_has_substance("符合预期")


def test_declaration_renders_in_document(tmp_path):
    """AC-04：声明渲染为生成文档的核对记录一节。"""
    table = _declaration_table("设计变更只调整实施细节，产品规则边界不变，核对后确认无需修改产物")
    content = records_mod.generate_document("acceptance_plan", table, project_root=str(tmp_path))
    assert "## 核对记录" in content, "生成文档必须渲染核对记录一节"
    assert "核对对象" in content and "核对依据" in content
    assert "产品总说明第 1-9 章与功能文档" in content

    # 无声明的表不渲染该节
    table.pop("核对结论")
    content = records_mod.generate_document("acceptance_plan", table, project_root=str(tmp_path))
    assert "## 核对记录" not in content, "无声明时不应出现核对记录节"
