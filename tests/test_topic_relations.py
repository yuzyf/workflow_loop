from pathlib import Path

import pytest

from workflow_loop.topic_relations import read_topic_index, relation_signature


TOPIC = "验收测试和实施计划按同一主题完整追踪"


def _write_index(root: Path, rows: str) -> str:
    path = root / "acceptance" / "索引.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """# 验收索引

## wf

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 验收结果 |
| --- | --- | --- | --- | --- |
"""
        + rows,
        encoding="utf-8",
    )
    return "acceptance/索引.md"


def _write_topic_docs(root: Path, *topics: str) -> None:
    for topic in topics:
        for suffix in ("验收计划", "验收结果"):
            (root / "acceptance" / f"{topic}_{suffix}.md").write_text(
                f"# {topic}{suffix}\n", encoding="utf-8"
            )


def test_topic_index_reads_unique_ordered_relationships(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-01 验收主题完整唯一且关系无循环
    验收条件：AC-01 验收主题完整且关系唯一
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：读取多个直接前置主题并保留唯一展示顺序
    测试入口：tests/test_topic_relations.py::test_topic_index_reads_unique_ordered_relationships
    代码入口：workflow_loop.topic_relations.read_topic_index
    """
    relative_path = _write_index(
        tmp_path,
        "| 1 | 安装 | 无 | [计划](./安装_验收计划.md) | [结果](./安装_验收结果.md) |\n"
        "| 2 | 设计 | 安装 | [计划](./设计_验收计划.md) | [结果](./设计_验收结果.md) |\n"
        "| 3 | 实施 | 安装、设计 | [计划](./实施_验收计划.md) | [结果](./实施_验收结果.md) |\n",
    )
    _write_topic_docs(tmp_path, "安装", "设计", "实施")

    relations = read_topic_index(str(tmp_path), relative_path, "wf")

    assert relation_signature(relations) == [
        (1, "安装", ()),
        (2, "设计", ("安装",)),
        (3, "实施", ("安装", "设计")),
    ]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            "| 1 | 安装 | 无 | [计划](./安装_验收计划.md) | [结果](./安装_验收结果.md) |\n"
            "| 2 | 安装 | 无 | [计划](./安装_验收计划.md) | [结果](./安装_验收结果.md) |\n",
            "重复验收主题",
        ),
        (
            "| 1 | 安装 | 无 | [计划](./安装_验收计划.md) | [结果](./安装_验收结果.md) |\n"
            "| 2 | 实施 | 不存在 | [计划](./实施_验收计划.md) | [结果](./实施_验收结果.md) |\n",
            "引用了不存在的前置主题",
        ),
        (
            "| 2 | 安装 | 实施 | [计划](./安装_验收计划.md) | [结果](./安装_验收结果.md) |\n"
            "| 1 | 实施 | 安装 | [计划](./实施_验收计划.md) | [结果](./实施_验收结果.md) |\n",
            "必须排在前面",
        ),
    ],
)
def test_topic_index_rejects_ambiguous_or_invalid_graph(tmp_path, rows, message):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-01 验收主题完整唯一且关系无循环
    验收条件：AC-01 验收主题完整且关系唯一
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：拒绝重名、缺失前置和不能形成合法先后顺序的主题关系
    测试入口：tests/test_topic_relations.py::test_topic_index_rejects_ambiguous_or_invalid_graph
    代码入口：workflow_loop.topic_relations.read_topic_index
    """
    relative_path = _write_index(tmp_path, rows)
    _write_topic_docs(tmp_path, "安装", "实施")

    with pytest.raises(ValueError, match=message):
        read_topic_index(str(tmp_path), relative_path, "wf")


def test_topic_index_reports_all_independent_row_errors_once(tmp_path):
    """同一索引中的独立行错误必须一次返回，不能逐次修复再重跑。"""
    relative_path = _write_index(
        tmp_path,
        "| wrong | 安装 | 无 | [计划](./错误_验收计划.md) | `./安装_验收结果.md`（待生成） |\n"
        "| 2 |  | 无 | 不是链接 | `./空主题_验收结果.md`（待生成） |\n",
    )

    with pytest.raises(ValueError) as exc_info:
        read_topic_index(str(tmp_path), relative_path, "wf")

    detail = str(exc_info.value)
    assert "展示顺序必须是整数" in detail
    assert "应指向 ./安装_验收计划.md" in detail
    assert "验收主题不能为空" in detail
    assert "索引单元格必须是单一真实 Markdown 链接" in detail
    assert "主题关系图：未检查" in detail


def test_topic_name_must_match_stable_plan_path(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-01 验收主题完整唯一且关系无循环
    验收条件：AC-01 验收主题完整且关系唯一
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：主题显示名只能链接到由同一稳定文件标识生成的验收计划
    测试入口：tests/test_topic_relations.py::test_topic_name_must_match_stable_plan_path
    代码入口：workflow_loop.topic_relations.read_topic_index
    """
    relative_path = _write_index(
        tmp_path,
        "| 1 | 安装 | 无 | [计划](./另一个主题_验收计划.md) | [结果](./安装_验收结果.md) |\n",
    )

    with pytest.raises(ValueError, match="应指向 ./安装_验收计划.md"):
        read_topic_index(str(tmp_path), relative_path, "wf")


def test_topic_index_accepts_exact_pending_future_path(tmp_path):
    relative_path = _write_index(
        tmp_path,
        "| 1 | 安装 | 无 | [计划](./安装_验收计划.md) | `./安装_验收结果.md`（待生成） |\n",
    )
    (tmp_path / "acceptance" / "安装_验收计划.md").write_text("# 计划\n", encoding="utf-8")

    relation = read_topic_index(str(tmp_path), relative_path, "wf")[0]

    assert relation.links["验收结果"] == "./安装_验收结果.md"


@pytest.mark.parametrize(
    ("result_cell", "message"),
    [
        ("`./错误_验收结果.md`（待生成）", "应指向 ./安装_验收结果.md"),
        ("`./安装_验收结果.md`", "必须是单一真实 Markdown 链接"),
        ("稍后再写", "必须是单一真实 Markdown 链接"),
    ],
)
def test_topic_index_rejects_invalid_future_representation(tmp_path, result_cell, message):
    relative_path = _write_index(
        tmp_path,
        f"| 1 | 安装 | 无 | [计划](./安装_验收计划.md) | {result_cell} |\n",
    )
    (tmp_path / "acceptance" / "安装_验收计划.md").write_text("# 计划\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        read_topic_index(str(tmp_path), relative_path, "wf")


def test_topic_index_rejects_pending_required_acceptance_plan(tmp_path):
    relative_path = _write_index(
        tmp_path,
        "| 1 | 安装 | 无 | `./安装_验收计划.md`（待生成） | `./安装_验收结果.md`（待生成） |\n",
    )

    with pytest.raises(ValueError, match="必须是单一真实 Markdown 链接"):
        read_topic_index(str(tmp_path), relative_path, "wf")


def test_topic_index_rejects_pending_marker_after_target_exists(tmp_path):
    relative_path = _write_index(
        tmp_path,
        "| 1 | 安装 | 无 | [计划](./安装_验收计划.md) | `./安装_验收结果.md`（待生成） |\n",
    )
    _write_topic_docs(tmp_path, "安装")

    with pytest.raises(ValueError, match="目标已经存在"):
        read_topic_index(str(tmp_path), relative_path, "wf")
