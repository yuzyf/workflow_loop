from pathlib import Path

from workflow_loop.bug_record import (
    record_overall_acceptance_pass,
    record_regression_failure,
    record_regression_pass,
    record_topic_acceptance_pass,
)


WORKFLOW_ID = "2026-07-24-1200-bugfix"
TOPIC = "上传真实文件后成功完成处理"
BUG_FILE = "缺陷_上传失败.md"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _setup(tmp_path: Path) -> str:
    original = f"""# 【缺陷】上传失败

- 工作流编号：{WORKFLOW_ID}
- 验收主题：{TOPIC}

## 1. 缺陷现象

原始现象。

## 6. 根因

原始根因。
"""
    _write(tmp_path / "bug" / BUG_FILE, original)
    _write(
        tmp_path / "bug" / "索引.md",
        f"| 缺陷 | 状态 |\n|---|---|\n| [上传失败](./{BUG_FILE}) | 根因已确认 |\n",
    )
    _write(tmp_path / "impl" / "上传处理实施记录.md", "# 上传处理实施记录\n")
    return original


def test_topic_acceptance_keeps_bug_open_until_full_regression(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-05 整体验收和缺陷关闭只接受用户决定
    验收条件：AC-05 整体验收由用户决定
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：主题验收通过后只追加结果链接并把缺陷标记为待全量回归
    测试入口：tests/test_bug_record.py::test_topic_acceptance_keeps_bug_open_until_full_regression
    代码入口：src/workflow_loop/bug_record.py 的 record_topic_acceptance_pass()
    """
    original = _setup(tmp_path)

    record_topic_acceptance_pass(str(tmp_path), WORKFLOW_ID, [TOPIC])
    after_topic = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")
    assert after_topic.startswith(original)
    assert "主题验收通过，待全量回归" in after_topic
    assert f"../impl/{TOPIC}_实施记录.md" in after_topic
    assert f"../qa/{TOPIC}_测试结果.md" in after_topic
    assert "主题验收通过，待全量回归" in (tmp_path / "bug" / "索引.md").read_text(encoding="utf-8")


def test_regression_failure_reopens_bug_without_rewriting_reproduction(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-05 整体验收和缺陷关闭只接受用户决定
    验收条件：AC-05 整体验收由用户决定
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：最终全量回归失败后缺陷恢复为处理中，且不能被提前关闭
    测试入口：tests/test_bug_record.py::test_regression_failure_reopens_bug_without_rewriting_reproduction
    代码入口：src/workflow_loop/bug_record.py 的 record_regression_failure()
    """
    original = _setup(tmp_path)

    record_regression_failure(str(tmp_path), WORKFLOW_ID, [TOPIC])
    failed = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")
    assert failed.startswith(original)
    assert "回归失败，重新处理中" in failed


def test_regression_pass_waits_for_overall_acceptance(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-05 整体验收和缺陷关闭只接受用户决定
    验收条件：AC-05 整体验收由用户决定
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：全量回归通过只进入待整体验收状态而不能自行关闭缺陷
    测试入口：tests/test_bug_record.py::test_regression_pass_waits_for_overall_acceptance
    代码入口：workflow_loop.bug_record.record_regression_pass
    """
    original = _setup(tmp_path)

    record_regression_pass(str(tmp_path), WORKFLOW_ID, [TOPIC])

    content = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")
    assert content.startswith(original)
    assert "全量回归通过，待整体验收" in content
    assert "已修复并验收" not in content


def test_overall_acceptance_closes_bug_and_preserves_reproduction(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-05 整体验收和缺陷关闭只接受用户决定
    验收条件：AC-05 整体验收由用户决定
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：整体验收通过后缺陷才关闭，并且原复现事实和根因保持不变
    测试入口：tests/test_bug_record.py::test_overall_acceptance_closes_bug_and_preserves_reproduction
    代码入口：src/workflow_loop/bug_record.py 的 record_overall_acceptance_pass()
    """
    original = _setup(tmp_path)

    record_overall_acceptance_pass(str(tmp_path), WORKFLOW_ID, [TOPIC])
    closed = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")
    assert closed.startswith(original)
    assert "已修复并验收" in closed
    assert "整体验收：用户已确认" in closed
    assert "overall_result.md" not in closed
    assert "## 1. 缺陷现象" in closed
    assert "## 6. 根因" in closed


def test_bug_status_update_is_idempotent(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-05 整体验收和缺陷关闭只接受用户决定
    验收条件：AC-05 整体验收由用户决定
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：同一用户决定重复登记不会重复追加状态或结果链接
    测试入口：tests/test_bug_record.py::test_bug_status_update_is_idempotent
    代码入口：workflow_loop.bug_record.record_topic_acceptance_pass
    """
    _setup(tmp_path)

    record_topic_acceptance_pass(str(tmp_path), WORKFLOW_ID, [TOPIC])
    first = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")
    record_topic_acceptance_pass(str(tmp_path), WORKFLOW_ID, [TOPIC])
    second = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")

    assert first == second
