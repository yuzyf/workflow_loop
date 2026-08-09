from pathlib import Path

from workflow_loop.artifact_validation import (
    validate_product_design_documents,
    validate_project_design_feature_consistency,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_initialization_documents(tmp_path: Path, workflow_id: str = "test") -> None:
    _write(tmp_path / "src" / "upload.py", "def save_document():\n    return 'saved'\n")
    _write(tmp_path / "src" / "search.py", "def search_documents():\n    return []\n")
    _write(tmp_path / "src" / "legacy.py", "# 已被替代的旧入口\n")
    _write(
        tmp_path / "tests" / "test_upload.py",
        "def test_save_document():\n    assert True\n",
    )
    _write(
        tmp_path / "tests" / "test_search.py",
        "def test_search_documents():\n    assert True\n",
    )
    _write(
        tmp_path / "spec" / "产品总说明.md",
        """# 文档中心 - 产品总说明

## 7. 产品功能

| 功能 | 一句话说明 | 对应场景 | 详细文档 |
|---|---|---|---|
| 上传文档 | 用户上传文档 | 管理资料 | [上传文档](./功能_上传文档.md) |
| 搜索文档 | 用户查找文档 | 查找资料 | [搜索文档](./功能_搜索文档.md) |
""",
    )
    _write(tmp_path / "spec" / "功能_上传文档.md", "# 【功能】上传文档\n")
    _write(tmp_path / "spec" / "功能_搜索文档.md", "# 【功能】搜索文档\n")
    _write(
        tmp_path / "spec" / "代码架构设计.md",
        """# 文档中心 - 代码架构设计

## 6. 各产品功能的代码设计

### 6.1 【功能】上传文档

- 产品依据：[上传文档](./功能_上传文档.md)

| 图中步骤 | 触发和输入 | 代码位置 | 具体处理逻辑 | 产生的状态、数据或输出 | 失败时的结果 | 验证位置 |
|---|---|---|---|---|---|---|
| 保存文档 | 用户提交文档 | `src/upload.py::save_document` | 校验内容后保存 | 返回已保存状态 | 返回具体失败原因 | `tests/test_upload.py::test_save_document` |

### 6.2 【功能】搜索文档

- 产品依据：[搜索文档](./功能_搜索文档.md)

| 图中步骤 | 触发和输入 | 代码位置 | 具体处理逻辑 | 产生的状态、数据或输出 | 失败时的结果 | 验证位置 |
|---|---|---|---|---|---|---|
| 查找文档 | 用户提交关键词 | `src/search.py::search_documents` | 在可见文档中匹配关键词 | 返回匹配列表 | 返回具体失败原因 | `tests/test_search.py::test_search_documents` |
""",
    )
    _write(
        tmp_path / "spec" / "项目设计初始化证据.md",
        f"""# 项目设计初始化调查证据

- 工作流编号：{workflow_id}
- 代码检查状态：已完成
- 初始化范围确认状态：已确认

## 1. 入口清单

| 入口 | 入口类型 | 调查证据 | 功能归属 | 排除理由 | 用户确认 |
|---|---|---|---|---|---|
| 上传页面 | 用户操作入口 | `src/upload.py` | 上传文档 | 暂无 | 已确认 |
| 搜索框 | 用户操作入口 | `src/search.py` | 搜索文档 | 暂无 | 已确认 |
| 旧版导出命令 | 用户操作入口 | `src/legacy.py` | 暂无 | 已被新版替代且当前不可达 | 已确认 |

## 2. 功能清单

| 功能名称 | 独立完成的用户事情 | 覆盖入口 | 用户确认 |
|---|---|---|---|
| 上传文档 | 上传一份文档并看到保存结果 | 上传页面 | 已确认 |
| 搜索文档 | 输入关键词并得到匹配结果 | 搜索框 | 已确认 |

## 3. 产出文件清单

| 预期正式路径 | 所属功能或全局用途 | 实际状态 |
|---|---|---|
| `spec/产品总说明.md` | 全局 | 已生成 |
| `spec/功能_上传文档.md` | 上传文档 | 已生成 |
| `spec/功能_搜索文档.md` | 搜索文档 | 已生成 |
| `spec/代码架构设计.md` | 全局 | 已生成 |
| `spec/项目设计初始化证据.md` | 全局 | 已生成 |

## 4. 已检查代码

| 代码路径 | 检查内容 | 得到的事实 |
|---|---|---|
| `src/upload.py::save_document` | 检查上传入口和保存结果 | 入口返回已保存状态 |
| `src/search.py::search_documents` | 检查搜索入口和返回列表 | 入口返回匹配列表 |

## 5. 测试与运行记录

- 运行条件：具备
- 执行状态：已执行
- 执行结果：通过
- 执行命令：`.venv/bin/python -m pytest tests/test_upload.py tests/test_search.py`
- 结果摘要：上传和搜索两个入口的检查均通过
- 未执行原因：不适用
- 未验证范围：暂无

## 6. 产品与代码设计校准结果

产品总说明、两份功能文档和代码设计均按已确认的上传、搜索入口完成校准；旧版导出命令按不可达事实排除。
""",
    )


def test_four_initialization_feature_sets_must_match_exactly(tmp_path):
    """产品总说明、功能文档、架构和证据使用同一个功能集合。"""
    _write_initialization_documents(tmp_path)

    ok, detail = validate_project_design_feature_consistency(str(tmp_path))

    assert ok is True, detail


def test_initialization_reports_all_independent_scope_and_output_errors(tmp_path):
    """入口无归属、重复功能和漏产出必须在一次校验中全部指出。"""
    _write_initialization_documents(tmp_path)
    evidence = tmp_path / "spec" / "项目设计初始化证据.md"
    content = evidence.read_text(encoding="utf-8")
    content = content.replace(
        "| 搜索框 | 用户操作入口 | `src/search.py` | 搜索文档 | 暂无 | 已确认 |",
        "| 搜索框 | 用户操作入口 | `src/search.py` | 暂无 | 暂无 | 未确认 |",
    )
    content = content.replace(
        "| 搜索文档 | 输入关键词并得到匹配结果 | 搜索框 | 已确认 |",
        "| 上传文档 | 输入关键词并得到匹配结果 | 搜索框 | 未确认 |",
    )
    content = content.replace(
        "| `spec/功能_搜索文档.md` | 搜索文档 | 已生成 |\n",
        "",
    )
    evidence.write_text(content, encoding="utf-8")

    ok, detail = validate_project_design_feature_consistency(str(tmp_path))

    assert ok is False
    assert "搜索框" in detail
    assert "归属" in detail or "排除理由" in detail
    assert "重复" in detail
    assert "搜索文档" in detail
    assert "产出文件清单" in detail


def test_product_documents_reject_internal_references_but_allow_user_files(tmp_path):
    """Workflow-Test
    主题：首次接入已有项目时功能完整且产品文档面向用户
    测试项：TC-03 拒绝明确内部实现且保留用户可见文件
    验收条件：AC-03 产品文档只描述用户能够理解和检查的产品内容
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    产品入口：`workflow gate spec` 提交产品文档，用户核对程序无法确定的语义内容
    测试入口：`tests/test_project_design_init.py::test_product_documents_reject_internal_references_but_allow_user_files`
    代码入口：`src/workflow_loop/artifact_validation.py::validate_product_design_documents`
    准备数据：在隔离项目准备一份功能文档，先写用户上传 `.md` 格式 Markdown 文档、下载图片和查看导入文件；再加入内部路径 `app/api/chat/route.ts`、接口路由 `GET /api/internal/docs`、数据库对象 `documents.source_path` 和类函数 `SyncService.runClearAll`。另准备一句不含确定内部定位、但需要结合产品语境判断的同步描述供用户核对。
    执行动作：自动化部分先提交仅含用户可见文件的文档检查，再提交加入 4 类明确内部引用的文档检查；人工部分读取歧义原句和上下文，记录该句是否属于用户可见产品行为及保留或删除决定。
    关键断言：用户可见 `.md`、Markdown、图片和导入文件描述全部通过；加入内部引用后检查失败，并在同一次输出中逐项出现 `app/api/chat/route.ts`、`GET /api/internal/docs`、`documents.source_path`、`SyncService.runClearAll`；歧义句不因单个技术词自动失败，最终处理与用户记录一致。
    预期证据：`pytest-junitxml` 必须精确匹配本测试入口，实际执行 1 项且跳过、失败、错误均为 0；保存用户文件通过事实、4 个内部引用的同次错误清单、歧义原句与上下文及用户处理决定。
    """
    _write_initialization_documents(tmp_path)
    feature = tmp_path / "spec" / "功能_上传文档.md"
    feature.write_text(
        """# 【功能】上传文档

用户可以上传 `.md` 格式的 Markdown 文档，下载处理后的图片并查看导入文件。
""",
        encoding="utf-8",
    )

    ok, detail = validate_product_design_documents(str(tmp_path))

    assert ok is True, detail

    feature.write_text(
        feature.read_text(encoding="utf-8")
        + "\n内部实现位于 `app/api/chat/route.ts`，使用 `GET /api/internal/docs`，"
        + "读取 `documents.source_path` 并调用 `SyncService.runClearAll`。\n",
        encoding="utf-8",
    )

    ok, detail = validate_product_design_documents(str(tmp_path))

    assert ok is False
    assert "spec/功能_上传文档.md" in detail
    assert "app/api/chat/route.ts" in detail
    assert "GET /api/internal/docs" in detail
    assert "documents.source_path" in detail
    assert "SyncService.runClearAll" in detail
