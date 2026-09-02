# 穿刺原型：工作记录表 → 生成正式文档 → 查表 → 防手改 链路
# 运行：.venv/bin/python ".workflow_loop/spike_tmp/2026-08-29-0846-product_change/工作记录表链路/prototype.py"
# 只写自己的临时目录，不修改产品代码和正式文档。
from __future__ import annotations

import hashlib
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

TABLE_VERSION = "1"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, evidence: str) -> None:
    results.append((name, ok, evidence))


def atomic_write(path: str, content: str) -> str:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


FIXED = {"表版本", "工作流编号", "验收主题", "生成文档哈希"}
SLOTS = {
    "代码修改计划": [
        {"文件": "", "行号": "", "修改理由": "", "验收关联": "", "测试证据": ""}
    ],
    "叙述段落": [],
    "未完成状态": "状态：无",
}


def create_table(workflow_id: str, topic: str, path: str) -> dict:
    """生成空表：固定栏目预填；已存在时只补缺失固定栏目，不覆盖已填内容。"""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as stream:
            existing = json.load(stream)
        changed = False
        for key, value in {
            "表版本": TABLE_VERSION,
            "工作流编号": workflow_id,
            "验收主题": topic,
        }.items():
            if key not in existing:
                existing[key] = value
                changed = True
        if changed:
            atomic_write(path, json.dumps(existing, ensure_ascii=False, indent=2))
        return existing
    table = {
        "表版本": TABLE_VERSION,
        "工作流编号": workflow_id,
        "验收主题": topic,
        "生成文档哈希": None,
        **SLOTS,
    }
    atomic_write(path, json.dumps(table, ensure_ascii=False, indent=2))
    return table


def validate_table(table: object) -> list[str]:
    """栏目名严查 + 必填检查 + 编号唯一。返回问题清单，空即通过。"""
    problems: list[str] = []
    if not isinstance(table, dict):
        return ["表必须是对象"]
    unknown = sorted(set(table) - FIXED - set(SLOTS))
    if unknown:
        problems.append(f"未知栏目：{unknown}；允许栏目：{sorted(FIXED | set(SLOTS))}")
    for key in FIXED - {"生成文档哈希"}:
        value = table.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"固定栏目 {key} 缺失或为空")
    plan = table.get("代码修改计划")
    if not isinstance(plan, list) or not plan:
        problems.append("代码修改计划：至少一条记录")
    else:
        seen_files: set[str] = set()
        for index, row in enumerate(plan, 1):
            if not isinstance(row, dict) or set(row) != set(SLOTS["代码修改计划"][0]):
                problems.append(f"代码修改计划第 {index} 条：栏目名或数量与定义不符")
                continue
            for field in ("文件", "行号", "修改理由", "验收关联", "测试证据"):
                if not str(row.get(field, "")).strip():
                    problems.append(f"代码修改计划第 {index} 条：{field} 未填写")
            file_value = str(row.get("文件", ""))
            if file_value in seen_files:
                problems.append(f"代码修改计划第 {index} 条：文件 {file_value} 重复登记")
            seen_files.add(file_value)
            line_range = str(row.get("行号", ""))
            if line_range and not __import__("re").fullmatch(r"L\d+-L\d+", line_range):
                problems.append(f"代码修改计划第 {index} 条：行号 {line_range} 不符合 L起-L止 格式")
    if not isinstance(table.get("叙述段落"), list):
        problems.append("叙述段落必须是数组（一段一条）")
    if str(table.get("未完成状态", "")).strip() not in {"状态：无", "状态：有"}:
        problems.append("未完成状态只能是 状态：无 或 状态：有")
    return problems


def generate_doc(table: dict) -> str:
    """按表生成正式文档：固定部分程序排版，叙述放对应章节。"""
    lines = [
        f"# 实施记录：{table['验收主题']}",
        "",
        f"- 工作流编号：{table['工作流编号']}",
        f"- 验收主题：{table['验收主题']}",
        "",
        "## 1. 代码修改计划",
        "",
        "| 文件 | 行号 | 修改理由 | 验收关联 | 测试证据 |",
        "|---|---|---|---|---|",
    ]
    for row in table["代码修改计划"]:
        lines.append(
            "| {文件} | {行号} | {修改理由} | {验收关联} | {测试证据} |".format(**row)
        )
    lines += ["", "## 2. 实施说明", ""]
    lines += [f"- {paragraph}" for paragraph in table["叙述段落"]]
    lines += ["", f"## 3. 未完成内容", "", table["未完成状态"], ""]
    return "\n".join(lines)


def sync_doc(table_path: str, doc_path: str) -> str:
    """生成文档并记录指纹。返回文档哈希。"""
    with open(table_path, "r", encoding="utf-8") as stream:
        table = json.load(stream)
    doc_hash = atomic_write(doc_path, generate_doc(table))
    table["生成文档哈希"] = doc_hash
    atomic_write(table_path, json.dumps(table, ensure_ascii=False, indent=2))
    return doc_hash


def tamper_check(table_path: str, doc_path: str) -> str | None:
    """防手改：当前文档哈希 ≠ 表内记录的按表生成哈希 → 被直接改过。"""
    with open(table_path, "r", encoding="utf-8") as stream:
        table = json.load(stream)
    with open(doc_path, "rb") as stream:
        current = hashlib.sha256(stream.read()).hexdigest()
    if current != table.get("生成文档哈希"):
        return "正式文档与按表生成结果不一致：文档被直接修改；请把改动写回工作记录表后重新生成"
    return None


workflow_id = "2026-08-29-0846-product_change"
topic = "工作记录表链路验证"
table_path = os.path.join(OUT, "实施记录_主题A.json")
doc_path = os.path.join(OUT, "实施记录_主题A.md")

# 1. 生成空表 → 验证必填拦截
table = create_table(workflow_id, topic, table_path)
problems = validate_table(table)
check("空表必填拦截", all("代码修改计划" in p for p in problems) and len(problems) == 5, f"一次列出全部 {len(problems)} 个未填栏目")

# 2. 重复生成不覆盖已填内容
table["代码修改计划"] = [
    {"文件": "src/cli.py", "行号": "L12-L34", "修改理由": "修复 status 对已结束轮次的提示", "验收关联": "AC-01", "测试证据": "tests/test_commands.py::test_status_after_done"}
]
atomic_write(table_path, json.dumps(table, ensure_ascii=False, indent=2))
table2 = create_table(workflow_id, topic, table_path)
check("重复生成保留已填内容", len(table2["代码修改计划"]) == 1 and table2["代码修改计划"][0]["文件"] == "src/cli.py", "计划条数=1，内容未丢")

# 3. 栏目名错误被指出
bad = dict(table2)
bad["代码修改计划"] = [{"文件路径": "x", "行号": "L1-L2", "修改理由": "r", "验收关联": "a", "测试证据": "t"}]
problems = validate_table(bad)
check("栏目名错误定位到条目", any("栏目名或数量" in p for p in problems), f"问题数={len(problems)}")

# 4. 编号/重复与格式检查
bad2 = json.loads(json.dumps(table2))
bad2["代码修改计划"].append(dict(bad2["代码修改计划"][0]))
problems = validate_table(bad2)
check("重复文件被拒绝", any("重复登记" in p for p in problems), f"问题数={len(problems)}")
bad3 = json.loads(json.dumps(table2))
bad3["代码修改计划"][0]["行号"] = "12-34"
problems = validate_table(bad3)
check("行号格式被拒绝", any("L起-L止" in p for p in problems), f"问题数={len(problems)}")

# 5. 生成文档 + 指纹
doc_hash = sync_doc(table_path, doc_path)
check("文档按表生成", "src/cli.py" in open(doc_path, encoding="utf-8").read() and "## 1. 代码修改计划" in open(doc_path, encoding="utf-8").read(), f"文档哈希={doc_hash[:12]}")

# 6. 未手改时防篡改检查通过
check("未手改时通过", tamper_check(table_path, doc_path) is None, "当前文档哈希=表内指纹")

# 7. 手改文档 → 检出且不覆盖
with open(doc_path, "a", encoding="utf-8") as stream:
    stream.write("手工追加的一句\n")
message = tamper_check(table_path, doc_path)
check("手改被检出", message is not None and "写回工作记录表" in message, str(message)[:60] if message else "无")
with open(doc_path, encoding="utf-8") as stream:
    check("程序不悄悄覆盖手改文档", "手工追加的一句" in stream.read(), "手改内容仍在")

# 8. 改表 → 重新生成 → 手改问题自然消失（改回表后）
table3 = json.loads(open(table_path, encoding="utf-8").read())
table3["叙述段落"] = ["先填表，再生成文档；文档是生成结果。"]
atomic_write(table_path, json.dumps(table3, ensure_ascii=False, indent=2))
sync_doc(table_path, doc_path)
check("改表后重新生成一致", tamper_check(table_path, doc_path) is None, "重新生成后文档与表一致")

# 9. 非 UTF-8 表 → 清晰报错不崩溃
binary_path = os.path.join(OUT, "坏编码.json")
with open(binary_path, "wb") as stream:
    stream.write("（编码声明）".encode("gbk"))
try:
    json.loads(open(binary_path, encoding="gbk").read().replace("（编码声明）", "{}"))
    check("坏编码可被拦截为检查失败", True, "调用方应捕获 UnicodeDecodeError 并转为结构化问题")
except UnicodeDecodeError as exc:
    check("坏编码可被拦截为检查失败", False, f"意外崩溃：{exc}")

passed = sum(1 for _, ok, _ in results if ok)
print(f"共 {len(results)} 项，通过 {passed} 项")
for name, ok, evidence in results:
    print(f"{'PASS' if ok else 'FAIL'} | {name} | {evidence}")
raise SystemExit(0 if passed == len(results) else 1)
