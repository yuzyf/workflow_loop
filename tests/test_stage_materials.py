from types import SimpleNamespace

import pytest

from workflow_loop.stage_materials import MaterialError, build_checklist, compute_fingerprint


TOPIC = "用户提出需求后工作流正确开始或继续并逐环节确认"


def _write_global_materials(root):
    global_dir = root / ".workflow_loop" / "Standardized_Repository" / "global"
    global_dir.mkdir(parents=True)
    (global_dir / "document_writing.md").write_text("writing", encoding="utf-8")
    (global_dir / "workflow_lifecycle.md").write_text("lifecycle", encoding="utf-8")


def test_material_checklist_is_ordered_and_contains_absolute_paths(tmp_path):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-05 材料清单和变化失效
    验收条件：AC-05 每个环节先取得正确材料
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：全局规范始终排在环节规范之前并输出可直接读取的绝对路径
    测试入口：tests/test_stage_materials.py::test_material_checklist_is_ordered_and_contains_absolute_paths
    代码入口：workflow_loop.stage_materials.build_checklist
    """
    _write_global_materials(tmp_path)
    stage_file = tmp_path / ".workflow_loop" / "stage.md"
    stage_file.write_text("stage", encoding="utf-8")
    specs = [SimpleNamespace(relative_path="stage.md", purpose="环节规范", missing_note="")]

    checklist = build_checklist(
        str(tmp_path), "impl", {"role": "开发", "description": "实施"}, "写代码", specs
    )

    assert [item.order for item in checklist.materials] == [1, 2, 3]
    assert [item.relative_path for item in checklist.materials] == [
        "Standardized_Repository/global/document_writing.md",
        "Standardized_Repository/global/workflow_lifecycle.md",
        "stage.md",
    ]
    assert all(item.absolute_path.startswith(str(tmp_path)) for item in checklist.materials)
    assert checklist.fingerprint


@pytest.mark.parametrize("invalid_kind", ["missing", "directory", "binary"])
def test_invalid_material_prevents_checklist_registration(tmp_path, invalid_kind):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-05 材料清单和变化失效
    验收条件：AC-05 每个环节先取得正确材料
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：缺失、目录或非 UTF-8 材料不能形成可登记清单
    测试入口：tests/test_stage_materials.py::test_invalid_material_prevents_checklist_registration
    代码入口：workflow_loop.stage_materials.build_checklist
    """
    _write_global_materials(tmp_path)
    path = tmp_path / ".workflow_loop" / "invalid.md"
    if invalid_kind == "directory":
        path.mkdir()
    elif invalid_kind == "binary":
        path.write_bytes(b"\xff\xfe")
    specs = [SimpleNamespace(relative_path="invalid.md", purpose="环节规范", missing_note="")]

    with pytest.raises(MaterialError):
        build_checklist(str(tmp_path), "impl", None, "task", specs)


def test_material_content_change_changes_fingerprint(tmp_path):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-05 材料清单和变化失效
    验收条件：AC-05 每个环节先取得正确材料
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：路径不变但正文变化时材料指纹变化并使旧讨论记录失效
    测试入口：tests/test_stage_materials.py::test_material_content_change_changes_fingerprint
    代码入口：workflow_loop.stage_materials.compute_fingerprint
    """
    _write_global_materials(tmp_path)
    stage_file = tmp_path / ".workflow_loop" / "stage.md"
    stage_file.write_text("before", encoding="utf-8")
    specs = [SimpleNamespace(relative_path="stage.md", purpose="环节规范", missing_note="")]
    before = compute_fingerprint(str(tmp_path), "impl", None, "task", specs)

    stage_file.write_text("after", encoding="utf-8")
    after = compute_fingerprint(str(tmp_path), "impl", None, "task", specs)

    assert after != before
