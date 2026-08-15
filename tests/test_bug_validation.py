from pathlib import Path

from workflow_loop.artifact_validation import validate_reproduce_documents
from workflow_loop.topic import list_reproduce_topics


TOPIC = "产品和代码设计及缺陷穿刺结论保持真实一致"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _bug_document(root: Path, root_cause: str = "解析器忽略错误码。") -> list[str]:
    _write(
        root / "bug" / "索引.md",
        "# 缺陷索引\n\n| 缺陷 | 状态 |\n| --- | --- |\n| [上传失败](./缺陷_上传失败.md) | 根因已确认 |\n",
    )
    _write(
        root / "bug" / "缺陷_上传失败.md",
        f"""# 【缺陷】上传失败

- 工作流编号：wf
- 复现状态：已复现
- 根因状态：已确认
- 验收主题：上传失败后显示真实错误

## 1. 缺陷现象

上传失败后显示成功。

## 2. 真实复现条件

- 运行环境：macOS 15，Python 3.12
- 真实输入：真实失败响应的脱敏样本，哈希 abc123

## 3. 复现步骤

执行 `workflow upload failing.bin` 并记录退出码和输出。

## 4. 实际结果

退出码为零并显示成功。

## 5. 期望结果

依据产品错误处理规则，应显示真实失败原因并返回非零退出码。

## 6. 根因

- 根因说明：{root_cause}
- 根因位置：`src/workflow_loop/upload.py:42`
- 根因证据：真实响应包含 error.code，但运行输出进入成功分支。

## 7. 修复仍存在的不确定性

无
""",
    )
    return ["bug/索引.md", "bug/缺陷_上传失败.md"]


def test_reproduce_document_requires_real_evidence_root_cause_and_one_topic(tmp_path):
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-04 缺陷使用真实复现和根因证据
    验收条件：AC-04 缺陷依据来自真实复现
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：真实环境输入、实际结果、期望依据、根因位置证据和唯一主题完整时允许登记
    测试入口：tests/test_bug_validation.py::test_reproduce_document_requires_real_evidence_root_cause_and_one_topic
    代码入口：workflow_loop.artifact_validation.validate_reproduce_documents
    """
    changed = _bug_document(tmp_path)

    ok, detail = validate_reproduce_documents(str(tmp_path), changed, "wf")

    assert ok is True, detail
    assert "确定验收主题" in detail


def test_reproduce_document_rejects_unconfirmed_root_cause(tmp_path):
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-04 缺陷使用真实复现和根因证据
    验收条件：AC-04 缺陷依据来自真实复现
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：根因说明为空泛或状态未确认时不能进入修复实施
    测试入口：tests/test_bug_validation.py::test_reproduce_document_rejects_unconfirmed_root_cause
    代码入口：workflow_loop.artifact_validation.validate_reproduce_documents
    """
    changed = _bug_document(tmp_path, root_cause="TODO")

    ok, detail = validate_reproduce_documents(str(tmp_path), changed, "wf")

    assert ok is False
    assert "6. 根因" in detail


def test_reproduce_topic_on_the_next_line_is_not_misread_as_the_next_field(tmp_path):
    """Workflow-Test
    主题：所有阶段门禁失败时一次指出全部真实原因和改法
    测试项：TC-05 缺陷主题空值不吞下一字段
    验收条件：AC-03 格式错误报真实格式和改法
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate reproduce` 的缺陷记录校验
    测试入口：`tests/test_bug_validation.py::test_reproduce_topic_on_the_next_line_is_not_misread_as_the_next_field`
    代码入口：`src/workflow_loop/artifact_validation.py::validate_reproduce_documents`
    准备数据：建立有效缺陷记录，再清空“验收主题”同行值并在下一行写入“别的字段”。
    执行动作：执行缺陷记录校验并读取缺陷主题列表。
    关键断言：输出定位“验收主题”字段并说明同行格式；下一字段不被误作主题，主题列表为空。
    预期证据：结构化报告需精确匹配该测试入口，实际执行数为 1，跳过数、失败数和错误数均为 0；断言需同时证明格式诊断和空主题列表。
    """
    changed = _bug_document(tmp_path)
    record = tmp_path / "bug" / "缺陷_上传失败.md"
    record.write_text(
        record.read_text(encoding="utf-8").replace(
            "- 验收主题：上传失败后显示真实错误",
            "- 验收主题：\n- 别的字段：不该被当成主题",
        ),
        encoding="utf-8",
    )

    ok, detail = validate_reproduce_documents(str(tmp_path), changed, "wf")

    assert ok is False
    assert "验收主题”字段" in detail
    assert "值必须写在标签同一行，下一行内容不会被读取" in detail
    assert list_reproduce_topics(str(tmp_path), "wf") == []
