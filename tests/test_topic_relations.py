import pytest

from workflow_loop.topic_relations import TopicRelation, expand_dependents, read_topic_index


def test_expand_dependents_includes_transitive_dependents_only():
    relations = [
        TopicRelation(1, "上传文件", (), {}),
        TopicRelation(2, "解析文件", ("上传文件",), {}),
        TopicRelation(3, "展示结果", ("解析文件",), {}),
        TopicRelation(4, "查看状态", (), {}),
    ]

    assert expand_dependents(relations, ["上传文件"]) == [
        "上传文件",
        "解析文件",
        "展示结果",
    ]
    assert expand_dependents(relations, ["查看状态"]) == ["查看状态"]


def test_read_topic_index_rejects_invalid_dependency_graph(tmp_path):
    index = tmp_path / "acceptance" / "index.md"
    index.parent.mkdir()
    index.write_text(
        """# 验收主题索引

## test

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
|---|---|---|---|---|
| 1 | 上传文件 | 解析文件 | [计划](./上传文件_plan.md) | [结果](./上传文件_result.md) |
| 2 | 解析文件 | 上传文件 | [计划](./解析文件_plan.md) | [结果](./解析文件_result.md) |
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="必须排在前面|循环"):
        read_topic_index(
            str(tmp_path),
            "acceptance/index.md",
            "test",
            ["展示顺序", "验收主题", "前置主题", "验收计划", "主题验收结果"],
        )
