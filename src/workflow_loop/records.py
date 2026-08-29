"""工作记录表：机器事实的填空表、校验和正式文档生成。

表保存在 .workflow_loop/records/<workflow_id>/ 下，是程序要核对的固定事实的
唯一真本；正式文档由本模块按表生成，产物目录中只出现正式文档。
表路径按"表文件是否存在"分流：没有表的旧轮次继续走原有文档校验。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile

from . import artifact_paths as artifact_paths_mod
from . import state as state_mod
from .topic import topic_file_key


RECORDS_ROOT = ".workflow_loop/records"
TABLE_FORMAT_VERSION = "1"

NARRATIVE_KEY = "叙述段落"
DOC_HASH_KEY = "生成文档哈希"
GENERATED_DOC_PATH_KEY = "生成文档路径"

LINE_RANGE_RE = re.compile(r"L\d+-L\d+")

# 每类表的定义：栏目、行清单、枚举和文档章节。
# kind 是稳定程序标识；row_list 的 key_column 用于编号唯一性检查。
KIND_SCHEMAS: dict[str, dict] = {
    # 实施记录：代码计划 + 代码结果，生成文档保持旧结构以便三方改动核对继续解析
    "impl_record": {
        "doc_name": "实施记录",
        "row_lists": {
            "代码修改计划": {
                "columns": ["文件", "计划修改内容", "对应验收条件"],
                "key_column": "文件",
                "required_at_gate": True,
            },
            "实际代码修改": {
                "columns": [
                    "文件",
                    "代码位置（最终文件）",
                    "实际修改的代码逻辑",
                    "数据、状态或输出的实际变化",
                    "修改理由",
                    "对应验收条件",
                    "测试证据",
                ],
                "key_column": "文件",
                "required_at_gate": True,
                "line_range_column": "代码位置（最终文件）",
            },
        },
        "narrative": ["实施动作记录", "实施中问题与处理"],
        "enums": {"未完成状态": ["状态：无", "状态：有"]},
    },
    "test_plan": {
        "doc_name": "测试计划",
        "row_lists": {
            "测试项": {
                "columns": [
                    "测试项编号",
                    "命令参数数组",
                    "工作目录",
                    "超时秒数",
                    "报告适配器",
                    "正式目标名称",
                    "对应验收条件",
                ],
                "optional_columns": ["工作目录"],
                "key_column": "测试项编号",
                "required_at_gate": False,
            },
        },
        "narrative": ["测试范围说明"],
        "enums": {},
    },
    "acceptance_plan": {
        "doc_name": "验收计划",
        "row_lists": {
            "验收条件": {
                "columns": [
                    "验收条件编号",
                    "开始前状态",
                    "触发动作",
                    "可检查结果",
                    "通过标准",
                    "不通过标准",
                    "产品设计依据",
                ],
                "key_column": "验收条件编号",
                "required_at_gate": True,
            },
        },
        "narrative": ["验收目标说明"],
        "enums": {},
    },
    "spike_conclusion": {
        "doc_name": "穿刺结论",
        "row_lists": {
            "穿刺项": {
                "columns": [
                    "穿刺项编号",
                    "真实场景",
                    "验证方法与命令",
                    "实际观察结果",
                    "结论",
                ],
                "key_column": "穿刺项编号",
                "required_at_gate": True,
            },
        },
        "narrative": ["结论说明"],
        "enums": {},
    },
    "bug_record": {
        "doc_name": "缺陷记录",
        "row_lists": {
            "缺陷信息": {
                "columns": ["缺陷编号", "现象", "复现步骤", "预期行为", "根因"],
                "key_column": "缺陷编号",
                "required_at_gate": True,
            },
        },
        "narrative": ["缺陷说明"],
        "enums": {},
    },
    "design_sync": {
        "doc_name": "最终设计同步结论",
        "row_lists": {
            "核对项": {
                "columns": ["核对项", "核对结论", "设计影响", "代码影响"],
                "key_column": "核对项",
                "required_at_gate": True,
            },
        },
        "narrative": ["同步说明"],
        "enums": {},
    },
    "product_features": {
        "doc_name": "产品功能清单",
        "row_lists": {
            "功能": {
                "columns": ["功能名称", "一句话说明", "对应场景", "功能文档路径"],
                "key_column": "功能名称",
                "required_at_gate": True,
            },
        },
        "narrative": [],
        "enums": {},
    },
    "test_result": {
        "doc_name": "测试结果",
        "row_lists": {
            "测试结果": {
                "columns": ["测试项编号", "执行结论", "机器记录编号", "实际结果说明"],
                "optional_columns": ["机器记录编号"],
                "key_column": "测试项编号",
                "required_at_gate": False,
            },
        },
        "narrative": ["结果说明"],
        "enums": {},
    },
    "acceptance_result": {
        "doc_name": "验收结果",
        "row_lists": {
            "验收结果": {
                "columns": ["验收条件编号", "验收结论", "实际观察结果", "证据"],
                "key_column": "验收条件编号",
                "required_at_gate": True,
            },
        },
        "narrative": ["验收说明"],
        "enums": {},
    },
}

COLUMN_HINTS: dict[str, dict[str, str]] = {
    "代码修改计划": {
        "文件": "项目内相对路径，例如 src/cli.py",
        "计划修改内容": "一句话写清这一处要改什么，例如 修复已完成轮次的 status 提示",
        "对应验收条件": "本主题的验收条件编号，例如 AC-01、AC-02",
    },
    "实际代码修改": {
        "文件": "实际修改文件的项目内相对路径，例如 src/cli.py",
        "代码位置（最终文件）": "最终文件的行号范围，例如 L12-L34",
        "实际修改的代码逻辑": "改了什么逻辑，例如 状态判断改为先看 run_status",
        "数据、状态或输出的实际变化": "用户可见或程序可见的实际变化",
        "修改理由": "为什么改，例如 修复提示死路",
        "对应验收条件": "例如 AC-01",
        "测试证据": "覆盖它的测试，例如 tests/test_records.py",
    },
    "测试项": {
        "测试项编号": "主题内唯一，例如 TC-01",
        "命令参数数组": "JSON 数组，例如 [\"pytest\", \"tests/test_a.py\"]",
        "工作目录": "项目内相对路径；留空表示项目根",
        "超时秒数": "整数，例如 600",
        "报告适配器": "pytest-junitxml 或 vitest-junitxml",
        "正式目标名称": "测试报告里的正式目标名",
        "对应验收条件": "例如 AC-01",
    },
    "测试结果": {
        "测试项编号": "与测试计划表一致，例如 TC-01",
        "执行结论": "passed 或 failed",
        "机器记录编号": "留空，由程序从机器记录回填，不要手填",
        "实际结果说明": "一段话写清实际观察",
    },
    "验收条件": {
        "验收条件编号": "主题内唯一，例如 AC-01",
        "开始前状态": "执行前可核实的状态",
        "触发动作": "谁通过哪个入口做什么",
        "可检查结果": "到哪里检查什么",
        "通过标准": "哪些结果同时成立才通过",
        "不通过标准": "出现什么就不通过",
        "产品设计依据": "设计文档和章节",
    },
    "验收结果": {
        "验收条件编号": "与验收计划表一致，例如 AC-01",
        "验收结论": "passed、failed 或 blocked",
        "实际观察结果": "实际看到什么",
        "证据": "可复核的证据说明",
    },
    "穿刺项": {
        "穿刺项编号": "例如 SP-001",
        "真实场景": "产品实际遇到的场景",
        "验证方法与命令": "真实执行的命令",
        "实际观察结果": "关键原始输出或测量",
        "结论": "已确认 / 限制已确认 / 仍未确认",
    },
    "缺陷信息": {
        "缺陷编号": "例如 BUG-01",
        "现象": "用户可见的缺陷表现",
        "复现步骤": "可重复的复现路径",
        "预期行为": "按设计应该怎样",
        "根因": "查明的原因",
    },
    "核对项": {
        "核对项": "例如 产品功能与真实代码映射",
        "核对结论": "一致或不一致的说明",
        "设计影响": "需要修改 或 无需修改",
        "代码影响": "需要修改 或 无需修改",
    },
    "功能": {
        "功能名称": "完整中文功能名称",
        "一句话说明": "这个功能帮助用户完成什么",
        "对应场景": "产品总说明中的场景名称",
        "功能文档路径": "例如 ./功能_一次安装.md",
    },
    "主题关系": {
        "验收主题": "完整中文主题名称",
        "前置主题": "直接前置主题，多个用顿号连接；无依赖写 无",
    },
}

NARRATIVE_HINT = "叙述一段存一条；每条一句话到几句话，写给人看的内容"

# 这些表是轮次级（不属于某个验收主题），验收主题栏目允许为空
WORKFLOW_LEVEL_KINDS = {"product_features", "topic_relations", "spike_conclusion", "bug_record", "design_sync"}

FORMAT_CATEGORY = "格式问题"
CONTENT_CATEGORY = "内容问题"

# 断言九/R4：枚举列的合法值（validate_table 逐列校验，不只查非空）
_ENUM_COLUMNS: dict[str, set[str]] = {
    "执行结论": {"passed", "failed"},
    "验收结论": {"passed", "failed", "blocked"},
    "测试方式": {"自动化测试", "人工验收", "自动化测试 + 人工验收"},
}

# 断言九/R4：列的类型约束（validate_table 逐列校验，不只查非空）
_TYPE_COLUMNS: dict[str, str] = {
    "命令参数数组": "json_array",
    "超时秒数": "int",
}


class RecordsError(ValueError):
    """表读取或解析失败；调用方把它转为结构化门禁问题，不能裸崩。"""


def records_dir(project_root: str, workflow_id: str) -> str:
    return os.path.join(project_root, RECORDS_ROOT, workflow_id)


def table_relative_path(project_root: str, workflow_id: str, kind: str, topic: str) -> str:
    file_key = topic_file_key(project_root, topic) if topic else kind
    return f"{RECORDS_ROOT}/{workflow_id}/{kind}_{file_key}.json"


def _schema(kind: str) -> dict:
    if kind not in KIND_SCHEMAS:
        raise RecordsError(f"未知的工作记录表类型：{kind}")
    return KIND_SCHEMAS[kind]


def _fixed_fields(workflow_id: str, topic: str) -> dict[str, str]:
    return {
        "表版本": TABLE_FORMAT_VERSION,
        "工作流编号": workflow_id,
        "验收主题": topic,
        DOC_HASH_KEY: None,
        GENERATED_DOC_PATH_KEY: None,
    }


def create_or_complete_table(
    project_root: str,
    workflow_id: str,
    kind: str,
    topic: str = "",
) -> str:
    """生成空表；表已存在时只补缺失固定栏目，不覆盖已填内容。返回表相对路径。"""
    schema = _schema(kind)
    relative = table_relative_path(project_root, workflow_id, kind, topic)
    full = os.path.join(project_root, relative)
    if os.path.exists(full):
        table = load_table(full)
        changed = False
        for key, value in _fixed_fields(workflow_id, topic).items():
            if key not in table:
                table[key] = value
                changed = True
        for key in schema["row_lists"]:
            if key not in table:
                table[key] = []
                changed = True
        for key in schema["narrative"]:
            if key not in table:
                table[key] = []
                changed = True
        for key in schema["enums"]:
            if key not in table:
                table[key] = schema["enums"][key][0]
                changed = True
        if "填写说明" not in table:
            hints = {}
            for key in schema["row_lists"]:
                hints[key] = {c: COLUMN_HINTS.get(key, {}).get(c, "按栏目含义填写") for c in schema["row_lists"][key]["columns"]}
            for key in schema["narrative"]:
                hints[key] = NARRATIVE_HINT
            table["填写说明"] = hints
            changed = True
        if changed:
            _atomic_write(full, table)
        return relative
    table: dict = _fixed_fields(workflow_id, topic)
    for key in schema["row_lists"]:
        table[key] = []
    for key in schema["narrative"]:
        table[key] = []
    for key in schema["enums"]:
        table[key] = schema["enums"][key][0]
    hints: dict[str, object] = {}
    for key in schema["row_lists"]:
        hints[key] = {c: COLUMN_HINTS.get(key, {}).get(c, "按栏目含义填写") for c in schema["row_lists"][key]["columns"]}
    for key in schema["narrative"]:
        hints[key] = NARRATIVE_HINT
    table["填写说明"] = hints
    os.makedirs(os.path.dirname(full), exist_ok=True)
    _atomic_write(full, table)
    return relative


def _atomic_write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".records-", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def load_table(path: str) -> dict:
    """读取表；坏编码或坏 JSON 转为 RecordsError，不裸崩。"""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except UnicodeDecodeError as exc:
        raise RecordsError(f"工作记录表 {path} 不是合法的 UTF-8 文本：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise RecordsError(f"工作记录表 {path} 不是合法 JSON：{exc}") from exc
    except OSError as exc:
        raise RecordsError(f"工作记录表 {path} 无法读取：{exc}") from exc
    if not isinstance(data, dict):
        raise RecordsError(f"工作记录表 {path} 的顶层必须是对象")
    return data


def table_exists(project_root: str, relative: str) -> bool:
    return os.path.isfile(os.path.join(project_root, relative))


def validate_table(kind: str, table: dict) -> list[tuple[str, str]]:
    """校验一张表，返回 (类别, 问题) 列表；类别为格式问题或内容问题。"""
    schema = _schema(kind)
    problems: list[tuple[str, str]] = []
    allowed = set(schema["row_lists"]) | set(schema["narrative"]) | set(schema["enums"])
    allowed |= {"表版本", "工作流编号", "验收主题", "填写说明", DOC_HASH_KEY, GENERATED_DOC_PATH_KEY}
    unknown = sorted(set(table) - allowed)
    if unknown:
        problems.append((
            FORMAT_CATEGORY,
            f"未知栏目 {unknown}；允许栏目：{sorted(allowed)}",
        ))
    for key in ("表版本", "工作流编号", "验收主题"):
        if kind in WORKFLOW_LEVEL_KINDS and key == "验收主题":
            continue
        value = table.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append((CONTENT_CATEGORY, f"固定栏目 {key} 缺失或为空"))
        elif key == "表版本" and value.strip() != TABLE_FORMAT_VERSION:
            problems.append(
                (CONTENT_CATEGORY, f"固定栏目 表版本 必须是 {TABLE_FORMAT_VERSION}，实际为 {value.strip()!r}")
            )
    for key, definition in schema["row_lists"].items():
        rows = table.get(key)
        if not isinstance(rows, list):
            problems.append((FORMAT_CATEGORY, f"栏目 {key} 必须是行数组"))
            continue
        columns = definition["columns"]
        seen_keys: set[str] = set()
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or set(row) != set(columns):
                problems.append((
                    FORMAT_CATEGORY,
                    f"{key} 第 {index} 行栏目与定义不符；允许栏目：{columns}",
                ))
                continue
            key_value = str(row.get(definition["key_column"], "")).strip()
            if not key_value:
                problems.append((
                    CONTENT_CATEGORY,
                    f"{key} 第 {index} 行的 {definition['key_column']} 未填写",
                ))
            elif key_value in seen_keys:
                problems.append((
                    CONTENT_CATEGORY,
                    f"{key} 第 {index} 行的 {definition['key_column']} {key_value} 重复登记",
                ))
            else:
                seen_keys.add(key_value)
            optional = set(definition.get("optional_columns", ()))
            for column in columns:
                value = str(row.get(column, "")).strip()
                if not value and column in optional:
                    continue
                if not value:
                    problems.append((
                        CONTENT_CATEGORY,
                        f"{key} 第 {index} 行的 {column} 未填写",
                    ))
                    continue
                if column in _ENUM_COLUMNS and value not in _ENUM_COLUMNS[column]:
                    problems.append((
                        CONTENT_CATEGORY,
                        f"{key} 第 {index} 行的 {column} {value!r} 只允许 {'、'.join(sorted(_ENUM_COLUMNS[column]))}",
                    ))
                if column in _TYPE_COLUMNS:
                    _ttype = _TYPE_COLUMNS[column]
                    if _ttype == "json_array":
                        _raw = row.get(column)
                        _parsed = json.loads(_raw) if isinstance(_raw, str) else _raw
                        if not isinstance(_parsed, list):
                            problems.append((
                                CONTENT_CATEGORY,
                                f"{key} 第 {index} 行的 {column} 必须是 JSON 数组，例如 [\"pytest\"]",
                            ))
                    elif _ttype == "int":
                        try:
                            int(value)
                        except ValueError:
                            problems.append((
                                CONTENT_CATEGORY,
                                f"{key} 第 {index} 行的 {column} 必须是整数，例如 600",
                            ))
                if column == definition.get("line_range_column"):
                    bare = value.removeprefix("基线").strip()
                    if (re.match(r"^[Ll][ \t]*[0-9]", bare)
                            and LINE_RANGE_RE.fullmatch(bare) is None):
                        problems.append((
                            CONTENT_CATEGORY,
                            f"{key} 第 {index} 行的 {column} {value!r} 不符合 L起始-L结束 格式，例如 L12-L34",
                        ))
        if definition.get("required_at_gate") and not rows:
            problems.append((CONTENT_CATEGORY, f"栏目 {key} 至少需要一行记录"))
    for key in schema["narrative"]:
        if not isinstance(table.get(key), list):
            problems.append((FORMAT_CATEGORY, f"栏目 {key} 必须是段落数组（一段一条）"))
    for key, allowed_values in schema["enums"].items():
        value = table.get(key)
        if value not in allowed_values:
            problems.append((
                CONTENT_CATEGORY,
                f"栏目 {key} 的值 {value!r} 只允许 {'、'.join(allowed_values)}",
            ))
    return problems


def _md_cell(value) -> str:
    """转义单元格内容里的管道符和换行，避免破坏生成的 Markdown 表格（R3）。"""
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")
    return text


def generate_document(kind: str, table: dict, *, project_root: str = "") -> str:
    """按表生成正式文档；固定部分程序排版，叙述放进对应章节。"""
    schema = _schema(kind)
    topic = str(table.get("验收主题", ""))
    workflow_id = str(table.get("工作流编号", ""))
    lines: list[str] = []
    if kind == "impl_record":
        lines += [
            f"# 实施记录：{topic}",
            "",
            f"- 工作流编号：{workflow_id}",
            f"- 验收主题：{topic}",
            "",
            "## 1. 实施依据",
            "",
            "- 本记录由工作记录表按栏目自动生成；实施依据为已确认的产品设计、验收计划和穿刺结论。",
            "",
            "## 2. 实施前计划",
            "",
            "### 2.2 最低实现设计",
            "",
            "本记录的最低实现设计由代码计划行承载；从零开发的设计说明填在代码修改计划的“计划修改内容”列。",
            "",
            "### 2.3 代码修改计划",
            "",
            "| 文件 | 计划修改内容 | 对应验收条件 |",
            "|---|---|---|",
        ]
        for row in table.get("代码修改计划", []):
            cells = {**{c: "" for c in KIND_SCHEMAS["impl_record"]["row_lists"]["代码修改计划"]["columns"]}, **row}
            cols = KIND_SCHEMAS["impl_record"]["row_lists"]["代码修改计划"]["columns"]
            lines.append("| " + " | ".join(_md_cell(cells[c]) for c in cols) + " |")
        lines += [
            "",
            "### 2.4 未决问题",
            "",
            "暂无",
            "",
            "## 3. 实施后记录",
            "",
            "### 3.1 实施动作记录",
            "",
        ] + [f"- {item}" for item in table.get("实施动作记录", [])]
        lines += [
            "",
            "### 3.2 实施中问题与处理",
            "",
        ] + ([f"- {item}" for item in table.get("实施中问题与处理", [])] or ["- 暂无"])
        lines += [
            "",
            "### 3.3 未完成内容",
            "",
            str(table.get("未完成状态", "状态：无")),
            "",
            "#### 3.4.2 开发检查记录",
            "",
            "- 开发检查记录填在工作记录表的“实施动作记录”叙述栏；此处由程序按表保留位置。",
            "",
            "#### 3.4.1 实际代码修改",
            "",
            "| 文件 | 代码位置（最终文件） | 实际修改的代码逻辑 | 数据、状态或输出的实际变化 | 修改理由 | 对应验收条件 | 测试证据 |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in table.get("实际代码修改", []):
            cells = {**{c: "" for c in KIND_SCHEMAS["impl_record"]["row_lists"]["实际代码修改"]["columns"]}, **row}
            cols = KIND_SCHEMAS["impl_record"]["row_lists"]["实际代码修改"]["columns"]
            lines.append("| " + " | ".join(_md_cell(cells[c]) for c in cols) + " |")
        lines += [
            "",
            "## 4. 上下游文档",
            "",
            "| 关系 | 文档 | 说明 |\n|---|---|---|\n"
            f"| 上游 | [需求交付追踪表](../需求交付追踪表.md) | 本主题的完整交付关系 |\n"
            f"| 全局 | `acceptance/{topic_file_key(project_root, topic)}_验收计划.md` | 本主题验收依据 |\n",
        ]
        return "\n".join(lines)
    if kind == "product_features":
        lines += [
            f"| 功能 | 一句话说明 | 对应场景 | 详细文档 |",
            "|---|---|---|---|",
        ]
        for row in table.get("功能", []):
            doc_path = str(row.get("功能文档路径", ""))
            name = str(row.get("功能名称", ""))
            lines.append(
                f"| {_md_cell(name)} | {_md_cell(row.get('一句话说明', ''))} | {_md_cell(row.get('对应场景', ''))} | [{_md_cell(name)}]({_md_cell(doc_path)}) |"
            )
        return "\n".join(lines)
    # 其余类型：标题 + 编号行 + 行清单表 + 叙述段
    title = f"{schema['doc_name']}：{topic}" if topic else schema["doc_name"]
    lines += [f"# 【工作记录】{title}", "", f"- 工作流编号：{workflow_id}"]
    if kind == "acceptance_result":
        conclusions = [str(r.get("验收结论", "")).strip() for r in table.get("验收结果", [])]
        if conclusions and all(c == "passed" for c in conclusions):
            overall = "通过"
        elif any(c == "failed" for c in conclusions):
            overall = "失败"
        elif any(c == "blocked" for c in conclusions):
            overall = "阻塞"
        else:
            overall = "通过" if not conclusions else "未完成"
        lines.append(f"- 验收结果：{overall}")
    if topic:
        lines.append(f"- 验收主题：{topic}")
    for key, definition in schema["row_lists"].items():
        lines += ["", f"## {key}", ""]
        # R17：为每行产出稳定导航锚点（id 小写、非字母数字替换为-，供跨文档链接跳转）
        for row in table.get(key, []):
            _kid = str(row.get(definition.get("key_column", ""), "")).strip().lower()
            if _kid:
                _safe_id = re.sub(r"[^a-z0-9:-]", "-", _kid)
                lines.append(f'<a id="{_safe_id}"></a>')
        lines += ["", "| " + " | ".join(definition["columns"]) + " |",
                  "|" + "---|" * len(definition["columns"])]
        for row in table.get(key, []):
            lines.append("| " + " | ".join(_md_cell(row.get(c, "")) for c in definition["columns"]) + " |")
    for key in schema["narrative"]:
        lines += ["", f"## {key}", ""] + [f"- {item}" for item in table.get(key, [])]
    return "\n".join(lines)


def sync_documents(
    project_root: str,
    workflow_id: str,
    kind: str,
    topics: list[str],
    *,
    regenerate: bool = True,
) -> tuple[list[tuple[str, str]], list[str]]:
    """校验并按表生成文档。返回 (问题列表, 生成/检查的文档相对路径)。

    问题为 (类别, 描述)；文档生成总是以当前表为准重写，手改内容不会被悄悄
    覆盖——检测到手改时报告问题并跳过重写，由 AI 写回表后再生成。
    """
    problems: list[tuple[str, str]] = []
    documents: list[str] = []
    topics_for_kind = topics or [""]
    for topic in topics_for_kind:
        relative = table_relative_path(project_root, workflow_id, kind, topic)
        full = os.path.join(project_root, relative)
        if not os.path.isfile(full):
            continue
        documents.append(relative)
        try:
            table = load_table(full)
        except RecordsError as exc:
            problems.append((CONTENT_CATEGORY, str(exc)))
            continue
        problems.extend(validate_table(kind, table))
        if any(category == FORMAT_CATEGORY for category, _ in problems):
            continue
        expected_name = _expected_document_path(project_root, kind, topic, table)
        doc_relative = expected_name
        doc_full = os.path.join(project_root, doc_relative)
        current_hash = _file_sha256(doc_full) if os.path.isfile(doc_full) else None
        recorded_hash = table.get(DOC_HASH_KEY)
        if recorded_hash is not None and current_hash != recorded_hash:
            problems.append((
                CONTENT_CATEGORY,
                f"正式文档 {doc_relative} 与工作记录表不一致：文档被直接修改；"
                "请把改动写回工作记录表后重新执行门禁，程序不会悄悄覆盖手改内容",
            ))
            continue
        if regenerate:
            content = generate_document(kind, table, project_root=project_root)
            _write_text(doc_full, content)
            doc_hash = _file_sha256(doc_full)
            table[DOC_HASH_KEY] = doc_hash
            table[GENERATED_DOC_PATH_KEY] = doc_relative
            _atomic_write(full, table)
    return problems, documents


def _expected_document_path(project_root: str, kind: str, topic: str, table: dict) -> str:
    existing = table.get(GENERATED_DOC_PATH_KEY)
    if isinstance(existing, str) and existing:
        # R13：生成文档路径必须落在项目产物目录内，拒绝越出项目的路径（不信任表内任意值）
        _norm = os.path.normpath(existing)
        if not (os.path.isabs(_norm) or _norm.startswith("..") or _norm == ".."):
            return existing
    if kind == "product_features":
        return artifact_paths_mod.PRODUCT_OVERVIEW_DOC
    file_key = topic_file_key(project_root, topic) if topic else kind
    if kind == "impl_record":
        return f"impl/{file_key}_实施记录.md"
    if kind == "test_plan":
        return f"qa/{file_key}_测试计划.md"
    if kind == "test_result":
        return f"qa/{file_key}_测试结果.md"
    if kind == "acceptance_plan":
        return f"acceptance/{file_key}_验收计划.md"
    if kind == "acceptance_result":
        return f"acceptance/{file_key}_验收结果.md"
    return f".workflow_loop/records/{table.get('工作流编号', '')}/{kind}_{file_key}.md"


def _file_sha256(path: str) -> str | None:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _write_text(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".records-doc-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def delete_workflow_records(project_root: str, workflow_id: str) -> list[str]:
    """整轮作废时删除本轮全部工作记录表；返回删除的表相对路径。"""
    directory = records_dir(project_root, workflow_id)
    if not os.path.isdir(directory):
        return []
    removed: list[str] = []
    for root, dirs, files in os.walk(directory, topdown=False):
        for name in sorted(files):
            full = os.path.join(root, name)
            if os.path.isfile(full) or os.path.islink(full):
                os.remove(full)
            rel = os.path.relpath(full, directory).replace(os.sep, "/")
            removed.append(f"{RECORDS_ROOT}/{workflow_id}/{rel}")
        for name in sorted(dirs):
            os.rmdir(os.path.join(root, name))
    if os.path.isdir(directory):
        os.rmdir(directory)
        removed.append(f"{RECORDS_ROOT}/{workflow_id}/")
    return removed


def stage_table_kinds(stage: str) -> tuple[str, ...]:
    mapping = {
        "spec": ("product_features",),
        "spike": ("spike_conclusion",),
        "acceptance_plan": ("acceptance_plan", "topic_relations"),
        "impl": ("impl_record",),
        "qa": ("test_plan", "test_result"),
        "topic_acceptance": ("acceptance_result",),
        "reproduce": ("bug_record",),
        "update_code_design": ("design_sync",),
    }
    return mapping.get(stage, ())


def table_is_filled(table: dict) -> bool:
    """表内是否已经有 AI 填写的内容；空表不启用表路径，保证旧流程兼容。"""
    schema_name = table.get("验收主题")
    for key, value in table.items():
        if key in {"表版本", "工作流编号", "验收主题", DOC_HASH_KEY, GENERATED_DOC_PATH_KEY}:
            continue
        if isinstance(value, list) and value:
            return True
        if key in {"未完成状态"}:
            continue
    _ = schema_name
    return False


def has_any_table(project_root: str, workflow_id: str, stage: str, topics: list[str]) -> bool:
    for kind in stage_table_kinds(stage):
        for topic in topics or [""]:
            relative = table_relative_path(project_root, workflow_id, kind, topic)
            if table_exists(project_root, relative):
                try:
                    table = load_table(os.path.join(project_root, relative))
                except RecordsError:
                    return True
                if table_is_filled(table):
                    return True
    return False


def has_any_table_file(project_root: str, workflow_id: str, stage: str, topics: list[str]) -> bool:
    """本环节是否有任何工作记录表文件（不论是否已填）。

    R11：本轮是否启用表流程以表文件是否存在为准，不以内容是否已填为准；
    空表也属于启用了表流程，门禁报“尚未填写”并停留，不退回文档模式。
    """
    for kind in stage_table_kinds(stage):
        for topic in topics or [""]:
            relative = table_relative_path(project_root, workflow_id, kind, topic)
            if table_exists(project_root, relative):
                return True
    return False


# ── 轮次级主题关系表与索引生成 ─────────────────────────────────────────────

KIND_SCHEMAS["topic_relations"] = {
    "doc_name": "主题关系",
    "row_lists": {
        "主题关系": {
            "columns": ["验收主题", "前置主题"],
            "key_column": "验收主题",
            "required_at_gate": True,
        },
    },
    "narrative": [],
    "enums": {},
}


def _topic_relations_rows(project_root: str, workflow_id: str) -> list[dict]:
    relative = table_relative_path(project_root, workflow_id, "topic_relations", "")
    full = os.path.join(project_root, relative)
    if not os.path.isfile(full):
        return []
    table = load_table(full)
    rows = table.get("主题关系", [])
    return rows if isinstance(rows, list) else []


def ensure_stage_tables(project_root: str, wf_state: state_mod.WorkflowState) -> list[str]:
    """在环节加载材料时为当前环节生成缺失的工作记录表；返回创建的表路径。"""
    from .topic import current_workflow_topics

    stage = wf_state.current_stage
    kinds = stage_table_kinds(stage)
    if not kinds:
        return []
    topics = current_workflow_topics(project_root)
    created: list[str] = []
    for kind in kinds:
        if kind in {"acceptance_plan", "acceptance_result", "impl_record", "test_plan", "test_result"}:
            if not topics:
                continue
            targets = topics
        else:
            targets = [""]
        for topic in targets:
            created.append(create_or_complete_table(project_root, wf_state.workflow_id, kind, topic))
    if created:
        journal_note = {"tables": created}
        from . import journal as journal_mod

        journal_mod.append_entry(
            project_root,
            "工作记录表就绪",
            "workflow.py",
            stage=stage,
            **journal_note,
        )
    return created


def _index_link_columns(stage: str, file_key: str, project_root: str = "") -> str:
    """索引里的文档入口：目标存在时写链接，未生成时写普通路径加（待生成）。"""
    index_dir = {"acceptance": "acceptance", "impl": "impl", "qa": "qa"}[stage]

    def link_or_pending(path: str, label: str) -> str:
        full = os.path.join(project_root, index_dir, os.path.basename(path))
        if os.path.isfile(full):
            return f"[{label}]({path})"
        return f"`./{os.path.basename(path)}`（待生成）"

    if stage == "acceptance":
        return (
            f"{link_or_pending(f'./{file_key}_验收计划.md', file_key + ' 验收计划')} | "
            f"{link_or_pending(f'./{file_key}_验收结果.md', file_key + ' 验收结果')}"
        )
    if stage == "impl":
        return link_or_pending(f"./{file_key}_实施记录.md", file_key + " 实施记录")
    if stage == "qa":
        return (
            f"{link_or_pending(f'./{file_key}_测试计划.md', file_key + ' 测试计划')} | "
            f"{link_or_pending(f'./{file_key}_测试结果.md', file_key + ' 测试结果')}"
        )
    return file_key


def regenerate_index(
    project_root: str,
    workflow_id: str,
    index_relative: str,
    *,
    stage: str,
    result_suffix: str = "",
) -> str | None:
    """按主题关系表重写索引文档中当前工作流的章节；列头与既有索引模板一致。"""
    relations = _topic_relations_rows(project_root, workflow_id)
    if not relations:
        return None
    from .topic import topic_file_key

    spec = {
        "acceptance": {
            "headers": ["展示顺序", "验收主题", "前置主题", "验收计划", "主题验收结果"],
            "columns": lambda key: [
                ("./{k}_验收计划.md".format(k=key), "验收计划", "acceptance"),
                ("./{k}_验收结果.md".format(k=key), "主题验收结果", "acceptance"),
            ],
        },
        "impl": {
            "headers": ["展示顺序", "验收主题", "前置主题", "验收计划", "实施文档"],
            "columns": lambda key: [
                ("../acceptance/{k}_验收计划.md".format(k=key), "验收计划", "acceptance"),
                ("./{k}_实施记录.md".format(k=key), "实施文档", "impl"),
            ],
        },
        "qa": {
            "headers": ["展示顺序", "验收主题", "前置主题", "验收计划", "实施记录", "测试计划", "测试结果"],
            "columns": lambda key: [
                ("../acceptance/{k}_验收计划.md".format(k=key), "验收计划", "acceptance"),
                ("../impl/{k}_实施记录.md".format(k=key), "实施记录", "impl"),
                ("./{k}_测试计划.md".format(k=key), "测试计划", "qa"),
                ("./{k}_测试结果.md".format(k=key), "测试结果", "qa"),
            ],
        },
    }[stage]

    def cell_for(path: str, label: str, kind_dir: str) -> str:
        full = os.path.join(project_root, kind_dir, os.path.basename(path))
        if os.path.isfile(full):
            return f"[{label}]({path})"
        return f"`{path}`（待生成）"

    lines = ["| " + " | ".join(spec["headers"]) + " |", "|" + "---|" * len(spec["headers"])]
    for order, row in enumerate(relations, 1):
        topic = str(row.get("验收主题", "")).strip()
        if not topic:
            continue
        key = topic_file_key(project_root, topic)
        cells = [str(order), topic, str(row.get("前置主题", "") or "无")]
        cells += [cell_for(path, label, kind_dir) for path, label, kind_dir in spec["columns"](key)]
        lines.append("| " + " | ".join(cells) + " |")
    if len(lines) == 2:
        return None
    section = (
        f'\n<a id="{workflow_id}"></a>\n## {workflow_id}\n\n### 主题关系\n\n'
        + "\n".join(lines)
        + "\n"
    )
    full = os.path.join(project_root, index_relative)
    anchor = f'<a id="{workflow_id}"></a>'
    if os.path.isfile(full):
        content = open(full, "r", encoding="utf-8").read()
        pattern = re.compile(
            re.escape(anchor) + r"\n## " + re.escape(workflow_id) + r"\n.*?(?=\n<a id=|\Z)",
            re.DOTALL,
        )
        if pattern.search(content):
            content = pattern.sub(section.strip("\n"), content)
        else:
            content = content.rstrip("\n") + "\n" + section
    else:
        title = {"acceptance": "# 验收主题索引", "impl": "# 实施索引", "qa": "# 测试索引"}[stage]
        content = title + "\n" + section
    _write_text(full, content)
    return index_relative


def regenerate_workflow_indexes(project_root: str, workflow_id: str) -> list[str]:
    """按主题关系表重写 acceptance/impl/qa 三类索引的当前工作流章节。"""
    results = []
    for stage, relative in (
        ("acceptance", "acceptance/索引.md"),
        ("impl", "impl/索引.md"),
        ("qa", "qa/索引.md"),
    ):
        path = regenerate_index(project_root, workflow_id, relative, stage=stage, result_suffix="")
        if path:
            results.append(path)
    return results


def _sync_product_features(project_root: str, workflow_id: str) -> tuple[list[tuple[str, str]], list[str]]:
    """产品功能清单：校验表并把产品总说明的功能清单小节按表重写。"""
    relative = table_relative_path(project_root, workflow_id, "product_features", "")
    full = os.path.join(project_root, relative)
    problems: list[tuple[str, str]] = []
    documents: list[str] = []
    if not os.path.isfile(full):
        return problems, documents
    documents.append(relative)
    table = load_table(full)
    problems.extend(validate_table("product_features", table))
    if any(category == FORMAT_CATEGORY for category, _ in problems):
        return problems, documents
    overview_rel = artifact_paths_mod.PRODUCT_OVERVIEW_DOC
    overview_full = os.path.join(project_root, overview_rel)
    if not os.path.isfile(overview_full):
        problems.append((CONTENT_CATEGORY, f"{overview_rel} 不存在，无法写入功能清单"))
        return problems, documents
    content = open(overview_full, "r", encoding="utf-8").read()
    block = generate_document("product_features", table, project_root=project_root)
    pattern = re.compile(
        r"(## 7\. 产品功能\n)(.*?)(?=\n## 8\. )",
        re.DOTALL,
    )
    if not pattern.search(content):
        problems.append((CONTENT_CATEGORY, f"{overview_rel} 缺少“## 7. 产品功能”章节，无法按表写入功能清单"))
        return problems, documents
    new_content = pattern.sub(lambda match: match.group(1) + "\n" + block + "\n\n", content, count=1)
    section_hash = hashlib.sha256(
        pattern.sub(lambda match: match.group(1) + "\n" + block + "\n\n", content, count=1).encode("utf-8")
    ).hexdigest()
    recorded = table.get(DOC_HASH_KEY)
    current_section = pattern.search(content)
    current_block_hash = hashlib.sha256(
        (current_section.group(1) + current_section.group(2)).encode("utf-8")
    ).hexdigest()
    expected_hash = hashlib.sha256(
        (current_section.group(1) + "\n" + block + "\n\n").encode("utf-8")
    ).hexdigest()
    if recorded is not None and recorded != expected_hash and recorded != section_hash:
        problems.append((
            CONTENT_CATEGORY,
            "产品总说明的功能清单与工作记录表不一致：文档被直接修改；"
            "请把改动写回工作记录表后重新执行门禁，程序不会悄悄覆盖手改内容",
        ))
        return problems, documents
    if current_block_hash != expected_hash:
        _write_text(overview_full, new_content)
    table[DOC_HASH_KEY] = section_hash
    table[GENERATED_DOC_PATH_KEY] = overview_rel
    _atomic_write(full, table)
    return problems, documents


def _test_outcome(record) -> str:
    """从机器记录判定单条测试项结果（R12：据实，不写死通过）。"""
    if record is None:
        return "未执行"
    executed = int(getattr(record, "executed_count", 0) or 0)
    skipped = int(getattr(record, "skipped_count", 0) or 0)
    failed = int(getattr(record, "failed_count", 0) or 0)
    error = int(getattr(record, "error_count", 0) or 0)
    exit_code = getattr(record, "exit_code", None)
    if exit_code == 0 and executed > 0 and skipped == 0 and failed == 0 and error == 0:
        return "通过"
    return "失败"


def generate_test_result_document(
    topic: str,
    table: dict,
    tasks_by_id: dict,
    plan_table: dict | None = None,
) -> str:
    """按结果表和当前机器记录生成测试结果文档；固定事实全部程序写入。"""
    from .artifact_validation import (
        _argv_text,
        _environment_text,
        _output_tail_text,
    )

    workflow_id = str(table.get("工作流编号", ""))
    _outcomes = []
    for _row in table.get("测试结果", []):
        _tid = str(_row.get("测试项编号", "")).strip()
        _task = tasks_by_id.get(_tid)
        _outcomes.append(_test_outcome(_task.current_record if _task is not None else None))
    if _outcomes and all(o == "通过" for o in _outcomes):
        _overall = "通过"
    elif any(o == "失败" for o in _outcomes):
        _overall = "失败"
    else:
        _overall = "未完成" if _outcomes else "通过"
    lines = [
        f"# 测试结果：{topic}",
        "",
        f"- 工作流编号：{workflow_id}",
        f"- 验收主题：{topic}",
        f"- 自动化测试结果：{_overall}",
        "- 人工验收状态：无需人工验收",
        f"- 验收结果：{_overall}",
        "",
        "本文档由程序按测试工作记录表和当前机器记录生成；固定事实不由 AI 手写。",
        "",
        "## 3. 测试项结果",
        "",
    ]
    ac_by_id: dict[str, str] = {}
    for row in (plan_table or {}).get("测试项", []):
        if isinstance(row, dict):
            ac_by_id[str(row.get("测试项编号", "")).strip()] = str(row.get("对应验收条件", "")).strip()
    for row in table.get("测试结果", []):
        test_id = str(row.get("测试项编号", "")).strip()
        task = tasks_by_id.get(test_id)
        record = task.current_record if task is not None else None
        lines += [f"### {test_id}：{str(row.get('实际结果说明', ''))[:40]}", ""]
        if record is None:
            lines += ["- 自动化测试结果：未执行", ""]
            continue
        checks = [
            ("对应验收条件", ac_by_id.get(test_id, "")),
            ("机器记录编号", record.record_id),
            ("工作目录", record.cwd or "项目根"),
            ("测试入口", _argv_text(record.test_entries)),
            ("执行命令", _argv_text(record.command)),
            ("超时（秒）", record.timeout_seconds),
            ("运行环境", _environment_text(record.platform, record.executable)),
            ("开始时间", record.started_at),
            ("结束时间", record.finished_at),
            ("时长（秒）", record.duration_seconds),
            ("退出码", record.exit_code),
            ("输出摘要", _output_tail_text(record.output_tail)),
            ("输出哈希", record.output_sha256),
            ("输出字节数", record.output_bytes),
            ("报告适配器", record.report_adapter),
            ("报告哈希", record.report_hash),
            ("报告字节数", record.report_size),
            ("精确匹配测试入口", _argv_text(record.matched_test_entries or [])),
            ("实际执行数", record.executed_count),
            ("跳过数", record.skipped_count),
            ("失败数", record.failed_count),
            ("错误数", record.error_count),
            ("产品代码哈希", record.code_snapshot_hash),
            ("测试代码哈希", record.test_code_hash),
            ("自动化测试结果", _test_outcome(record)),
            ("实际结果", str(row.get("实际结果说明", ""))),
            ("证据", f"机器记录 {record.record_id}；结构化报告哈希 {record.report_hash}"),
        ]
        for label, value in checks:
            lines.append(f"- {label}：{value}")
        lines.append("")
    return "\n".join(lines)


def sync_stage_tables(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[list[tuple[str, str]], list[str]]:
    """第二道门前同步当前环节的工作记录表：校验、按表生成文档、检测手改。"""
    from .topic import current_workflow_topics

    stage = wf_state.current_stage
    kinds = stage_table_kinds(stage)
    if not kinds:
        return [], []
    topics = list(wf_state.topics) or current_workflow_topics(project_root)
    if not topics:
        # 主题尚未写入 state.topics 时，从 topic_relations 工作记录表读（断言三：表为唯一输入，不靠 state.topics）
        _rel = table_relative_path(project_root, wf_state.workflow_id, "topic_relations", "")
        if table_exists(project_root, _rel):
            _ttable = load_table(os.path.join(project_root, _rel))
            topics = [
                str(r.get("验收主题", "")).strip()
                for r in _ttable.get("主题关系", [])
                if str(r.get("验收主题", "")).strip()
            ]
    if not has_any_table(project_root, wf_state.workflow_id, stage, topics + [""]) and "topic_relations" not in kinds:
        return [], []
    problems: list[tuple[str, str]] = []
    documents: list[str] = []
    for kind in kinds:
        if kind == "product_features":
            kind_problems, kind_docs = _sync_product_features(project_root, wf_state.workflow_id)
            problems.extend(kind_problems)
            documents.extend(kind_docs)
            continue
        if kind in {"acceptance_plan", "acceptance_result", "impl_record", "test_plan", "test_result"}:
            targets = topics or [""]
        else:
            targets = [""]
        for topic in targets:
            relative = table_relative_path(project_root, wf_state.workflow_id, kind, topic)
            if not table_exists(project_root, relative):
                continue
            table = load_table(os.path.join(project_root, relative))
            if kind != "topic_relations" and not table_is_filled(table):
                continue
            documents.append(relative)
            kind_problems = validate_table(kind, table)
            if kind == "topic_relations":
                problems.extend(kind_problems)
                continue
            problems.extend(kind_problems)
            if any(category == FORMAT_CATEGORY for category, _ in kind_problems):
                continue
            if kind == "test_result":
                record_problems = _fill_machine_record_ids(project_root, wf_state, topic, table)
                problems.extend(record_problems)
            if kind == "test_plan" and topic:
                pass
            doc_relative = _expected_document_path(project_root, kind, topic, table)
            doc_full = os.path.join(project_root, doc_relative)
            current_hash = _file_sha256(doc_full) if os.path.isfile(doc_full) else None
            recorded_hash = table.get(DOC_HASH_KEY)
            expected_now = hashlib.sha256(
                generate_document(kind, table, project_root=project_root).encode("utf-8")
            ).hexdigest()
            if current_hash != expected_now:
                # 文档与当前表不一致：可能是手改、表更新或失效删除。
                # 文档缺失或上次生成指纹仍与文档一致 → 表更新或失效删除，正常重新生成；
                # 指纹也对不上 → 文档在生成后被直接修改，报告并保留手改内容。
                if current_hash is not None and recorded_hash is not None and current_hash != recorded_hash:
                    problems.append((
                        CONTENT_CATEGORY,
                        f"正式文档 {doc_relative} 与工作记录表不一致：文档被直接修改；"
                        "请把改动写回工作记录表后重新执行门禁，程序不会悄悄覆盖手改内容",
                    ))
                    continue
            if kind == "test_result" and wf_state.stages.get("qa") is not None:
                tasks_by_id = wf_state.stages["qa"].test_tasks.get(topic, {})
                plan_table = None
                plan_relative = table_relative_path(project_root, wf_state.workflow_id, "test_plan", topic)
                if table_exists(project_root, plan_relative):
                    plan_table = load_table(os.path.join(project_root, plan_relative))
                content = generate_test_result_document(topic, table, tasks_by_id, plan_table)
            else:
                content = generate_document(kind, table, project_root=project_root)
            _write_text(doc_full, content)
            table[DOC_HASH_KEY] = _file_sha256(doc_full)
            table[GENERATED_DOC_PATH_KEY] = doc_relative
            _atomic_write(os.path.join(project_root, relative), table)
    if stage in {"acceptance_plan", "impl", "qa", "topic_acceptance", "update_code_design"}:
        for index_path in regenerate_workflow_indexes(project_root, wf_state.workflow_id):
            documents.append(index_path)
    if stage == "acceptance_plan":
        try:
            from . import traceability as traceability_mod
            if traceability_mod.ensure_workflow_section(project_root, wf_state.workflow_id, topics):
                documents.append("需求交付追踪表.md")
        except Exception:
            pass
    return problems, documents


def _fill_machine_record_ids(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    topic: str,
    table: dict,
) -> list[tuple[str, str]]:
    """测试结果表：机器记录编号由程序从当前机器记录回填，不由 AI 手抄。"""
    problems: list[tuple[str, str]] = []
    stage_state = wf_state.stages.get(wf_state.current_stage)
    topic_tasks = stage_state.test_tasks.get(topic, {}) if stage_state is not None else {}
    for row in table.get("测试结果", []):
        if not isinstance(row, dict):
            continue
        test_id = str(row.get("测试项编号", "")).strip()
        task = topic_tasks.get(test_id)
        if task is not None and task.current_record is not None:
            row["机器记录编号"] = task.current_record.record_id or ""
        else:
            row["机器记录编号"] = ""
            problems.append((
                CONTENT_CATEGORY,
                f"{topic} 的测试项 {test_id} 还没有当前成功机器记录；机器记录编号由程序回填，不能手填",
            ))
    return problems
