"""工作记录表功能与出错通道的行为测试。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from workflow_loop import records as records_mod
from workflow_loop import state as state_mod

from test_commands import _install_project, _run


def test_table_create_then_recreate_keeps_filled_content(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    table_path = root / relative
    assert table_path.is_file()
    table = json.loads(table_path.read_text(encoding="utf-8"))
    assert table["工作流编号"] == "wf-1"
    assert table["验收主题"] == "主题A"
    assert table["代码修改计划"] == []

    table["代码修改计划"] = [
        {"文件": "src/a.py", "计划修改内容": "修复提示", "对应验收条件": "AC-01"}
    ]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    reloaded = json.loads(table_path.read_text(encoding="utf-8"))
    assert reloaded["代码修改计划"][0]["文件"] == "src/a.py"


def test_v1_frozen_round_keeps_legacy_schema_and_rendering(tmp_path: Path) -> None:
    """AC-03/R18：冻结版本 1 的轮次按 v1 schema 校验并用旧渲染生成，不报 v2 缺栏位。

Workflow-Test
主题：表栏位补齐模板映射
测试项：TC-03 冻结版本 1 的轮次按旧口径校验渲染
验收条件：AC-03 表版本开工冻结
测试方式：自动化测试
测试层级：单元测试
产品入口：对进行中的旧版本轮次继续执行 workflow gate
测试入口：tests/test_records.py::test_v1_frozen_round_keeps_legacy_schema_and_rendering
代码入口：src/workflow_loop/records.py::_schema
准备数据：构造 table_format_version=1 的轮次与其 v1 工作记录表
执行动作：对该轮次执行表校验与文档生成
关键断言：按 v1 schema 校验并用旧渲染逐字节生成，不报 v2 缺栏位
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    root = tmp_path / "proj"
    root.mkdir()
    (root / "impl").mkdir()
    state = _state_with_stage("wf-old", "impl")
    state.table_format_version = "1"
    # 手工放一张版本 1 的已填表（旧 3 列计划 + 叙述栏实施动作记录）
    relative = records_mod.table_relative_path(str(root), "wf-old", "impl_record", "主题A")
    full = root / relative
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(json.dumps({
        "表版本": "1",
        "工作流编号": "wf-old",
        "验收主题": "主题A",
        "生成文档哈希": None,
        "生成文档路径": None,
        "代码修改计划": [
            {"文件": "src/a.py", "计划修改内容": "在 status_hint 中删除已完成轮次仍提示 done 的分支，改为提示开新一轮", "对应验收条件": "AC-01"}
        ],
        "实际代码修改": [
            {
                "文件": "src/a.py",
                "代码位置（最终文件）": "L10-L20",
                "实际修改的代码逻辑": "status_hint 按 run_status 判定，完成态不再返回旧命令提示",
                "数据、状态或输出的实际变化": "变化",
                "修改理由": "修复",
                "对应验收条件": "AC-01",
                "测试证据": "tests/test_records.py",
            }
        ],
        "实施动作记录": ["修改 src/a.py"],
        "实施中问题与处理": [],
        "未完成状态": "状态：无",
        "填写说明": {},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    problems, documents = records_mod.sync_stage_tables(str(root), state)
    assert problems == [], problems
    content = (root / "impl" / "主题A_实施记录.md").read_text(encoding="utf-8")
    # v1 渲染保持升级前结构（旧轮次文档不重排版、不要求新栏位）
    assert "# 实施记录：主题A" in content


def test_scaffold_migrates_v2_rows_preserving_values(tmp_path: Path) -> None:
    """行迁移：v2 表按 schema 补齐缺失列、剔除未知列，已填值不丢。

Workflow-Test
主题：表栏位补齐模板映射
测试项：TC-01 迁移保留已填值的补齐骨架
验收条件：AC-01 新轮次七类表栏位齐全
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow start 新轮次后打开各环节工作记录表
测试入口：tests/test_records.py::test_scaffold_migrates_v2_rows_preserving_values
代码入口：src/workflow_loop/records.py::create_or_complete_table
准备数据：构造 table_format_version=2 的轮次和一张缺少新栏位的旧表，行内已有已填值
执行动作：调用 create_or_complete_table 补齐骨架并迁移行栏目
关键断言：补齐后每类行清单栏目与 v2 schema 完全一致，已填值原样保留，多余栏目被剔除
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    root = tmp_path / "proj"
    root.mkdir()
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    full = root / relative
    table = json.loads(full.read_text(encoding="utf-8"))
    # 模拟 schema 演进前填入的旧 3 列行 + 一个未知列
    table["代码修改计划"] = [
        {"文件": "src/a.py", "计划修改内容": "在 status_hint 中删除已完成轮次仍提示 done 的分支，改为提示开新一轮", "对应验收条件": "AC-01", "旧列": "x"}
    ]
    full.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    migrated = json.loads(full.read_text(encoding="utf-8"))["代码修改计划"][0]
    assert migrated["文件"] == "src/a.py"
    assert migrated["计划修改内容"] == "在 status_hint 中删除已完成轮次仍提示 done 的分支，改为提示开新一轮"
    assert "旧列" not in migrated
    assert set(migrated) == set(
        records_mod.KIND_SCHEMAS["impl_record"]["row_lists"]["代码修改计划"]["columns"]
    )


def test_test_plan_manual_items_machine_columns_optional(tmp_path: Path) -> None:
    """R8/AC-02：测试方式=人工验收时机器列可留空；控制列未填不放大可选范围。

Workflow-Test
主题：测试计划表并入设计语义列
测试项：TC-02 人工验收行机器列可空
验收条件：AC-02 人工验收行机器列可空
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate qa 对测试计划表校验
测试入口：tests/test_records.py::test_test_plan_manual_items_machine_columns_optional
代码入口：src/workflow_loop/records.py::validate_table
准备数据：构造人工验收行与自动化行并留空机器列
执行动作：执行 validate_table 校验测试计划表
关键断言：人工验收行机器列留空通过，自动化行留空被点名拒绝
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    manual_row = {c: "" for c in records_mod.KIND_SCHEMAS["test_plan"]["row_lists"]["测试项"]["columns"]}
    manual_row.update({
        "测试项编号": "TC-01", "直白测试名称": "肉眼核对输出", "前置测试项": "无",
        "测试方式": "人工验收", "产品入口": "workflow status", "准备数据": "无",
        "执行动作": "执行命令", "观察位置": "终端", "预期结果": "显示冻结版本",
        "不通过表现": "不显示", "证据要求": "用户回答", "对应验收条件": "AC-01",
    })
    problems = records_mod.validate_table("test_plan", {
        "表版本": "2", "工作流编号": "wf-1", "验收主题": "主题A",
        "测试项": [manual_row],
        "测试范围说明": ["覆盖开工冻结表版本在 status 输出中的展示行为"],
        "测试条件要求": [], "未决测试条件": [], "针对性回归范围": [],
    }, "2")
    assert problems == [], problems

    # 控制列留空 → 机器列仍必填
    row_no_mode = dict(manual_row)
    row_no_mode["测试方式"] = ""
    problems = records_mod.validate_table("test_plan", {
        "表版本": "2", "工作流编号": "wf-1", "验收主题": "主题A",
        "测试项": [row_no_mode], "测试范围说明": [], "测试条件要求": [],
        "未决测试条件": [], "针对性回归范围": [],
    }, "2")
    assert any("测试方式" in message for _category, message in problems)
    assert any("命令参数数组" in message for _category, message in problems)


def test_start_freezes_table_version(tmp_path: Path) -> None:
    """AC-03：新轮次开工把程序当前表版本写入 state 冻结。

Workflow-Test
主题：表栏位补齐模板映射
测试项：TC-05 开工冻结表版本写入状态
验收条件：AC-03 表版本开工冻结
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow start 开新工作轮
测试入口：tests/test_records.py::test_start_freezes_table_version
代码入口：src/workflow_loop/cli.py::cmd_start
准备数据：准备可开工的项目目录
执行动作：执行 workflow start 开新一轮
关键断言：开工即冻结当前程序表版本并随状态序列化往返保留
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    root = tmp_path / "proj"
    root.mkdir()
    _install_project(root)
    _run(["start", "--intent", "light_task"], root)
    state = state_mod.load_state(str(root))
    assert state is not None
    assert state.table_format_version == records_mod.TABLE_FORMAT_VERSION


def test_validate_reports_category_and_all_problems(tmp_path: Path) -> None:
    table = {
        "表版本": "1",
        "工作流编号": "wf-1",
        "验收主题": "主题A",
        "代码修改计划": [
            {"文件": "src/a.py", "错误列": "x"},
            {"文件": "src/a.py", "计划修改内容": "a", "对应验收条件": "AC-01"},
            {"文件": "src/a.py", "计划修改内容": "b", "对应验收条件": "AC-02"},
        ],
        "实际代码修改": [],
        "实施动作记录": [],
        "实施中问题与处理": [],
        "未完成状态": "状态：无",
    }
    problems = records_mod.validate_table("impl_record", table)
    categories = {category for category, _ in problems}
    assert records_mod.FORMAT_CATEGORY in categories
    assert records_mod.CONTENT_CATEGORY in categories
    joined = "\n".join(message for _category, message in problems)
    assert "栏目与定义不符" in joined
    assert "重复登记" in joined
    # 同一输入重复校验，问题清单和顺序一致
    again = records_mod.validate_table("impl_record", table)
    assert again == problems


def test_r19_lists_all_substance_problems_once(tmp_path: Path) -> None:
    """AC-01（门禁实质内容校验）：敷衍填表一次列出全部四类不合格栏位。

Workflow-Test
主题：门禁实质内容校验
测试项：TC-01 敷衍内容一次返回全部实质问题
验收条件：AC-01 敷衍填表一次拦全
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate impl 的表校验
测试入口：tests/test_records.py::test_r19_lists_all_substance_problems_once
代码入口：src/workflow_loop/records.py::validate_table
准备数据：构造多处占位与不达最低信息量的表
执行动作：执行 validate_table
关键断言：一次返回全部实质问题，每条含位置、值、期望和改法
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    table = _fill_impl_table_v2(
        json.loads(json.dumps(_blank_impl_table(), ensure_ascii=False))
    )
    # 占位词命中自由描述列
    table["代码修改计划"][0]["计划修改内容"] = "符合预期"
    # 低于最小信息量
    table["实际代码修改"][0]["修改理由"] = "改"
    # 空的必填叙述栏
    table["预期产品结果"] = []
    # 非允许"暂无"的必填叙述栏填"暂无"
    table["未决问题"] = ["暂无"]  # 允许：确无内容栏声明
    problems = records_mod.validate_table("impl_record", table, "2")
    joined = "\n".join(message for _category, message in problems)
    assert "占位词" in joined
    assert "最小信息量" in joined
    assert "预期产品结果" in joined and "必填" in joined
    assert "未决问题" not in joined  # 声明允许整栏"暂无"，不误伤
    # 一次列出全部：至少三条独立问题
    assert len(problems) >= 3


def test_r19_reference_and_enum_columns_not_flagged(tmp_path: Path) -> None:
    """AC-02：编号引用列、枚举列与机器列不因长度短被拦截；实质内容不误伤。

Workflow-Test
主题：门禁实质内容校验
测试项：TC-02 引用列与枚举列不误报
验收条件：AC-02 实质内容不误伤
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate impl 的表校验
测试入口：tests/test_records.py::test_r19_reference_and_enum_columns_not_flagged
代码入口：src/workflow_loop/records.py::validate_table
准备数据：构造引用编号列与枚举列取值合法的表
执行动作：执行 validate_table
关键断言：合法引用与枚举取值不被报为敷衍内容
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    table = _fill_impl_table_v2(_blank_impl_table())
    problems = records_mod.validate_table("impl_record", table, "2")
    assert problems == [], problems
    # 前置步骤"无"是声明允许值，不算占位
    table["代码修改计划"][0]["前置步骤"] = "无"
    assert records_mod.validate_table("impl_record", table, "2") == []
    # v1 表不受 R19 约束（历史轮次冻结口径）
    v1_table = dict(table)
    v1_table["表版本"] = "1"
    v1_table["代码修改计划"] = [{"文件": "src/a.py", "计划修改内容": "改", "对应验收条件": "AC-01"}]
    problems = records_mod.validate_table("impl_record", v1_table, "1")
    assert not any("占位" in message or "信息量" in message for _category, message in problems)


def test_r19_flow_only_topic_exempted(tmp_path: Path) -> None:
    """AC-04：纯流程主题计划行填标记后，代码结果类栏位空不拦；必填叙述栏仍查。

Workflow-Test
主题：门禁实质内容校验
测试项：TC-04 纯流程主题按标记豁免代码结果
验收条件：AC-04 纯流程主题按标记豁免
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate impl 对纯流程主题校验
测试入口：tests/test_records.py::test_r19_flow_only_topic_exempted
代码入口：src/workflow_loop/records.py::validate_table
准备数据：构造计划行全部填纯流程标记的主题表
执行动作：执行 validate_table 与门禁核对
关键断言：纯流程主题不要求实际代码修改行，豁免生效
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    table = _fill_impl_table_v2(_blank_impl_table())
    table["代码修改计划"] = [
        {
            "顺序": "1",
            "文件": records_mod.FLOW_ONLY_MARKER,
            "类、函数或配置项": "workflow return 后重走环节",
            "当前逻辑": "验收文档由旧渲染器生成，缺少表映射栏位",
            "计划修改内容": "实施完成后执行 workflow return --to acceptance_plan，用 v2 表重新生成验收文档并逐项核对",
            "数据、状态或输出变化": "验收计划与实施记录文档全部由 v2 表重新生成",
            "对应验收条件": "AC-01",
            "前置步骤": "无",
        }
    ]
    table["实施动作记录"] = []
    table["实际代码修改"] = []
    table["开发检查计划"] = []
    table["开发检查记录"] = []
    assert records_mod.validate_table("impl_record", table, "2") == []
    # 实施依据与预期产品结果仍按①-④检查，不被豁免吞掉
    table["预期产品结果"] = []
    problems = records_mod.validate_table("impl_record", table, "2")
    assert any("预期产品结果" in message and "必填" in message for _c, message in problems)


def test_r19_flow_only_marker_mixed_with_real_rows_rejected(tmp_path: Path) -> None:
    """AC-04 反向：标记行与真实代码行混在同一张表时报错，不能借标记绕过代码记录。"""
    table = _fill_impl_table_v2(_blank_impl_table())
    table["代码修改计划"].append(
        {
            "顺序": "2",
            "文件": records_mod.FLOW_ONLY_MARKER,
            "类、函数或配置项": "发布核对",
            "当前逻辑": "暂无现有逻辑",
            "计划修改内容": "执行发布清单核对并把结果写入发布记录，不修改任何代码",
            "数据、状态或输出变化": "无代码变化，只核对发布产物清单",
            "对应验收条件": "AC-02",
            "前置步骤": "无",
        }
    )
    problems = records_mod.validate_table("impl_record", table, "2")
    joined = "\n".join(message for _c, message in problems)
    assert "混合" in joined or "同时存在标记行" in joined
    # 混合表不享受豁免：代码结果类栏位仍按必填检查（此表已填所以不重复报）
    assert records_mod.impl_table_exempts_code_result_lists(table) is False


def test_product_features_other_section_change_no_false_tamper(tmp_path: Path) -> None:
    """AC-03：产品总说明追加其他章节（如修改记录）后同步不误报手改。

Workflow-Test
主题：门禁实质内容校验
测试项：TC-03 其他章节变化不误报功能清单手改
验收条件：AC-03 功能清单不误报手改
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate 更新产品总说明功能清单
测试入口：tests/test_records.py::test_product_features_other_section_change_no_false_tamper
代码入口：src/workflow_loop/records.py::_sync_product_features
准备数据：已同步过的产品总说明，仅修改功能清单以外的章节
执行动作：再次执行功能清单同步
关键断言：其他章节变化不报文档被手改，功能清单块正常重写
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    root = tmp_path / "proj"
    root.mkdir()
    (root / "spec").mkdir()
    overview = root / "spec" / "产品总说明.md"
    overview.write_text(
        "# 产品\n\n## 7. 产品功能\n\n旧清单\n\n## 8. 相关文档\n\n暂无\n",
        encoding="utf-8",
    )
    (root / "spec" / "功能_一次安装.md").write_text("# 【功能】一次安装\n", encoding="utf-8")
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "product_features", "")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["功能"] = [
        {
            "功能名称": "一次安装",
            "一句话说明": "一条命令完成安装",
            "对应场景": "安装场景",
            "功能文档路径": "./功能_一次安装.md",
        }
    ]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    problems, _docs = records_mod.sync_stage_tables(str(root), _state_with_stage("wf-1", "spec"))
    assert problems == [], problems
    # 其他章节追加内容（模拟修改记录/上下游更新），不动第 7 章
    overview.write_text(
        overview.read_text(encoding="utf-8") + "\n## 9. 修改记录\n\n- 2026-08-30 追加\n",
        encoding="utf-8",
    )
    problems, _docs = records_mod.sync_stage_tables(str(root), _state_with_stage("wf-1", "spec"))
    assert problems == [], problems
    # 真实手改第 7 章仍然要报
    content = overview.read_text(encoding="utf-8")
    overview.write_text(
        content.replace("## 7. 产品功能", "## 7. 产品功能\n\n手工插入的段落"),
        encoding="utf-8",
    )
    problems, _docs = records_mod.sync_stage_tables(str(root), _state_with_stage("wf-1", "spec"))
    assert any("文档被直接修改" in message for _category, message in problems)


def _blank_impl_table() -> dict:
    import copy
    from workflow_loop import records as _r
    # 用 create_or_complete_table 需要磁盘目录，这里直接构造空骨架
    schema = _r.KIND_SCHEMAS["impl_record"]
    table = {
        "表版本": "2",
        "工作流编号": "wf-1",
        "验收主题": "主题A",
        "生成文档哈希": None,
        "生成文档路径": None,
        "填写说明": {},
    }
    for list_key, definition in schema["row_lists"].items():
        table[list_key] = []
    for narrative_key in schema["narrative"]:
        table[narrative_key] = []
    table["未完成状态"] = "状态：无"
    return copy.deepcopy(table)


def _fill_impl_table_v2(table: dict) -> dict:
    """把 impl_record 表填成版本 2 全栏位合法内容（模板四章映射，R18）。"""
    table["实施依据"] = [
        {
            "依据类型": "验收条件",
            "依据编号": "JU-01",
            "具体内容": "AC-01：完成输出不再提示旧命令",
            "文档位置": "[AC-01](../acceptance/主题A_验收计划.md#ac-01)",
        }
    ]
    table["最低实现设计"] = [
        {
            "设计项": "模块与职责",
            "已确认做法": "records.py 负责按表生成，stages.py 只做门禁调用",
            "选择理由": "生成逻辑集中一处，改动可被单元测试覆盖",
            "对应验收条件": "AC-01",
        }
    ]
    table["代码修改计划"] = [
        {
            "顺序": "1",
            "文件": "src/a.py",
            "类、函数或配置项": "status_hint",
            "当前逻辑": "已完成轮次仍提示执行 done",
            "计划修改内容": "在 status_hint 中删除已完成轮次仍提示 done 的分支，改为提示开新一轮",
            "数据、状态或输出变化": "完成输出不再提示执行完成后的旧命令",
            "对应验收条件": "AC-01",
            "前置步骤": "无",
        }
    ]
    table["开发检查计划"] = [
        {
            "检查命令或方法": "uv run python -m pytest tests/test_records.py -q",
            "检查范围": "实施记录生成与手改检测",
            "预期观察结果": "pytest 全部通过且新断言无失败项",
        }
    ]
    table["实施动作记录"] = [
        {
            "实施顺序": "1",
            "对应计划步骤": "1",
            "文件": "src/a.py",
            "代码位置（最终文件）": "L10-L20",
            "实际执行的动作": "修改 src/a.py 并本地核对",
            "当步反馈": "pytest 通过",
            "状态": "已完成",
        }
    ]
    table["实际代码修改"] = [
        {
            "文件": "src/a.py",
            "代码位置（最终文件）": "L10-L20",
            "实际修改的代码逻辑": "status_hint 按 run_status 判定，完成态不再返回旧命令提示",
            "数据、状态或输出的实际变化": "完成输出不再提示执行完成后的旧命令",
            "修改理由": "完成提示属于本轮已确认行为，死路提示会误导用户重复执行",
            "对应验收条件": "AC-01",
            "测试证据": "tests/test_records.py",
        }
    ]
    table["开发检查记录"] = [
        {
            "检查命令或方法": "uv run python -m pytest tests/test_records.py -q",
            "检查范围": "实施记录生成与手改检测",
            "实际反馈": "pytest 481 项全部通过，退出码 0",
            "是否需要继续修改": "否",
        }
    ]
    table["预期产品结果"] = ["用户执行完成后不再看到旧命令提示"]
    table["实施中问题与处理"] = []
    table["未决问题"] = ["暂无"]
    table["未完成状态"] = "状态：无"
    return table


def test_generate_impl_doc_and_detect_tamper(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "impl").mkdir()
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    table_path = root / relative
    table = _fill_impl_table_v2(json.loads(table_path.read_text(encoding="utf-8")))
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    problems, documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "impl"),
    )
    assert problems == [], problems
    doc = root / "impl" / "主题A_实施记录.md"
    assert doc.is_file()
    content = doc.read_text(encoding="utf-8")
    # 模板四章全部渲染且内容来自表栏位（R16/R18/AC-02）
    assert "## 1. 实施依据" in content
    assert "### 2.1 预期产品结果" in content
    assert "### 2.2 最低实现设计" in content
    assert "#### 开发检查计划" in content
    assert "### 2.4 未决问题" in content
    assert "暂无" in content  # 未决问题为空时显示暂无
    assert "### 3.1 实施动作记录" in content
    assert "#### 3.4.1 实际代码修改" in content
    assert "#### 3.4.2 开发检查记录" in content
    assert "## 4. 上下游文档" in content
    # 占位指引句被消灭
    for banned in ("由代码计划行承载", "填在工作记录表", "本记录由工作记录表按栏目自动生成"):
        assert banned not in content

    # 手改文档 → 检出且不覆盖
    with doc.open("a", encoding="utf-8") as stream:
        stream.write("手工追加\n")
    problems, _documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "impl"),
    )
    assert any("文档被直接修改" in message for _category, message in problems)
    assert "手工追加" in doc.read_text(encoding="utf-8")


def test_pristine_table_activates_table_path_and_reports_unfilled(tmp_path: Path) -> None:
    # R11（2026-08-29-2338 轮修订）：表文件存在即启用表流程，空表不再静默跳过，
    # 门禁报"尚未填写"并停留表模式，不退回文档模式解析正式文档。
    """Workflow-Test
主题：表模式启用判定统一
测试项：TC-01 空表也启用表路径并报尚未填写
验收条件：AC-01 表存在即锁定表模式
测试方式：自动化测试
测试层级：单元测试
产品入口：对只建表未填写的轮次执行 workflow gate
测试入口：tests/test_records.py::test_pristine_table_activates_table_path_and_reports_unfilled
代码入口：src/workflow_loop/records.py::has_any_table_file
准备数据：构造只生成空工作记录表的轮次
执行动作：执行环节门禁校验
关键断言：表文件存在即走表路径，报尚未填写并停留，不退回文档模式
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    root = tmp_path / "proj"
    root.mkdir()
    records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    assert not records_mod.has_any_table(str(root), "wf-1", "impl", ["主题A"])
    assert records_mod.has_any_table_file(str(root), "wf-1", "impl", ["主题A"])
    problems, documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "impl"),
    )
    assert any("尚未填写" in message for _category, message in problems), problems
    assert not any("文档被直接修改" in message for _category, message in problems)
    assert documents == []


def test_missing_topic_table_reports_named_error(tmp_path: Path) -> None:
    # R19 第⑤条：本环节按主题建表时某主题缺表，报"某主题缺少某表"，不静默跳过。
    """Workflow-Test
主题：表模式启用判定统一
测试项：TC-02 缺表主题按名单点名报错
验收条件：AC-02 缺表主题点名报错
测试方式：自动化测试
测试层级：单元测试
产品入口：对缺少主题表的轮次执行 workflow gate
测试入口：tests/test_records.py::test_missing_topic_table_reports_named_error
代码入口：src/workflow_loop/records.py::sync_stage_tables
准备数据：构造双主题轮次且其中一个主题缺表
执行动作：执行环节门禁校验
关键断言：点名缺失主题与表路径，另一个主题不受牵连
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    root = tmp_path / "proj"
    root.mkdir()
    records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    problems, _documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "impl", ["主题A", "主题B"]),
    )
    assert any("主题B" in message and "缺少" in message for _category, message in problems), problems


def test_bad_encoding_table_reports_structured_error(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    table_path = root / ".workflow_loop/records/wf-1/impl_record_主题A.json"
    table_path.parent.mkdir(parents=True)
    table_path.write_bytes("（编码声明）".encode("gbk"))
    try:
        records_mod.load_table(str(table_path))
        raised = False
    except records_mod.RecordsError as exc:
        raised = True
        assert "UTF-8" in str(exc)
    assert raised


def _state_with_stage(
    workflow_id: str, stage: str, topics: list[str] | None = None
) -> state_mod.WorkflowState:
    state = state_mod.WorkflowState(
        workflow_id=workflow_id, intent="product_change", topics=topics or ["主题A"]
    )
    state.current_stage = stage
    state.stages[stage] = state_mod.StageState()
    return state


def test_status_after_completed_does_not_point_to_done(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _install_project(root)
    _run(["start", "--intent", "light_task"], root)
    _run(["light", "--discuss-done", "--task", "t", "--verification", "v"], root)
    _run(["light", "--confirmed", "--result", "done"], root)
    _run(["done"], root)
    code, out, _err = _run(["status"], root)
    assert code == 0
    assert "调 `workflow done`" not in out
    assert "已经完成" in out


def test_gate_with_non_utf8_document_reports_structured_failure(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _install_project(root)
    _run(["start", "--intent", "from_scratch"], root)
    _run(["discuss"], root)
    _run(["gate", "spec", "--discuss-done"], root)
    (root / "spec").mkdir(parents=True, exist_ok=True)
    overview = root / "spec" / "产品总说明.md"
    overview.write_text(
        "# 产品总说明\n\n## 7. 产品功能\n\n旧清单\n\n## 8. 相关文档\n\n暂无\n",
        encoding="utf-8",
    )
    (root / "spec" / "功能_一.md").write_bytes("# 【功能】功能一\n".encode("gbk"))
    # R11：填 product_features 表（让 sync 走到 GBK 文件检查）
    _records_dir = root / ".workflow_loop" / "records"
    _wf_dirs = sorted(d for d in _records_dir.iterdir() if d.is_dir())
    _pf_path = _wf_dirs[0] / "product_features_product_features.json"
    _pf = json.loads(_pf_path.read_text(encoding="utf-8"))
    _pf["功能"] = [
        {"功能名称": "功能一", "一句话说明": "功能一说明", "对应场景": "场景", "功能文档路径": "./功能_一.md"}
    ]
    _pf_path.write_text(json.dumps(_pf, ensure_ascii=False, indent=2), encoding="utf-8")
    code, out, _err = _run(["gate", "spec"], root)
    assert "Traceback" not in out
    assert "阶段校验无法完成" in out
    assert "下一步命令" in out


def test_corrupted_state_file_reports_clean_error(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _install_project(root)
    (root / ".workflow_loop" / "state.json").write_text("{broken", encoding="utf-8")
    code, out, _err = _run(["status"], root)
    assert "Traceback" not in out


def test_regenerate_indexes_from_topic_relations(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "topic_relations", "")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["主题关系"] = [{"验收主题": "主题A", "前置主题": "无"}]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = records_mod.regenerate_workflow_indexes(str(root), "wf-1")
    assert len(paths) == 3
    acceptance_index = (root / "acceptance" / "索引.md").read_text(encoding="utf-8")
    assert "主题A" in acceptance_index and "wf-1" in acceptance_index
    assert (root / "impl" / "索引.md").is_file()
    assert (root / "qa" / "索引.md").is_file()


def test_product_features_section_rewrite(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "spec").mkdir()
    overview = root / "spec" / "产品总说明.md"
    overview.write_text(
        "# 产品\n\n## 7. 产品功能\n\n旧清单\n\n## 8. 相关文档\n\n暂无\n",
        encoding="utf-8",
    )
    (root / "spec" / "功能_一次安装.md").write_text("# 【功能】一次安装\n", encoding="utf-8")
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "product_features", "")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["功能"] = [
        {
            "功能名称": "一次安装",
            "一句话说明": "一条命令完成安装",
            "对应场景": "安装场景",
            "功能文档路径": "./功能_一次安装.md",
        }
    ]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    problems, documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "spec"),
    )
    assert problems == [], problems
    content = overview.read_text(encoding="utf-8")
    assert "一次安装" in content and "旧清单" not in content
    # 再同步一次：内容一致，不报手改
    problems, _documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "spec"),
    )
    assert problems == [], problems


def test_spike_bug_design_tables_generate_docs(tmp_path: Path) -> None:
    """Workflow-Test
主题：表栏位补齐模板映射
测试项：TC-02 填写完整的表逐节生成文档
验收条件：AC-02 生成文档无占位句
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate 各环节第二道门按表生成正式文档
测试入口：tests/test_records.py::test_spike_bug_design_tables_generate_docs
代码入口：src/workflow_loop/records.py::generate_document
准备数据：构造填写完整且满足逐栏最低信息量的 spike、缺陷、设计同步等表
执行动作：调用 generate_document 生成对应正式文档
关键断言：模板规定的每一节都存在且内容来自表栏位，不出现占位句或指引句
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    root = tmp_path / "proj"
    root.mkdir()
    state = state_mod.WorkflowState(
        workflow_id="wf-1", intent="product_change", topics=["主题A"]
    )
    for stage, kind, topic in [
        ("spike", "spike_conclusion", ""),
        ("reproduce", "bug_record", ""),
        ("update_code_design", "design_sync", ""),
    ]:
        relative = records_mod.create_or_complete_table(str(root), "wf-1", kind, topic)
        table_path = root / relative
        table = json.loads(table_path.read_text(encoding="utf-8"))
        schema = records_mod.KIND_SCHEMAS[kind]
        for list_key, definition in schema["row_lists"].items():
            table[list_key] = [{
                column: (f"{column}内容说明具体事实与取值"
                         if column not in ("结果状态", "是否阻塞后续", "缺陷编号", "穿刺项编号")
                         else f"{column}内容")
                for column in definition["columns"]
            }]
        for narrative_key in schema["narrative"]:
            table[narrative_key] = [f"{narrative_key}：本节说明具体事实、依据与下一步"]
        table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
        state.current_stage = stage
        state.stages[stage] = state_mod.StageState()
        problems, documents = records_mod.sync_stage_tables(str(root), state)
        assert problems == [], (stage, problems)
    # 三类表都生成了正式文档
    assert (root / ".workflow_loop/records/wf-1/spike_conclusion_spike_conclusion.md").is_file()
    assert (root / ".workflow_loop/records/wf-1/bug_record_bug_record.md").is_file()
    assert (root / ".workflow_loop/records/wf-1/design_sync_design_sync.md").is_file()


def test_acceptance_record_rejects_criterion_not_in_table(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "acceptance_plan", "主题A")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["验收条件"] = [{
        "验收条件编号": "AC-01",
        "开始前状态": "s", "触发动作": "a", "可检查结果": "r",
        "通过标准": "p", "不通过标准": "f", "产品设计依据": "d",
    }]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    from argparse import Namespace
    from workflow_loop import cli, state as state_mod

    state = state_mod.WorkflowState(workflow_id="wf-1", intent="product_change", topics=["主题A"])
    state.current_stage = "topic_acceptance"
    state.stages["topic_acceptance"] = state_mod.StageState()
    # 表中存在的编号直接放行
    assert cli._reject_criterion_not_in_table(str(root), state, "主题A", "AC-01") is False
    # 表中不存在的编号拒绝
    try:
        cli._reject_criterion_not_in_table(str(root), state, "主题A", "AC-99")
        raised = False
    except SystemExit:
        raised = True
    assert raised


def _fill_acceptance_plan_table(root: Path) -> Path:
    """建一张填写完整的验收计划表并生成文档，返回文档路径。"""
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "acceptance_plan", "主题A")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["验收条件"] = [
        {
            "验收条件编号": "AC-01",
            "验收条件名称": "安装前可审查",
            "开始前状态": "用户在目标项目根目录且已安装 Python",
            "触发动作": "用户执行安装命令且尚未确认",
            "可检查结果": "终端输出的项目路径与环境预检清单",
            "通过标准": "输出含项目绝对路径且取消时零写入",
            "不通过标准": "取消后仍写入全局命令",
            "产品设计依据": "[安装到项目 R4](../spec/功能_安装到项目.md#4-规则)",
        }
    ]
    table["验收目标说明"] = ["用户一条命令完成三平台安装且不留半套"]
    table["需求来源"] = ["[产品总说明](../spec/产品总说明.md)"]
    table["产品设计依据"] = ["[安装到项目 R4](../spec/功能_安装到项目.md#4-规则)"]
    table["本主题验收"] = ["三平台单命令安装入口"]
    table["本主题不验收"] = ["安装后的工作流行为"]
    table["完成判定"] = ["AC-01 通过后本主题完成"]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "acceptance").mkdir(exist_ok=True)
    return table_path


def test_downstream_generation_backfills_upstream_reference(tmp_path: Path) -> None:
    """Workflow-Test
主题：表栏位补齐模板映射
测试项：TC-04 下游生成回补上游引用
验收条件：AC-02 生成文档无占位句
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate impl 首次生成实施记录文档
测试入口：tests/test_records.py::test_downstream_generation_backfills_upstream_reference
代码入口：src/workflow_loop/records.py::sync_stage_tables
准备数据：先填写并生成验收计划文档，再填写实施记录表
执行动作：执行 sync_stage_tables 生成实施记录文档
关键断言：下游行由（待生成）升级为真实链接，只刷新引用方，表内容不变
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    root = tmp_path / "proj"
    root.mkdir()
    (root / "spec").mkdir()
    (root / "spec" / "功能_安装到项目.md").write_text("# 【功能】安装到项目\n", encoding="utf-8")
    acceptance_table = _fill_acceptance_plan_table(root)
    records_mod.sync_stage_tables(str(root), _state_with_stage("wf-1", "acceptance_plan"))
    plan_doc = root / "acceptance" / "主题A_验收计划.md"
    assert "（待生成）" in plan_doc.read_text(encoding="utf-8")
    assert "[主题A 实施记录]" not in plan_doc.read_text(encoding="utf-8")

    (root / "impl").mkdir()
    impl_relative = records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    impl_table_path = root / impl_relative
    impl_table = _fill_impl_table_v2(json.loads(impl_table_path.read_text(encoding="utf-8")))
    impl_table_path.write_text(json.dumps(impl_table, ensure_ascii=False, indent=2), encoding="utf-8")

    problems, documents = records_mod.sync_stage_tables(str(root), _state_with_stage("wf-1", "impl"))
    assert problems == [], problems
    content = plan_doc.read_text(encoding="utf-8")
    # 实施记录已生成 → 验收计划下游行升级成链接；测试计划仍未生成 → 保持待生成
    assert "[主题A 实施记录](../impl/主题A_实施记录.md)" in content
    assert "（待生成）" in content
    assert str(plan_doc.relative_to(root)) in documents
    # 表内容不因回补被改动（只更新程序专用键）
    reloaded = json.loads(acceptance_table.read_text(encoding="utf-8"))
    assert reloaded["验收条件"][0]["通过标准"] == "输出含项目绝对路径且取消时零写入"


def test_records_lifecycle_abort_deletes_and_clean_preserves(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    removed = records_mod.delete_workflow_records(str(root), "wf-1")
    assert removed and not (root / ".workflow_loop/records/wf-1").exists()

    # 从零清场只删除 spec/acceptance/qa/impl/bug，不碰旧轮次的工作记录表
    records_mod.create_or_complete_table(str(root), "wf-old", "impl_record", "旧主题")
    from workflow_loop.cli import clean_artifacts

    cleaned = clean_artifacts(str(root))
    assert (root / ".workflow_loop/records/wf-old").exists()
    assert not any("records" in item for item in cleaned)


def test_test_plan_columns_match_coverage_table() -> None:
    """Workflow-Test
主题：测试计划表并入设计语义列
测试项：TC-01 测试计划表列与模板覆盖表一致
验收条件：AC-01 测试计划表列齐覆盖表全
测试方式：自动化测试
测试层级：单元测试
产品入口：打开测试计划工作记录表与生成文档的验收条件覆盖表
测试入口：tests/test_records.py::test_test_plan_columns_match_coverage_table
代码入口：src/workflow_loop/records.py::KIND_SCHEMAS
准备数据：读取 test_plan schema 与模板 qa/test_plan.md 的覆盖表表头
执行动作：对照两者列名与列序及机器列配置
关键断言：覆盖表各列在 schema 中同名同序，机器列齐备且人工验收行条件可选
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    template = (
        Path(records_mod.__file__).parent
        / "data" / "Template_Repository" / "qa" / "test_plan.md"
    )
    header = next(
        line
        for line in template.read_text(encoding="utf-8").splitlines()
        if line.startswith("| 验收条件链接")
    )
    doc_columns = [cell.strip() for cell in header.strip().strip("|").split("|")]
    assert doc_columns[0] == "验收条件链接"
    schema_columns = records_mod.KIND_SCHEMAS["test_plan"]["row_lists"]["测试项"]["columns"]
    assert doc_columns[2:] == schema_columns[2:13]
    assert schema_columns[0] == "测试项编号" and schema_columns[1] == "直白测试名称"
    assert schema_columns[13] == "对应验收条件"
    machine = schema_columns[14:]
    assert machine == ["命令参数数组", "工作目录", "超时秒数", "报告适配器", "正式目标名称"]
    definition = records_mod.KIND_SCHEMAS["test_plan"]["row_lists"]["测试项"]
    manual_optional = definition["conditional_optional_by_column"]["测试方式"]["人工验收"]
    for column in machine:
        assert column in manual_optional or column in definition.get("optional_columns", [])

    table = {
        "表版本": "2",
        "工作流编号": "wf-1",
        "验收主题": "主题A",
        "测试项": [
            {
                "测试项编号": "TC-01",
                "直白测试名称": "样例用例",
                "前置测试项": "无",
                "测试方式": "自动化测试",
                "产品入口": "样例入口",
                "代码入口": "src/a.py::func_a",
                "测试入口": "tests/test_sample.py::test_a",
                "准备数据": "样例数据",
                "执行动作": "执行样例动作",
                "观察位置": "样例观察点",
                "预期结果": "样例预期",
                "不通过表现": "样例不通过表现",
                "证据要求": "junit 报告与退出码 0",
                "对应验收条件": "AC-01",
            }
        ],
    }
    document = records_mod.generate_document("test_plan", table, project_root="")
    doc_lines = document.splitlines()
    doc_header = next(
        line for line in doc_lines if line.startswith("| 验收条件链接")
    )
    doc_separator = doc_lines[doc_lines.index(doc_header) + 1]
    rendered_columns = [cell.strip() for cell in doc_header.strip().strip("|").split("|")]
    separator_columns = len(doc_separator.strip().strip("|").split("|"))
    assert rendered_columns == doc_columns
    assert separator_columns == len(rendered_columns), (
        f"分隔行 {separator_columns} 列与表头 {len(rendered_columns)} 列不一致"
    )
    assert "直白测试名称" not in rendered_columns

    # 结果文档不存在时下游行保持待生成；真实生成后回补为链接
    assert "（待生成）" in document

    _project = Path(tempfile.mkdtemp())
    (_project / "qa").mkdir(parents=True)
    (_project / "qa" / "主题A_测试结果.md").write_text("# 占位结果文档", encoding="utf-8")
    document_after = records_mod.generate_document(
        "test_plan", table, project_root=str(_project)
    )
    assert "[主题A测试结果](./主题A_测试结果.md)" in document_after
    assert "（待生成）" not in document_after.split("## 5.")[1]


def test_table_mode_items_carry_plan_fields_and_skip_manual_rows(tmp_path: Path) -> None:
    """Workflow-Test
主题：测试计划表并入设计语义列
测试项：TC-04 表模式测试项带全字段且人工行不算自动化
验收条件：AC-01 测试计划表列齐覆盖表全
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate qa 对测试计划表与测试代码的核对
测试入口：tests/test_records.py::test_table_mode_items_carry_plan_fields_and_skip_manual_rows
代码入口：src/workflow_loop/test_mapping.py::_test_plan_items_from_table
准备数据：临时项目内写入带验收条件名称的验收计划表，测试计划表含一行自动化与一行人工验收
执行动作：读取自动化测试项并执行追踪标识核对与登记核对
关键断言：自动化项字段与表逐列一致、验收条件名称按表回填、标识核对通过、人工行不被要求登记、结果文档可按分发生成
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    from workflow_loop import test_execution as test_execution_mod
    from workflow_loop import test_mapping as test_mapping_mod

    root = tmp_path / "proj"
    root.mkdir()
    (root / "impl").mkdir()
    (root / "tests").mkdir()
    state = state_mod.WorkflowState(
        workflow_id="wf-1", intent="product_change", topics=["主题A"]
    )
    state.current_stage = "qa"
    state.stages["qa"] = state_mod.StageState()
    state.table_format_version = "2"
    state_mod.save_state(str(root), state)

    acc_rel = records_mod.create_or_complete_table(str(root), "wf-1", "acceptance_plan", "主题A")
    acc = json.loads((root / acc_rel).read_text(encoding="utf-8"))
    acc["验收条件"] = [
        {
            "验收条件编号": "AC-01",
            "验收条件名称": "表模式字段齐全",
            "开始前状态": "实施已完成且测试计划工作记录表已生成",
            "触发动作": "用户执行 workflow gate qa 核对测试计划表与测试代码",
            "可检查结果": "自动化测试项字段与测试计划表逐列一致，Workflow-Test 标识核对通过",
            "通过标准": "名称、验收条件名称和六个计划字段与表逐字一致，人工行不算自动化项",
            "不通过标准": "字段退化为空串或节点号，或人工验收行被要求登记执行",
            "产品设计依据": "工作记录表表模式测试计划语义",
        }
    ]
    (root / acc_rel).write_text(json.dumps(acc, ensure_ascii=False, indent=2), encoding="utf-8")

    plan_rel = records_mod.create_or_complete_table(str(root), "wf-1", "test_plan", "主题A")
    plan = json.loads((root / plan_rel).read_text(encoding="utf-8"))
    columns = records_mod.KIND_SCHEMAS["test_plan"]["row_lists"]["测试项"]["columns"]
    auto_values = {
        "测试项编号": "TC-01",
        "直白测试名称": "表模式字段齐全用例",
        "前置测试项": "无",
        "测试方式": "自动化测试",
        "产品入口": "workflow gate qa 核对测试计划表",
        "代码入口": "src/workflow_loop/test_mapping.py::_test_plan_items_from_table",
        "测试入口": "tests/test_sample.py::test_sample_table_fields",
        "准备数据": "临时项目内写入带验收条件名称的验收计划表与测试计划表",
        "执行动作": "读取自动化测试项并核对追踪标识",
        "观察位置": "自动化测试项字段与标识核对结果",
        "预期结果": "字段与表逐列一致且标识核对通过",
        "不通过表现": "字段为空串或与表不一致",
        "证据要求": "pytest 结构化 junit 报告与退出码 0",
        "对应验收条件": "AC-01",
        "命令参数数组": [".venv/bin/pytest", "tests/test_sample.py::test_sample_table_fields", "-q"],
        "工作目录": "",
        "超时秒数": "600",
        "报告适配器": "pytest-junitxml",
        "正式目标名称": "tests/test_sample.py::test_sample_table_fields",
    }
    manual_values = {
        "测试项编号": "TC-02",
        "直白测试名称": "人工对照填写说明",
        "前置测试项": "无",
        "测试方式": "人工验收",
        "产品入口": "打开测试计划工作记录表的填写说明",
        "代码入口": "无自动化入口",
        "测试入口": "人工对照，无自动化入口",
        "准备数据": "本轮 test_plan 表已生成填写说明",
        "执行动作": "逐列对照模板内容边界",
        "观察位置": "每列说明的三要素",
        "预期结果": "每列说明写明填什么、从哪里取得、必须与什么一致",
        "不通过表现": "说明缺要素或与模板硬性要求不符",
        "证据要求": "人工对照结论写进验收结果文档",
        "对应验收条件": "AC-01",
        "命令参数数组": "",
        "工作目录": "",
        "超时秒数": "",
        "报告适配器": "",
        "正式目标名称": "",
    }
    plan["测试项"] = [
        {column: auto_values.get(column, "") for column in columns},
        {column: manual_values.get(column, "") for column in columns},
    ]
    plan["测试范围说明"] = ["本主题覆盖 AC-01：自动化用例核对表字段回填与人工行豁免，通过标准见测试项行清单。"]
    plan["测试条件要求"] = ["在临时项目目录内执行，使用 pytest 结构化报告，无需外部服务或网络。"]
    plan["未决测试条件"] = ["当前测试条件已全部明确，无未决条件。"]
    plan["针对性回归范围"] = ["本轮改动了表模式登记与执行核对，需回归上述直接受影响行为，其余交给最终全量回归。"]
    (root / plan_rel).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    items = test_mapping_mod.automated_test_items(str(root), ["主题A"])
    assert [item.test_id for item in items] == ["TC-01"]
    item = items[0]
    assert item.test_name == "表模式字段齐全用例"
    assert item.criterion_id == "AC-01"
    assert item.criterion_name == "表模式字段齐全"
    assert item.product_entry == auto_values["产品入口"]
    assert item.code_entry == auto_values["代码入口"]
    assert item.preparation == auto_values["准备数据"]
    assert item.action == auto_values["执行动作"]
    assert item.expected_result == auto_values["预期结果"]
    assert item.evidence_requirement == auto_values["证据要求"]

    (root / "tests" / "test_sample.py").write_text(
        'def test_sample_table_fields() -> None:\n'
        '    """Workflow-Test\n'
        '主题：主题A\n'
        '测试项：TC-01 表模式字段齐全用例\n'
        '验收条件：AC-01 表模式字段齐全\n'
        '测试方式：自动化测试\n'
        '测试层级：单元测试\n'
        '产品入口：workflow gate qa 核对测试计划表\n'
        '测试入口：tests/test_sample.py::test_sample_table_fields\n'
        '代码入口：src/workflow_loop/test_mapping.py::_test_plan_items_from_table\n'
        '准备数据：临时项目内写入带验收条件名称的验收计划表与测试计划表\n'
        '执行动作：读取自动化测试项并核对追踪标识\n'
        '关键断言：字段与表逐列一致且标识核对通过\n'
        '预期证据：pytest 结构化 junit 报告与退出码 0\n'
        '    """\n'
        '    from workflow_loop import test_mapping as tm\n'
        '    assert tm._parse_dependency_ids("无") == []\n'
        '    assert tm._parse_dependency_ids("TC-01、TC-02") == ["TC-01", "TC-02"]\n',
        encoding="utf-8",
    )
    ok, detail = test_mapping_mod.validate_workflow_test_markers(str(root), ["主题A"])
    assert ok, detail

    reference_map = records_mod._document_reference_map(str(root), "wf-1", "主题A")
    result_refs = reference_map["qa/主题A_测试结果.md"]
    for referencing_kind in (
        "acceptance_plan",
        "impl_record",
        "test_plan",
        "test_result",
        "acceptance_result",
    ):
        assert (referencing_kind, "主题A") in result_refs, referencing_kind

    loaded = state_mod.load_state(str(root))
    tasks_ok, tasks_detail = test_execution_mod.validate_prepared_tasks(str(root), loaded)
    assert not tasks_ok
    assert "TC-01" in tasks_detail
    assert "TC-02" not in tasks_detail

    from workflow_loop import cli as cli_mod
    cli_mod._prepare_tasks_from_tables(str(root), loaded)
    reloaded = state_mod.load_state(str(root))
    registered = reloaded.stages["qa"].test_tasks["主题A"]
    assert set(registered) == {"TC-01"}
    assert registered["TC-01"].command[:3] == [
        ".venv/bin/pytest", "tests/test_sample.py::test_sample_table_fields", "-q"
    ]

    result_rel = records_mod.create_or_complete_table(str(root), "wf-1", "test_result", "主题A")
    result_table = json.loads((root / result_rel).read_text(encoding="utf-8"))
    result_table["测试结果"] = [
        {"测试项编号": "TC-01", "执行结论": "passed", "机器记录编号": "", "实际结果说明": "字段回填与人工行豁免行为由本用例证明。"}
    ]
    document = records_mod.generate_document(
        "test_result", result_table, project_root=str(root), wf_state=reloaded
    )
    assert isinstance(document, str) and "TC-01" in document
