from hashlib import sha256
import json
from pathlib import Path

import pytest

from workflow_loop.markdown_links import (
    LinkRepairError,
    apply_legacy_anchor_repairs,
    plan_legacy_anchor_repairs,
    recover_pending_link_repair,
    scan_managed_markdown_links,
    validate_managed_markdown_links,
)


def _source(root: Path, content: str) -> Path:
    path = root / "spec" / "产品总说明.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _target(root: Path, name: str, content: str) -> Path:
    path = root / "spec" / f"功能_{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_scan_uses_markdown_structure_and_accepts_unique_explicit_id(tmp_path):
    _source(
        tmp_path,
        """# 产品

[有效](./功能_目标.md#rule-1)

`[行内代码](./不存在.md)`

```markdown
[代码块](./也不存在.md)
```

[外部](https://example.com/doc#part)
""",
    )
    _target(tmp_path, "目标", '<a id="rule-1"></a>\n## 规则\n')

    result = scan_managed_markdown_links(str(tmp_path))

    assert result.ok
    assert [(link.line, link.href) for link in result.links] == [
        (3, "./功能_目标.md#rule-1")
    ]


def test_scan_aggregates_path_file_and_explicit_id_problems(tmp_path):
    outside = tmp_path.parent / "outside-link.md"
    outside.write_text("# 外部\n", encoding="utf-8")
    _source(
        tmp_path,
        """# 产品
[缺文件](./缺失.md)
[隐式标题](./功能_隐式.md#rule)
[重复编号](./功能_重复.md#dup)
[越界](../../outside-link.md)
[符号链接](./功能_链接.md)
""",
    )
    _target(tmp_path, "隐式", "## Rule\n")
    _target(tmp_path, "重复", '<a id="dup"></a>\n<a id="dup"></a>\n')
    symlink = tmp_path / "spec" / "功能_链接.md"
    symlink.symlink_to(outside)

    result = scan_managed_markdown_links(str(tmp_path))
    ok, detail = validate_managed_markdown_links(str(tmp_path))

    assert not ok
    assert len(result.issues) == 5
    assert [issue.line for issue in result.issues] == [2, 3, 4, 5, 6]
    assert "目标不是现有普通文件" in detail
    assert "缺少完全一致的显式 HTML id" in detail
    assert "显式 HTML id 重复 2 次" in detail
    assert "本地目标越出项目根目录" in detail
    assert "本地目标经过符号链接" in detail
    assert "来源 spec/产品总说明.md:2" in detail


def test_implicit_heading_slug_never_counts_as_explicit_id(tmp_path):
    _source(tmp_path, "[规则](./功能_目标.md#rule)\n")
    _target(tmp_path, "目标", "# Rule\n")

    result = scan_managed_markdown_links(str(tmp_path))

    assert len(result.issues) == 1
    assert result.issues[0].reason == "缺少完全一致的显式 HTML id"


def test_repair_preview_is_read_only_and_apply_adds_unique_anchor(tmp_path):
    _source(tmp_path, "[规则](./功能_目标.md#ac-01)\n")
    target = _target(tmp_path, "目标", "### AC-01：可检查规则\n正文\n")
    before = target.read_bytes()

    plan = plan_legacy_anchor_repairs(str(tmp_path))

    assert target.read_bytes() == before
    assert len(plan.repairs) == 1
    assert not plan.unresolved

    result = apply_legacy_anchor_repairs(str(tmp_path), plan.preview_hash)

    assert result.success
    assert result.repaired_files == ("spec/功能_目标.md",)
    assert target.read_text(encoding="utf-8").startswith(
        '<a id="ac-01"></a>\n### AC-01：可检查规则'
    )
    assert scan_managed_markdown_links(str(tmp_path)).ok


def test_repair_preview_keeps_ambiguous_heading_unresolved(tmp_path):
    _source(tmp_path, "[规则](./功能_目标.md#ac-01)\n")
    _target(tmp_path, "目标", "### AC-01：第一条\n### AC-01：第二条\n")

    plan = plan_legacy_anchor_repairs(str(tmp_path))

    assert not plan.repairs
    assert len(plan.unresolved) == 1


def test_repair_allows_existing_unresolved_issue_line_to_move(tmp_path):
    source = _source(
        tmp_path,
        "[规则](#ac-01)\n\n### AC-01：规则\n\n[仍缺失](./missing.md)\n",
    )
    plan = plan_legacy_anchor_repairs(str(tmp_path))

    result = apply_legacy_anchor_repairs(str(tmp_path), plan)

    assert result.success
    assert '<a id="ac-01"></a>' in source.read_text(encoding="utf-8")
    issues = scan_managed_markdown_links(str(tmp_path)).issues
    assert len(issues) == 1
    assert issues[0].href == "./missing.md"


def test_repair_rejects_preview_drift_before_any_write(tmp_path):
    source = _source(tmp_path, "[规则](./功能_目标.md#ac-01)\n")
    target = _target(tmp_path, "目标", "### AC-01：规则\n")
    plan = plan_legacy_anchor_repairs(str(tmp_path))
    source.write_text(source.read_text(encoding="utf-8") + "补充\n", encoding="utf-8")
    before = target.read_bytes()

    with pytest.raises(LinkRepairError, match="预览已经漂移.*整批零写入"):
        apply_legacy_anchor_repairs(str(tmp_path), plan)

    assert target.read_bytes() == before
    assert not (tmp_path / ".workflow_loop" / "link_repair").exists()


def test_repair_restores_every_file_when_a_replace_fails(tmp_path):
    _source(
        tmp_path,
        "[一](./功能_一.md#ac-01)\n[二](./功能_二.md#ac-02)\n",
    )
    first = _target(tmp_path, "一", "### AC-01：一\n")
    second = _target(tmp_path, "二", "### AC-02：二\n")
    originals = {first: first.read_bytes(), second: second.read_bytes()}
    plan = plan_legacy_anchor_repairs(str(tmp_path))
    calls = 0

    def fail_second(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected replace failure")
        path.write_bytes(content)

    with pytest.raises(LinkRepairError, match="已恢复全部原文"):
        apply_legacy_anchor_repairs(str(tmp_path), plan, replace_file=fail_second)

    assert {path: path.read_bytes() for path in originals} == originals
    assert not (tmp_path / ".workflow_loop" / "link_repair").exists()


def test_repair_restores_original_when_post_write_scan_fails(tmp_path):
    _source(tmp_path, "[规则](./功能_目标.md#ac-01)\n")
    target = _target(tmp_path, "目标", "### AC-01：规则\n")
    before = target.read_bytes()
    plan = plan_legacy_anchor_repairs(str(tmp_path))

    def corrupt_write(path: Path, content: bytes) -> None:
        path.write_text("### AC-01：规则\n", encoding="utf-8")

    with pytest.raises(LinkRepairError, match="已恢复全部原文"):
        apply_legacy_anchor_repairs(str(tmp_path), plan, replace_file=corrupt_write)

    assert target.read_bytes() == before


def test_repair_recovers_before_propagating_keyboard_interrupt(tmp_path):
    _source(tmp_path, "[规则](./功能_目标.md#ac-01)\n")
    target = _target(tmp_path, "目标", "### AC-01：规则\n")
    before = target.read_bytes()
    plan = plan_legacy_anchor_repairs(str(tmp_path))

    def interrupt(path: Path, content: bytes) -> None:
        path.write_bytes(content)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        apply_legacy_anchor_repairs(str(tmp_path), plan, replace_file=interrupt)

    assert target.read_bytes() == before
    assert not (tmp_path / ".workflow_loop" / "link_repair").exists()


def test_recover_pending_transaction_restores_original_idempotently(tmp_path):
    target = _target(tmp_path, "目标", "修改后的内容\n")
    original = "原始内容\n".encode()
    tx_root = tmp_path / ".workflow_loop" / "link_repair"
    backup = tx_root / "backup" / "spec" / "功能_目标.md"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(original)
    (tx_root / "transaction.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "path": "spec/功能_目标.md",
                        "before_hash": sha256(original).hexdigest(),
                        "after_hash": sha256(target.read_bytes()).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    first = recover_pending_link_repair(str(tmp_path))
    second = recover_pending_link_repair(str(tmp_path))

    assert first.success
    assert target.read_bytes() == original
    assert second.success
    assert second.repaired_files == ()
