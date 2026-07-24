from pathlib import Path

from workflow_loop.bug_record import (
    record_overall_acceptance_pass,
    record_regression_failure,
    record_topic_acceptance_pass,
)


WORKFLOW_ID = "2026-07-24-1200-bugfix"
TOPIC = "上传真实文件后成功完成处理"
BUG_FILE = "2026-07-24_1200-上传失败.md"


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
        tmp_path / "bug" / "index.md",
        f"| 缺陷 | 状态 |\n|---|---|\n| [上传失败](./{BUG_FILE}) | 根因已确认 |\n",
    )
    _write(tmp_path / "impl" / "上传处理实施记录.md", "# 上传处理实施记录\n")
    return original


def test_bug_status_updates_append_results_without_rewriting_reproduction(tmp_path):
    original = _setup(tmp_path)

    record_topic_acceptance_pass(str(tmp_path), WORKFLOW_ID, [TOPIC])
    after_topic = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")
    assert after_topic.startswith(original)
    assert "主题验收通过，待全量回归" in after_topic
    assert "../impl/上传处理实施记录.md" in after_topic
    assert "../qa/上传真实文件后成功完成处理_result.md" in after_topic
    assert "主题验收通过，待全量回归" in (tmp_path / "bug" / "index.md").read_text(encoding="utf-8")

    record_regression_failure(str(tmp_path), WORKFLOW_ID, [TOPIC])
    failed = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")
    assert "回归失败，重新处理中" in failed

    record_overall_acceptance_pass(str(tmp_path), WORKFLOW_ID, [TOPIC])
    closed = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")
    assert "已修复并验收" in closed
    assert "## 1. 缺陷现象" in closed
    assert "## 6. 根因" in closed


def test_bug_status_update_is_idempotent(tmp_path):
    _setup(tmp_path)

    record_topic_acceptance_pass(str(tmp_path), WORKFLOW_ID, [TOPIC])
    first = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")
    record_topic_acceptance_pass(str(tmp_path), WORKFLOW_ID, [TOPIC])
    second = (tmp_path / "bug" / BUG_FILE).read_text(encoding="utf-8")

    assert first == second
