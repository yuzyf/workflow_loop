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
from . import markdown_links as markdown_links_mod
from . import state as state_mod
from .topic import topic_file_key


RECORDS_ROOT = ".workflow_loop/records"
TABLE_FORMAT_VERSION = "4"

NARRATIVE_KEY = "叙述段落"
DOC_HASH_KEY = "生成文档哈希"
GENERATED_DOC_PATH_KEY = "生成文档路径"
# 缺陷记录走 bug/ 目录的独立生成路径，用单独的程序专用键保存各文件上次生成的哈希；
# 与 DOC_HASH_KEY 一样由程序写入，AI 不填。
BUG_DOC_HASHES_KEY = "缺陷文档哈希"
PROGRAM_FIELD_KEYS = (DOC_HASH_KEY, GENERATED_DOC_PATH_KEY, BUG_DOC_HASHES_KEY)

LINE_RANGE_RE = re.compile(r"L\d+-L\d+")

# 每类表的定义：栏目、行清单、枚举和文档章节。
# kind 是稳定程序标识；row_list 的 key_column 用于编号唯一性检查。
KIND_SCHEMAS: dict[str, dict] = {
    # 实施记录：与 Template_Repository/impl/impl.md 模板章节逐节映射（R18）
    "impl_record": {
        "doc_name": "实施记录",
        "row_lists": {
            "实施依据": {
                "columns": ["依据类型", "依据编号", "具体内容", "文档位置"],
                "key_column": "依据编号",
                "required_at_gate": True,
            },
            "最低实现设计": {
                "columns": ["设计项", "已确认做法", "选择理由", "对应验收条件"],
                "key_column": "设计项",
                "required_at_gate": False,
            },
            "代码修改计划": {
                "columns": [
                    "顺序",
                    "文件",
                    "类、函数或配置项",
                    "当前逻辑",
                    "计划修改内容",
                    "数据、状态或输出变化",
                    "对应验收条件",
                    "前置步骤",
                ],
                "key_column": "顺序",
                "required_at_gate": True,
            },
            "开发检查计划": {
                "columns": ["检查命令或方法", "检查范围", "预期观察结果"],
                "key_column": "检查命令或方法",
                "required_at_gate": True,
            },
            "实施动作记录": {
                "columns": [
                    "实施顺序",
                    "对应计划步骤",
                    "文件",
                    "代码位置（最终文件）",
                    "实际执行的动作",
                    "当步反馈",
                    "状态",
                ],
                "key_column": "实施顺序",
                "required_at_gate": True,
                "line_range_column": "代码位置（最终文件）",
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
            "开发检查记录": {
                "columns": ["检查命令或方法", "检查范围", "实际反馈", "是否需要继续修改"],
                "key_column": "检查命令或方法",
                "required_at_gate": True,
            },
            "核对结论": {
                "columns": ["核对对象", "核对依据"],
                "key_column": "核对对象",
                "required_at_gate": False,
            },
        },
        "narrative": ["预期产品结果", "实施中问题与处理", "未决问题"],
        "enums": {"未完成状态": ["状态：无", "状态：有"]},
    },
    # 测试计划：与 Template_Repository/qa/test_plan.md 模板 13 列设计语义并入（R18）
    "test_plan": {
        "doc_name": "测试计划",
        "row_lists": {
            "测试项": {
                "columns": [
                    "测试项编号",
                    "直白测试名称",
                    "前置测试项",
                    "测试方式",
                    "产品入口",
                    "代码入口",
                    "测试入口",
                    "准备数据",
                    "执行动作",
                    "观察位置",
                    "预期结果",
                    "不通过表现",
                    "证据要求",
                    "对应验收条件",
                    "命令参数数组",
                    "工作目录",
                    "超时秒数",
                    "报告适配器",
                    "正式目标名称",
                ],
                "optional_columns": ["工作目录"],
                "conditional_optional_by_column": {
                    "测试方式": {
                        "人工验收": [
                            "命令参数数组", "超时秒数", "报告适配器",
                            "正式目标名称", "测试入口", "代码入口",
                        ],
                    },
                },
                "key_column": "测试项编号",
                "required_at_gate": True,
            },
            "核对结论": {
                "columns": ["核对对象", "核对依据"],
                "key_column": "核对对象",
                "required_at_gate": False,
            },
        },
        "narrative": ["测试范围说明", "测试条件要求", "未决测试条件", "针对性回归范围"],
        "enums": {},
    },
    "acceptance_plan": {
        "doc_name": "验收计划",
        "row_lists": {
            "验收条件": {
                "columns": [
                    "验收条件编号",
                    "验收条件名称",
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
            # R18：人工验收步骤计划字段由验收计划表承载（按 AC 关联），
            # 生成器渲染进验收结果文档，结果表不复述。
            "人工验收步骤": {
                "columns": [
                    "验收条件编号",
                    "验收对象",
                    "开始前条件",
                    "操作步骤",
                    "观察内容",
                    "预期结果",
                    "用户需要回答",
                ],
                "key_column": "验收条件编号",
                "required_at_gate": False,
            },
            "核对结论": {
                "columns": ["核对对象", "核对依据"],
                "key_column": "核对对象",
                "required_at_gate": False,
            },
        },
        "narrative": [
            "验收目标说明",
            "需求来源",
            "产品设计依据",
            "本主题验收",
            "本主题不验收",
            "完成判定",
        ],
        "enums": {},
    },
    # 穿刺结论：与 Template_Repository/spike/spike.md 模板映射（R18）
    "spike_conclusion": {
        "doc_name": "穿刺结论",
        "row_lists": {
            "穿刺项": {
                "columns": [
                    "穿刺项编号",
                    "真实场景",
                    "要验证的不确定性",
                    "验证结果用于决定什么",
                    "验证方法与命令",
                    "实际观察结果",
                    "结论",
                    "结果状态",
                    "是否阻塞后续",
                    "产品设计影响",
                    "代码设计影响",
                    "剩余风险",
                    "后续处理阶段",
                    "后续需要检查什么",
                ],
                "key_column": "穿刺项编号",
                "required_at_gate": True,
            },
            "可复用资产": {
                "columns": [
                    "资产目录",
                    "用途",
                    "运行方法",
                    "依赖与非敏感输入",
                    "不保留内容",
                    "支撑验收条件",
                ],
                "key_column": "资产目录",
                "required_at_gate": False,
            },
        },
        "narrative": ["结论说明"],
        "enums": {},
    },
    # 缺陷记录：与 Template_Repository/reproduce/reproduce.md 模板映射（R18）
    "bug_record": {
        "doc_name": "缺陷记录",
        "row_lists": {
            "缺陷信息": {
                "columns": ["缺陷编号", "现象", "复现步骤", "实际结果", "期望结果", "根因"],
                "key_column": "缺陷编号",
                "required_at_gate": True,
            },
        },
        "narrative": [
            "缺陷说明",
            "真实复现条件",
            "根因证据",
            "修复仍存在的不确定性",
            "修复与验收结果",
        ],
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
    "architecture_changes": {
        "doc_name": "架构正文变更",
        "row_lists": {
            "正文变更": {
                "columns": ["章节", "原文", "新文", "依据"],
                "key_column": "原文",
                "key_columns": ["章节", "原文"],
                "required_at_gate": False,
            },
        },
        "narrative": [],
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
            # 推进 R47：spec 环节退回核对时，无需修改声明填在本表（spec 无主题级表）
            "核对结论": {
                "columns": ["核对对象", "核对依据"],
                "key_column": "核对对象",
                "required_at_gate": False,
            },
        },
        "narrative": [],
        "enums": {},
    },
    # 测试结果：与 Template_Repository/qa/test.md 模板章节映射（R18）
    "test_result": {
        "doc_name": "测试结果",
        "row_lists": {
            "测试结果": {
                "columns": ["测试项编号", "执行结论", "机器记录编号", "实际结果说明"],
                "optional_columns": ["机器记录编号"],
                "key_column": "测试项编号",
                # R11：测试结果行是 qa 环节核心产出，空表必须报"尚未填写"，
                # 不能静默放行（2026-09-08 实证：空表放行导致整体验收才发现
                # 文档缺失，补填触发哈希变化被迫退回 qa 重走全流程）
                "required_at_gate": True,
            },
            "核对结论": {
                "columns": ["核对对象", "核对依据"],
                "key_column": "核对对象",
                "required_at_gate": False,
            },
        },
        "narrative": ["结果说明", "执行说明", "人工验收交接", "未通过或阻塞"],
        "enums": {},
    },
    # 验收结果：与 Template_Repository/acceptance/acceptance_result.md 模板映射（R18）
    "acceptance_result": {
        "doc_name": "验收结果",
        "row_lists": {
            "验收结果": {
                "columns": [
                    "验收条件编号",
                    "验收方式",
                    "验收结论",
                    "自动化依据",
                    "机器测试记录编号",
                    "用户实际回答",
                    "人工确认",
                    "实际观察结果",
                    "证据",
                    "验收记录编号",
                ],
                "optional_columns": ["用户实际回答", "人工确认", "验收记录编号"],
                "key_column": "验收条件编号",
                "required_at_gate": True,
            },
            "核对结论": {
                "columns": ["核对对象", "核对依据"],
                "key_column": "核对对象",
                "required_at_gate": False,
            },
        },
        "narrative": ["验收说明"],
        "enums": {},
    },
}

COLUMN_HINTS: dict[str, dict[str, str]] = {
    "实施依据": {
        "依据类型": "产品设计、验收条件、现有代码设计或穿刺结论四选一；与实施记录模板第 1 章表格的“依据类型”列一致",
        "依据编号": "该行在表内的唯一编号，例如 JU-01；生成文档用于锚点命名",
        "具体内容": "这条依据规定的产品行为或规则的一句话概括，取自上游文档原文；不写代码实现细节",
        "文档位置": "指向上游文档具体章节或 AC 锚点的 Markdown 链接，例如 [AC-01](../acceptance/主题_验收计划.md#ac-01)；从本主题实施记录出发可解析；现有代码设计没有时写“暂无现有代码设计”",
    },
    "最低实现设计": {
        "设计项": "模块与职责、接口与调用顺序、数据、状态与副作用、错误与边界之一（与实施模板 2.2 表一致），或本轮新增的设计主题名",
        "已确认做法": "这个设计项本轮确定怎么做，写到能指导编码；修改产品时只写本轮新增或改变的决定",
        "选择理由": "为什么这样划分或处理足以完成当前验收条件；不写“最佳实践”这类无依据概括",
        "对应验收条件": "本设计支撑的 AC 编号，多个用顿号连接；取自本主题验收计划表",
    },
    "代码修改计划": {
        "顺序": "从 1 开始的连续整数，表示计划执行顺序；生成文档 2.3 表按本列排序",
        "文件": "项目内相对路径，例如 src/workflow_loop/records.py；与计划实际要改的文件一致",
        "类、函数或配置项": "该文件内要改的具体符号名；新增位置写“新增”；取自真实代码调查，不写模块泛称",
        "当前逻辑": "该符号现在的实际行为一句话；从零项目写“暂无现有逻辑”；必须看过真实代码后填写",
        "计划修改内容": "一句话写清这一处增加、删除或改变什么处理逻辑，例如 表启用判定从按已填内容改为按文件存在",
        "数据、状态或输出变化": "改完后程序或用户可检查到的具体变化，例如 空表主题门禁报“尚未填写”而非跳过",
        "对应验收条件": "本步骤服务的 AC 编号，多个用顿号连接；取自本主题验收计划表",
        "前置步骤": "必须先完成的本表其他行顺序号；无依赖写“无”；只写直接前置，不重复间接依赖",
    },
    "开发检查计划": {
        "检查命令或方法": "实施期间将实际运行的命令或检查方法，例如 uv run python -m pytest tests/test_records.py -q；不写正式测试结论",
        "检查范围": "这条检查覆盖哪些代码行为，例如 表启用判定三处修改后的门禁行为",
        "预期观察结果": "运行后应当看到什么（退出码、报错文字、生成内容），看到即说明实施按预期生效；与计划修改内容逐项对应",
    },
    "实施动作记录": {
        "实施顺序": "从 1 开始的连续整数，按实际执行先后登记",
        "对应计划步骤": "本动作对应的代码修改计划“顺序”号；计划外额外文件写“额外”并在修改理由说明",
        "文件": "实际修改的项目内相对路径",
        "代码位置（最终文件）": "必须写最终文件起止行号 L起始行-L结束行，例如 L12-L34，单行也写 L12-L12，不能只写 L12；局部删除写“基线 L18-L31”；整文件删除写“删除整个文件”",
        "实际执行的动作": "这一步实际增加、删除或修改了什么；写事实，不复制计划文字",
        "当步反馈": "该步完成后的语法、静态检查或局部运行真实反馈；尚未检查时写“待检查”，不写“正式测试通过”",
        "状态": "已完成 或 进行中；全部行完成前不能过第二道门",
    },
    "实际代码修改": {
        "文件": "实际修改文件的项目内相对路径；与 git 真实差异一致，覆盖本轮全部差异文件",
        "代码位置（最终文件）": "必须写最终文件起止行号 L起始行-L结束行，例如 L12-L34，不能只写 L12；每个不连续差异块都要被至少一行覆盖",
        "实际修改的代码逻辑": "根据最终代码写清具体判断、调用和错误处理；不能复制“计划修改内容”代替事实",
        "数据、状态或输出的实际变化": "根据最终代码写可检查的状态、数据、文件或输出变化",
        "修改理由": "该文件为什么属于本轮已确认行为；计划外文件必须在这里说明理由",
        "对应验收条件": "例如 AC-01；取自本主题验收计划表，与代码修改计划的 AC 关联一致",
        "测试证据": "覆盖它的测试或检查，例如 tests/test_records.py::test_xxx 及实际结果；正式测试事实留给 qa 环节",
    },
    "开发检查记录": {
        "检查命令或方法": "与开发检查计划一致的实际命令或方法",
        "检查范围": "该检查实际覆盖的代码行为",
        "实际反馈": "真实观察到的输出摘要（退出码、失败项、报错位置）；不写“正常”“符合预期”",
        "是否需要继续修改": "是 或 否；为“是”时先回到实施动作继续处理，不能直接过门",
    },
    "测试项": {
        "测试项编号": "主题内唯一，例如 TC-01；生成文档锚点和追踪表引用该编号",
        "直白测试名称": "一句话说明测什么行为，读者不看代码也能懂，例如 空表主题门禁报尚未填写不退回文档模式",
        "前置测试项": "本主题内必须先通过的直接 TC 编号；无依赖写“无”；不重复间接依赖",
        "测试方式": "自动化测试、人工验收或 自动化测试 + 人工验收 三选一；能自动化判断的内容不能为省事写纯人工",
        "产品入口": "用户或调用方实际使用的入口，例如 workflow gate impl 命令；取自产品设计使用过程",
        "代码入口": "项目相对文件::可定位标识，例如 src/workflow_loop/stages/stages.py::ImplStage.discussion_validate；不接受目录或模块泛称",
        "测试入口": "tests/文件::测试函数；测试文件可以尚未创建，但路径和目标必须明确；本列只进入生成的测试计划文档，不是登记入口，登记入口取“正式目标名称”列；人工验收行可留空",
        "准备数据": "执行前要建立的具体数据和状态，例如 建一张空 impl_record 表；取自执行动作需要的前提",
        "执行动作": "通过产品入口执行的具体动作一句话；与验收条件“触发动作”语义一致但写到可执行粒度",
        "观察位置": "检查返回值、状态文件、生成文档或输出的具体位置；与验收条件“可检查结果”对应",
        "预期结果": "必须出现的具体值、数量、存在性或状态；与验收条件“通过标准”逐项一致，不新增标准",
        "不通过表现": "出现哪些缺失、错误值或错误状态即失败；与预期结果对应",
        "证据要求": "需要保存的结构化报告和可复核事实，例如 pytest junitxml 报告与退出码",
        "对应验收条件": "本测试项主要服务的 AC 编号；一个测试项只对应一条主要验收条件",
        "命令参数数组": "JSON 数组，例如 [\"pytest\", \"tests/test_a.py\"]；人工验收行留空",
        "工作目录": "项目内相对路径；留空表示项目根",
        "超时秒数": "整数，例如 600；人工验收行留空",
        "报告适配器": "pytest-junitxml 或 vitest-junit；人工验收行留空",
        "正式目标名称": (
            "本列是登记入口的唯一来源：必须写成 项目相对路径::报告里的目标名，"
            "与报告适配器输出的目标名逐字一致，例如 "
            "tests/test_records.py::test_table_rejects_bad_entry（pytest 写 nodeid，"
            "vitest 写 测试文件路径::测试标题）。只写测试标题不带路径会被登记拒绝。"
            "一个测试项覆盖多个测试函数时，把多个入口写成 JSON 数组，例如 "
            '["tests/a.test.ts::读取返回 15 组","tests/a.test.ts::升级文案存在"]；'
            "同行“测试入口”列填了也不参与登记。人工验收行留空"
        ),
    },
    "测试结果": {
        "测试项编号": "与测试计划表一致，例如 TC-01",
        "执行结论": "passed 或 failed",
        "机器记录编号": "留空，由程序从机器记录回填，不要手填",
        "实际结果说明": "一段话写清实际观察到什么、证明了验收条件的哪部分；只解释机器事实，不改写",
    },
    "验收条件": {
        "验收条件编号": "主题内唯一，从 AC-01 连续编号；编号会出现在生成文档小节标题与需求交付追踪表中，不得与其他行重复",
        "验收条件名称": "直白短名（不超过 20 字），写结果不写手段，例如 安装前可审查；生成文档 AC 小节标题与需求交付追踪表名称文字都取本列",
        "开始前状态": "执行本条件前可核实的数据、文件、页面或系统状态；写读者能独立核实的具体状态，取自产品设计和当前轮次事实，不写代码实现细节",
        "触发动作": "谁（用户或 AI）通过哪个产品入口（workflow 命令、文档、页面）执行什么动作；三要素缺一不可；与模板内容边界一致——不写单元测试命令、测试代码或实施步骤",
        "可检查结果": "动作后到哪里检查，必须看到哪些具体数据、文件、文档章节、返回值或状态；不许写栏目定义、门禁结果这类空词，要写到看到什么才算检查完",
        "通过标准": "哪些可检查结果同时成立才通过；数量、值、存在性、状态边界明确；禁用“功能正常”“正确处理”“符合预期”；不用 T1、stages.py 等只有开发者能懂的内部代号",
        "不通过标准": "出现哪些缺失、残留、错误值或错误状态就不通过；与通过标准逐项对应",
        "产品设计依据": "必须同时包含现有文档的 Markdown 链接和章节号或规则编号；例如 [工作记录表与正式文档生成 R18](../spec/功能_工作记录表与正式文档生成.md#r-18)；每条规则单独成链，可直接导航到规则行；链接从本主题文档出发可解析；不引用本轮内部代号",
    },
    "验收结果": {
        "验收条件编号": "与验收计划表一致，例如 AC-01",
        "验收方式": "自动化测试、人工验收或 自动化测试 + 人工验收；与该 AC 在测试计划中的测试方式一致",
        "验收结论": "passed、failed 或 blocked",
        "自动化依据": "qa/主题_测试结果.md 中证明本条的测试项和结果位置链接；纯人工验收写“不适用”",
        "机器测试记录编号": "作为本条依据的机器执行记录编号，多条用顿号分开；纯人工写“不适用”；不得写“见状态文件”",
        "用户实际回答": "人工验收时记录用户原话，不改写成“确认通过”；纯自动化写“不适用”",
        "人工确认": "通过 或 不适用；与验收记录一致",
        "实际观察结果": "实际看到什么（自动化输出、人工观察或两者组合）；写具体事实，不写“功能正常”",
        "证据": "可复核的证据说明：测试记录、运行输出、截图或文件位置",
        "验收记录编号": "留空由程序回填（workflow acceptance record 产生）；不得手写",
    },
    "人工验收步骤": {
        "验收条件编号": "对应需要用户人工判断的 AC 编号；纯自动化条件不登记本行清单",
        "验收对象": "用户实际检查什么（文档、命令输出、界面或状态）",
        "开始前条件": "执行验收前必须具备的状态或数据",
        "操作步骤": "用户按顺序执行的具体操作，一步一句，多个步骤用分号连接",
        "观察内容": "用户实际操作时观察什么",
        "预期结果": "验收条件要求看到的明确结果；与该 AC 通过标准一致",
        "用户需要回答": "要求用户确认的具体问题一句话；程序记录原话用",
    },
    "穿刺项": {
        "穿刺项编号": "例如 SP-001；与穿刺清单一致",
        "真实场景": "产品实际会遇到的接口、文件、平台、数据规模或操作路径；取自真实环境，不编造样本",
        "要验证的不确定性": "当前具体不知道什么；不写“验证可行性”这类空泛说法",
        "验证结果用于决定什么": "不同结果会改变哪项产品设计、代码计划或验证方式",
        "验证方法与命令": "真实执行的完整命令步骤，可以从项目根重复执行；不含密钥",
        "实际观察结果": "关键原始输出、返回字段、测量数据、失败行为和限制；不只写结论",
        "结论": "根据实际证据确认了什么",
        "结果状态": "已确认、限制已确认或仍未确认；与模板“结果状态说明”一致",
        "是否阻塞后续": "是 或 否；为“是”时穿刺环节不能完成",
        "产品设计影响": "需要修改 或 无需修改",
        "代码设计影响": "需要修改 或 无需修改",
        "剩余风险": "无，或当前仍然存在的具体风险；结果状态为“仍未确认”时必填",
        "后续处理阶段": "无 或 impl、qa 等阶段标识；“仍未确认”不阻塞时必填",
        "后续需要检查什么": "无，或到后续阶段必须检查的具体内容",
    },
    "可复用资产": {
        "资产目录": ".workflow_loop/spike_tmp/<workflow_id>/<穿刺项文件标识>/ 固定格式；一个穿刺项一个目录",
        "用途": "怎样用它重新取得本次结论",
        "运行方法": "从项目根可以实际执行的完整命令",
        "依赖与非敏感输入": "依赖版本与非敏感输入怎样准备；没有额外依赖也要明确说明",
        "不保留内容": "确认未保留敏感数据、缓存、日志和纯结果输出",
        "支撑验收条件": "本阶段写“待验收计划关联”；不提前编造 AC 编号",
    },
    "缺陷信息": {
        "缺陷编号": "例如 BUG-01；一份缺陷记录一个编号",
        "现象": "用户在什么操作中看到了什么问题",
        "复现步骤": "从真实入口开始、到缺陷出现的可重复操作，一步一句用分号连接",
        "实际结果": "实际输出、状态、日志、界面或错误；写观察到的事实",
        "期望结果": "根据已确认产品设计本来应该得到什么；与产品设计文档一致",
        "根因": "旧版表必须在同一格分别写 根因说明：内容、根因位置：内容、根因证据：内容；位置写真实文件及函数，证据取真实运行或代码事实；三个标签不可省略",
        "根因说明": "导致缺陷的具体判断、状态、数据、配置或外部行为；只填事实内容，不写根因说明等固定标签",
        "根因位置": "真实代码文件及函数、类或配置项；只填位置内容，不写固定标签",
        "根因证据": "能够核实根因的实际运行输出、输入对照或代码证据；只填事实，不重复标签",
    },
    "核对项": {
        "核对项": "例如 产品功能与真实代码映射；逐项列出需要核对的设计与代码事实",
        "核对结论": "一致或不一致的说明；不一致时写具体差异和证据位置",
        "设计影响": "需要修改 或 无需修改；与是否改动架构文档一致",
        "代码影响": "需要修改 或 无需修改；与实际代码改动一致",
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

_LEGACY_KIND_SCHEMAS: dict[str, dict] = {
    "impl_record": {
        "doc_name": "实施记录",
        "row_lists": {
            "代码修改计划": {
                "columns": [
                    "文件",
                    "计划修改内容",
                    "对应验收条件"
                ],
                "key_column": "文件",
                "required_at_gate": True
            },
            "实际代码修改": {
                "columns": [
                    "文件",
                    "代码位置（最终文件）",
                    "实际修改的代码逻辑",
                    "数据、状态或输出的实际变化",
                    "修改理由",
                    "对应验收条件",
                    "测试证据"
                ],
                "key_column": "文件",
                "required_at_gate": True,
                "line_range_column": "代码位置（最终文件）"
            }
        },
        "narrative": [
            "实施动作记录",
            "实施中问题与处理"
        ],
        "enums": {
            "未完成状态": [
                "状态：无",
                "状态：有"
            ]
        }
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
                    "对应验收条件"
                ],
                "optional_columns": [
                    "工作目录"
                ],
                "key_column": "测试项编号",
                "required_at_gate": False
            }
        },
        "narrative": [
            "测试范围说明"
        ],
        "enums": {}
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
                    "产品设计依据"
                ],
                "key_column": "验收条件编号",
                "required_at_gate": True
            }
        },
        "narrative": [
            "验收目标说明"
        ],
        "enums": {}
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
                    "结论"
                ],
                "key_column": "穿刺项编号",
                "required_at_gate": True
            }
        },
        "narrative": [
            "结论说明"
        ],
        "enums": {}
    },
    "bug_record": {
        "doc_name": "缺陷记录",
        "row_lists": {
            "缺陷信息": {
                "columns": [
                    "缺陷编号",
                    "现象",
                    "复现步骤",
                    "预期行为",
                    "根因"
                ],
                "key_column": "缺陷编号",
                "required_at_gate": True
            }
        },
        "narrative": [
            "缺陷说明"
        ],
        "enums": {}
    },
    "design_sync": {
        "doc_name": "最终设计同步结论",
        "row_lists": {
            "核对项": {
                "columns": [
                    "核对项",
                    "核对结论",
                    "设计影响",
                    "代码影响"
                ],
                "key_column": "核对项",
                "required_at_gate": True
            }
        },
        "narrative": [
            "同步说明"
        ],
        "enums": {}
    },
    "product_features": {
        "doc_name": "产品功能清单",
        "row_lists": {
            "功能": {
                "columns": [
                    "功能名称",
                    "一句话说明",
                    "对应场景",
                    "功能文档路径"
                ],
                "key_column": "功能名称",
                "required_at_gate": True
            }
        },
        "narrative": [],
        "enums": {}
    },
    "test_result": {
        "doc_name": "测试结果",
        "row_lists": {
            "测试结果": {
                "columns": [
                    "测试项编号",
                    "执行结论",
                    "机器记录编号",
                    "实际结果说明"
                ],
                "optional_columns": [
                    "机器记录编号"
                ],
                "key_column": "测试项编号",
                # R11：测试结果行是 qa 环节的核心产出，空表必须报"尚未填写"，
                # 不能静默放行（否则下游整体验收才发现文档缺失，被迫退回 qa 重走）
                "required_at_gate": True
            }
        },
        "narrative": [
            "结果说明"
        ],
        "enums": {}
    },
    "acceptance_result": {
        "doc_name": "验收结果",
        "row_lists": {
            "验收结果": {
                "columns": [
                    "验收条件编号",
                    "验收结论",
                    "实际观察结果",
                    "证据"
                ],
                "key_column": "验收条件编号",
                "required_at_gate": True
            }
        },
        "narrative": [
            "验收说明"
        ],
        "enums": {}
    },
    "topic_relations": {
        "doc_name": "主题关系",
        "row_lists": {
            "主题关系": {
                "columns": [
                    "验收主题",
                    "前置主题"
                ],
                "key_column": "验收主题",
                "required_at_gate": True
            }
        },
        "narrative": [],
        "enums": {}
    }
}


_LEGACY_COLUMN_HINTS: dict[str, dict[str, str]] = {
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
WORKFLOW_LEVEL_KINDS = {"product_features", "topic_relations", "spike_conclusion", "bug_record", "design_sync", "architecture_changes"}

FORMAT_CATEGORY = "格式问题"
CONTENT_CATEGORY = "内容问题"

# 断言九/R4：枚举列的合法值（validate_table 逐列校验，不只查非空）
_ENUM_COLUMNS: dict[str, set[str]] = {
    "执行结论": {"passed", "failed"},
    "验收结论": {"passed", "failed", "blocked"},
    "测试方式": {"自动化测试", "人工验收", "自动化测试 + 人工验收"},
    "验收方式": {"自动化测试", "人工验收", "自动化测试 + 人工验收"},
    "是否需要继续修改": {"是", "否"},
}

# 断言九/R4：列的类型约束（validate_table 逐列校验，不只查非空）
_TYPE_COLUMNS: dict[str, str] = {
    "命令参数数组": "json_array",
    "超时秒数": "int",
    # 登记入口的形状与文档模式同一口径（R15）；判断标准在 test_mapping 里定义一次。
    "正式目标名称": "test_entries",
}

# ── R19 表门禁实质内容校验（仅对表版本 2 生效；v1 冻结轮次维持旧口径）──
# ① 占位词表：命中即按内容问题拒绝（程序维护的明确清单）。
_PLACEHOLDER_WORDS = {
    "无", "暂无", "待定", "待补充", "见状态文件", "见测试结果",
    "功能正常", "正确处理", "符合预期",
}
# 仅由标点、空白或编号组成的值同样视为占位（R19 第①条）。
_REFERENCE_ONLY_RE = re.compile(r"^(?:[\s\W]*|[A-Za-z]{0,3}[0-9]{1,3}[：:]?)$")

# 模板声明允许整栏写“暂无”的栏目（“确无内容”语义栏）：出现“暂无”按空处理，
# 必填的仍受③拒绝，不填必填的放行（R19 第①条除外规则）。
_NARRATIVE_ALLOW_NO_CONTENT: dict[str, set[str]] = {
    "impl_record": {"未决问题", "实施中问题与处理"},
    "test_plan": {"未决测试条件", "针对性回归范围"},
    "test_result": {"未通过或阻塞"},
    "bug_record": {"修复仍存在的不确定性"},
}

# ② 自由描述列：按 schema 逐栏声明的最小信息量（最低长度，字符数）。
#    编号引用列、枚举列和机器执行列不受此约束（_ENUM_COLUMNS/_TYPE_COLUMNS 自动豁免）。
_FREE_DESCRIPTION_COLUMNS: dict[str, int] = {
    "已确认做法": 12,
    "具体内容": 12,
    "计划修改内容": 12,
    "数据、状态或输出变化": 8,
    "实际执行的动作": 12,
    "修改理由": 12,
    "实际修改的代码逻辑": 12,
    "数据、状态或输出的实际变化": 8,
    "预期观察结果": 8,
    "实际反馈": 8,
    "通过标准": 12,
    "不通过标准": 8,
    "可检查结果": 8,
    "开始前状态": 8,
    "触发动作": 8,
    "选择理由": 8,
    "结果说明": 12,
    "执行说明": 12,
    "人工验收交接": 12,
    "未通过或阻塞": 12,
    "验收说明": 12,
    "结论说明": 12,
    "同步说明": 12,
    "缺陷说明": 12,
    "真实复现条件": 12,
    "根因证据": 12,
    "根因说明": 12,
    "根因位置": 8,
    "运行环境": 8,
    "真实输入": 8,
    "修复仍存在的不确定性": 12,
    "修复与验收结果": 12,
    "预期产品结果": 12,
    "实施中问题与处理": 12,
    "未决问题": 12,
    "测试范围说明": 12,
    "测试条件要求": 12,
    "未决测试条件": 12,
    "针对性回归范围": 12,
    "验收目标说明": 12,
    "需求来源": 12,
    "产品设计依据": 12,
    "本主题验收": 12,
    "本主题不验收": 12,
    "完成判定": 12,
    "核对对象": 8,
    "核对依据": 12,
}

# ③ 门禁必填的叙述栏（空数组即内容问题拒绝；R19 第③条清单）。
_GATE_REQUIRED_NARRATIVE: dict[str, list[str]] = {
    "impl_record": ["预期产品结果", "未决问题"],
    "test_plan": ["测试范围说明"],
    "acceptance_plan": [
        "需求来源", "验收目标说明", "产品设计依据",
        "本主题验收", "本主题不验收", "完成判定",
    ],
    "test_result": ["结果说明"],
    "acceptance_result": ["验收说明"],
    "spike_conclusion": ["结论说明"],
    "bug_record": [
        "缺陷说明", "真实复现条件", "根因证据",
        "修复仍存在的不确定性", "修复与验收结果",
    ],
    "design_sync": ["同步说明"],
}


_PLACEHOLDER_ALLOWED_VALUES: dict[str, set[str]] = {
    # 栏位填写说明明确允许的"确无"值（R19 第①条除外口径，不扩大到自由描述栏）。
    "前置步骤": {"无"},
    "前置测试项": {"无"},
}

# ⑥ 纯流程主题豁免（版本 2）：impl_record"代码修改计划"行的"文件"列填本标记
# 表示该主题本轮不产生代码修改（验收重做、发布核对等流程动作）。
FLOW_ONLY_MARKER = "无代码修改（流程动作）"
# 豁免时不要求非空的代码结果类行清单；其余栏位（实施依据、代码修改计划、
# 预期产品结果、未决问题）仍按①-④检查。
_FLOW_ONLY_EXEMPT_ROW_LISTS = {"实施动作记录", "实际代码修改", "开发检查计划", "开发检查记录"}


def is_flow_only_plan_row(row: dict) -> bool:
    """代码修改计划行是否为纯流程标记行（R19⑥）。"""
    return str(row.get("文件", "")).strip() == FLOW_ONLY_MARKER


def impl_table_exempts_code_result_lists(table: dict) -> bool:
    """impl_record 表是否为纯流程主题：代码修改计划行全部是标记行。

    空行清单不算纯流程（由 required_at_gate 的"至少一行"先报错）；标记行与
    真实代码行混合时返回 False——混合表由 validate_table 单独报错，任何豁免
    都不生效，防止用标记绕过代码记录。
    """
    rows = [r for r in (table.get("代码修改计划") or []) if isinstance(r, dict)]
    if not rows:
        return False
    return all(is_flow_only_plan_row(r) for r in rows)


def _is_placeholder_value(value: str) -> bool:
    stripped = value.strip()
    if stripped in _PLACEHOLDER_WORDS:
        return True
    return bool(_REFERENCE_ONLY_RE.fullmatch(stripped))


def _substantive_problems(
    kind: str,
    location: str,
    column: str,
    value: str,
    problems: list[tuple[str, str]],
    *,
    free_minimum: bool = True,
) -> None:
    """R19 第①②条：单元格值的占位词与最小信息量检查（版本 2 表专用）。"""
    allowed = _PLACEHOLDER_ALLOWED_VALUES.get(column, set())
    if value.strip() in allowed:
        return
    if _is_placeholder_value(value):
        problems.append((
            CONTENT_CATEGORY,
            f"{location} 的 {column} 值 {value.strip()!r} 是占位词；请写具体内容（是什么、在哪里、结果如何）",
        ))
        return
    minimum = _FREE_DESCRIPTION_COLUMNS.get(column) if free_minimum else None
    if minimum is None:
        return
    stripped = value.strip()
    # 纯编号/标点形态（如 "AC-01"、"1"）不满足自由描述要求（R19 第①条编号值）。
    if re.fullmatch(r"[A-Za-z]{0,4}[0-9]{1,3}(?:[、，,;；.][A-Za-z]{0,4}[0-9]{1,3})*[：:]?", stripped):
        problems.append((
            CONTENT_CATEGORY,
            f"{location} 的 {column} 值 {stripped!r} 只是编号引用；自由描述栏需要说明实质内容",
        ))
        return
    if len(stripped) < minimum:
        problems.append((
            CONTENT_CATEGORY,
            f"{location} 的 {column} 值 {stripped!r} 不足 {minimum} 个字符的最小信息量；请写完整说明",
        ))


class RecordsError(ValueError):
    """表读取或解析失败；调用方把它转为结构化门禁问题，不能裸崩。"""


def records_dir(project_root: str, workflow_id: str) -> str:
    return os.path.join(project_root, RECORDS_ROOT, workflow_id)


def table_relative_path(project_root: str, workflow_id: str, kind: str, topic: str) -> str:
    file_key = topic_file_key(project_root, topic) if topic else kind
    return f"{RECORDS_ROOT}/{workflow_id}/{kind}_{file_key}.json"


def _storage_topic(project_root: str, kind: str, table: dict) -> str:
    topic = str(table.get("验收主题", ""))
    if kind == "bug_record" and topic:
        # 旧单表的主题填写在基础文件中；保留其路径，不把已有凭据迁到新主题路径。
        legacy = table_relative_path(project_root, str(table.get("工作流编号", "")), kind, "")
        if table_exists(project_root, legacy):
            stored = load_table(os.path.join(project_root, legacy))
            if stored.get("验收主题") == topic:
                return ""
        return topic
    return "" if kind in WORKFLOW_LEVEL_KINDS else topic


def bug_record_tables(
    project_root: str,
    workflow_id: str,
    required_topics: list[str] | None = None,
) -> tuple[list[tuple[str, str]], list[tuple[str, dict]]]:
    """发现本轮全部缺陷表并核对身份；仅忽略完全未填的无主题初始表。"""
    directory = records_dir(project_root, workflow_id)
    problems: list[tuple[str, str]] = []
    tables: list[tuple[str, dict]] = []
    seen_topics: dict[str, str] = {}
    seen_documents: dict[str, str] = {}
    base = table_relative_path(project_root, workflow_id, "bug_record", "")
    for name in sorted(os.listdir(directory)) if os.path.isdir(directory) else []:
        if not name.startswith("bug_record_") or not name.endswith(".json"):
            continue
        relative = f"{RECORDS_ROOT}/{workflow_id}/{name}"
        try:
            table = load_table(os.path.join(project_root, relative))
        except RecordsError as exc:
            problems.append((FORMAT_CATEGORY, str(exc)))
            continue
        if table.get("工作流编号") != workflow_id:
            problems.append((CONTENT_CATEGORY, f"{relative} 的工作流编号与当前轮次 {workflow_id} 不一致"))
            continue
        topic = table.get("验收主题")
        schema = _schema("bug_record", _table_version_of(table))
        fact_keys = set(schema["row_lists"]) | set(schema["narrative"])
        if (
            relative == base and topic == ""
            and str(table.get("表版本")) == _workflow_table_version(project_root, workflow_id)
            and all(table.get(key) == [] for key in fact_keys)
            and not any(_generation_fields(table).values())
            and not (set(table) - fact_keys - {"表版本", "工作流编号", "验收主题", "填写说明", *PROGRAM_FIELD_KEYS})
        ):
            continue
        if not isinstance(topic, str) or not topic.strip():
            problems.append((CONTENT_CATEGORY, f"{relative} 必须填写唯一验收主题；有缺陷事实的基础表不能作为空表跳过"))
            continue
        if topic != topic.strip():
            problems.append((CONTENT_CATEGORY, f"{relative} 的验收主题不能带首尾空白"))
        expected = table_relative_path(project_root, workflow_id, "bug_record", topic)
        if relative not in {base, expected}:
            problems.append((CONTENT_CATEGORY, f"{relative} 的主题与文件标识不一致；主题「{topic}」应使用 {expected}"))
        if topic in seen_topics:
            problems.append((CONTENT_CATEGORY, f"{relative} 与 {seen_topics[topic]} 使用重复主题「{topic}」"))
        seen_topics[topic] = relative
        document = f"bug/缺陷_{bug_file_key(project_root, topic)}.md"
        if document in seen_documents:
            problems.append((CONTENT_CATEGORY, f"缺陷文件标识冲突：{relative} 与 {seen_documents[document]} 都指向 {document}"))
        seen_documents[document] = relative
        tables.append((relative, table))
    for topic in required_topics or []:
        if topic and topic not in seen_topics:
            relative = table_relative_path(project_root, workflow_id, "bug_record", topic)
            problems.append((CONTENT_CATEGORY, f"主题「{topic}」缺少缺陷记录工作记录表（{relative}）"))
    return problems, tables


# 表格式版本 → schema/hints。版本 1 是历史轮次冻结使用的快照，保留用于按冻结版本
# 校验和生成旧表（R18：版本 2 只对开工时冻结为版本 2 的轮次生效，旧轮次不迁移）。
_SUPPORTED_TABLE_VERSIONS = {"1", "2", "3", "4"}

# 采集指纹键（R25）：实施记录表内程序专用的机器采集记录，AI 不填写。
COLLECTION_FINGERPRINT_KEY = "采集指纹"


def _schema(kind: str, version: str | None = None) -> dict:
    version = version or TABLE_FORMAT_VERSION
    if kind == "architecture_changes":
        return KIND_SCHEMAS[kind]
    schemas = _LEGACY_KIND_SCHEMAS if version == "1" else KIND_SCHEMAS
    if kind not in schemas:
        raise RecordsError(f"未知的工作记录表类型：{kind}")
    if kind == "bug_record" and version == "3":
        return {
            "doc_name": "缺陷记录",
            "row_lists": {"缺陷信息": {
                "columns": ["缺陷编号", "现象", "复现步骤", "实际结果", "期望结果", "根因说明", "根因位置", "根因证据"],
                "key_column": "缺陷编号", "required_at_gate": True,
            }},
            "narrative": ["缺陷说明", "运行环境", "真实输入", "真实复现条件", "修复仍存在的不确定性", "修复与验收结果"],
            "enums": {},
        }
    return schemas[kind]


def _hints_for(version: str | None) -> dict[str, dict[str, str]]:
    return _LEGACY_COLUMN_HINTS if (version or TABLE_FORMAT_VERSION) == "1" else COLUMN_HINTS


def _table_version_of(table: dict) -> str:
    """表内登记的版本；旧表没有该栏目时按版本 1 处理。"""
    value = str(table.get("表版本") or "1").strip()
    return value if value in _SUPPORTED_TABLE_VERSIONS else TABLE_FORMAT_VERSION


def _workflow_table_version(project_root: str, workflow_id: str) -> str:
    """本工作流开工冻结的表版本（AC-03）。

    进行中轮次一律用 state 冻结的版本判定格式与建表；冻结早于本机制、但本轮已经
    建出旧版本表的工作流，按磁盘上已有的最高旧版本判定（不升级到当前版本，
    保证门禁不因程序升级要求补新栏位或报版本错误）；没有任何表的新轮次用当前版本。
    """
    state = state_mod.load_state(project_root)
    if state is not None and getattr(state, "table_format_version", None):
        return str(state.table_format_version)
    directory = records_dir(project_root, workflow_id)
    if os.path.isdir(directory):
        versions: list[str] = []
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            try:
                data = json.loads(open(os.path.join(directory, name), encoding="utf-8").read())
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("表版本"):
                versions.append(str(data["表版本"]).strip())
        if versions and all(v in _SUPPORTED_TABLE_VERSIONS for v in versions):
            return max(versions)
    return TABLE_FORMAT_VERSION


def _fixed_fields(workflow_id: str, topic: str, version: str | None = None) -> dict[str, str]:
    return {
        "表版本": version or TABLE_FORMAT_VERSION,
        "工作流编号": workflow_id,
        "验收主题": topic,
        DOC_HASH_KEY: None,
        GENERATED_DOC_PATH_KEY: None,
    }


def migrate_rows(kind: str, table: dict, version: str | None = None) -> bool:
    """行迁移（仅版本 2）：行清单按 schema 定义补齐缺失列为空串、剔除未知列。

    只在"栏目集合不一致"时修正行本身，不改写有值的栏位内容；
    已填写的信息不丢失（旧 3 列计划行迁移为新 8 列，新增列为空待填）。
    返回是否发生修改。"""
    if (version or _table_version_of(table)) != "2":
        return False
    schema = _schema(kind, "2")
    changed = False
    for key, definition in schema["row_lists"].items():
        columns = definition["columns"]
        rows = table.get(key)
        if not isinstance(rows, list):
            continue
        new_rows: list = []
        list_changed = False
        for row in rows:
            if isinstance(row, dict) and set(row) != set(columns):
                row = {c: row.get(c, "") for c in columns}
                list_changed = True
            new_rows.append(row)
        if list_changed:
            table[key] = new_rows
            changed = True
    return changed


def _build_hints(schema: dict, hints_map: dict[str, dict[str, str]], kind: str = "", version: str = "") -> dict[str, object]:
    hints: dict[str, object] = {}
    for key in schema["row_lists"]:
        hints[key] = {
            c: hints_map.get(key, {}).get(c, "按栏目含义填写")
            for c in schema["row_lists"][key]["columns"]
        }
    for key in schema["narrative"]:
        hints[key] = NARRATIVE_HINT
    if version != "1":
        if kind == "bug_record":
            hints["修复仍存在的不确定性"] = "写仍未查清且影响修复的技术问题；确实没有时整栏只写一条“暂无”，不能留空或混入占位词"
            hints["修复与验收结果"] = "复现阶段只说明本节由后续验收阶段按实际结果追加，不提前填写修复成功"
            if version == "3":
                hints["运行环境"] = "写真实操作系统、工具版本和必要配置，一段一条；不写运行环境：等固定标签"
                hints["真实输入"] = "写触发缺陷的实际输入及来源，一段一条；不写真实输入：等固定标签"
                hints["真实复现条件"] = "可补充代码基线、前置状态等其他真实条件；运行环境和真实输入填各自独立栏，此栏无补充时留空数组"
            else:
                hints["真实复现条件"] = "旧版表至少分别写两条：运行环境：实际环境、真实输入：实际输入；标签与内容必须在同一条同一行，不能省略固定标签"
        if kind == "design_sync":
            hints["核对项"] = {
                "核对项": "分别填写产品设计核对、功能文档核对、代码实现核对、功能到代码映射、未处理差异、本次同步类型六项",
                "核对结论": "前三项填一致；映射填完整；未处理差异填暂无；同步类型填架构变化或架构未变化；存在差异时先返回对应阶段处理",
                "设计影响": "需要修改 或 无需修改；需要修改正文时另填架构正文变更表",
                "代码影响": "最终同步只处理设计；确认无需修改代码才填无需修改，否则先返回实施",
            }
            hints["同步说明"] = "写最终设计核对依据；机器记录编号由程序每次生成时从当前有效状态重新取得完整精确集合，不要手填或沿用旧编号；不能把旧记录写成当前有效记录"
    if kind == "architecture_changes":
        hints["正文变更"] = {
            "章节": "填写正式架构中唯一存在的完整章节标题，不带井号；不能填写最终同步结论章节",
            "原文": "从该章节复制需变更的原事实，必须唯一匹配；多行原文保留换行；不能仅填已替换后的新文",
            "新文": "填写已经实现并核实的新事实，不改原章节标题、表格结构或定位锚点",
            "依据": "填写真实代码位置、核对结果或验收依据；无正文变化时正文变更留空数组",
        }
    hints["程序专用字段"] = "生成文档路径、生成文档哈希、缺陷文档哈希由程序维护，不要填写或改动；填写事实后让程序生成，已有程序值保持原样"
    return hints


def create_or_complete_table(
    project_root: str,
    workflow_id: str,
    kind: str,
    topic: str = "",
) -> str:
    """生成空表；表已存在时补缺失栏目并按冻结版本迁移行栏目，不覆盖已填内容。

    版本判定用本轮开工冻结的版本（R11/R18/AC-03）：冻结 1 的轮次补栏目、迁移、
    填写说明全部按版本 1 口径；冻结 2 的轮次按版本 2 口径并把旧行迁移到新列集合。
    返回表相对路径。"""
    version = _workflow_table_version(project_root, workflow_id)
    schema = _schema(kind, version)
    relative = table_relative_path(project_root, workflow_id, kind, topic)
    full = os.path.join(project_root, relative)
    if os.path.exists(full):
        table = load_table(full)
        if table.get("工作流编号", workflow_id) != workflow_id:
            raise RecordsError(f"{relative} 已属于其他工作流，不能覆盖或补写为当前轮次")
        if not (kind == "bug_record" and not topic) and table.get("验收主题", topic) != topic:
            raise RecordsError(f"{relative} 的主题与请求主题「{topic}」冲突，不能覆盖已填表")
        # 已存在的表按其自身登记版本补齐（R18：版本 1 表保持现状不迁移）
        table_version = _table_version_of(table)
        schema = _schema(kind, table_version)
        changed = False
        for key, value in _fixed_fields(workflow_id, topic, table_version).items():
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
        # 行迁移：栏目集合与 schema 不一致的行按新列补齐/剔除（已填值保留）
        if migrate_rows(kind, table, table_version):
            changed = True
        # 填写说明缺失，或版本 2 表在 schema 演进后缺某个栏位的说明时按栏位重建
        current_hints = table.get("填写说明")
        expected_hints = _build_hints(schema, _hints_for(table_version), kind, table_version)
        if current_hints != expected_hints:
            table["填写说明"] = expected_hints
            changed = True
        if not _program_field_problems(project_root, kind, table):
            _save_generation_receipt(project_root, kind, table)
        if changed:
            _atomic_write(full, table)
        return relative
    if kind == "bug_record" and topic:
        identity_problems, existing = bug_record_tables(project_root, workflow_id)
        if identity_problems:
            raise RecordsError("；".join(detail for _, detail in identity_problems))
        for existing_relative, existing_table in existing:
            if existing_table["验收主题"] == topic:
                raise RecordsError(f"主题「{topic}」已经使用 {existing_relative}，不能另建重复缺陷表")
            if bug_file_key(project_root, existing_table["验收主题"]) == bug_file_key(project_root, topic):
                raise RecordsError(f"主题「{topic}」与 {existing_relative} 的缺陷文件标识冲突")
    table: dict = _fixed_fields(workflow_id, topic, version)
    for key in schema["row_lists"]:
        table[key] = []
    for key in schema["narrative"]:
        table[key] = []
    for key in schema["enums"]:
        table[key] = schema["enums"][key][0]
    table["填写说明"] = _build_hints(schema, _hints_for(version), kind, version)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    _atomic_write(full, table)
    _save_generation_receipt(project_root, kind, table)
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


def no_change_declaration(
    project_root: str,
    workflow_id: str,
    kind: str,
    topic: str,
) -> dict | None:
    """读取主题级工作记录表的“核对结论：无需修改”声明（推进 R47）。

    返回声明的首个声明行（核对对象、核对依据）；表不存在、没有声明行或
    声明行不完整时返回 None。依据是否有实质内容由调用方配合 R19 实质校验
    判断；本函数只负责把声明事实取出来。
    """
    relative = table_relative_path(project_root, workflow_id, kind, topic)
    if not table_exists(project_root, relative):
        return None
    try:
        table = load_table(os.path.join(project_root, relative))
    except RecordsError:
        return None
    rows = table.get("核对结论")
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    target = str(first.get("核对对象", "")).strip()
    rationale = str(first.get("核对依据", "")).strip()
    if not target or not rationale:
        return None
    return {"核对对象": target, "核对依据": rationale}


def declaration_rationale_has_substance(rationale: str) -> bool:
    """声明的核对依据是否有实质内容（推进 R47：不能拿占位词当依据）。

    与 R19 的占位词清单同源：命中占位词或只有标点编号的依据不算实质内容。
    """
    value = rationale.strip()
    if not value:
        return False
    if value in _PLACEHOLDER_WORDS:
        return False
    if _REFERENCE_ONLY_RE.match(value):
        return False
    return len(value) >= 12


def validate_table(kind: str, table: dict, expected_version: str | None = None, *, project_root: str = "") -> list[tuple[str, str]]:
    """校验一张表，返回 (类别, 问题) 列表；类别为格式问题或内容问题。

    expected_version 是本轮开工冻结的表版本（R11）：表版本必须等于冻结版本且
    为程序支持的版本；schema 按冻结版本选择，进行中轮次不因程序升级报新栏位缺失。
    """
    expected_version = expected_version or _table_version_of(table)
    if expected_version not in _SUPPORTED_TABLE_VERSIONS:
        return [(
            CONTENT_CATEGORY,
            f"本工作流冻结的表版本 {expected_version!r} 不是程序支持的版本（支持 {'、'.join(sorted(_SUPPORTED_TABLE_VERSIONS))}）",
        )]
    schema = _schema(kind, expected_version)
    problems: list[tuple[str, str]] = _program_field_problems(project_root, kind, table)
    allowed = set(schema["row_lists"]) | set(schema["narrative"]) | set(schema["enums"])
    allowed |= {
        "表版本", "工作流编号", "验收主题", "填写说明",
        DOC_HASH_KEY, GENERATED_DOC_PATH_KEY, BUG_DOC_HASHES_KEY,
    }
    # R25（v4）：实施记录表的采集指纹是程序专用键，AI 不填写。
    if kind == "impl_record" and expected_version == "4":
        allowed.add(COLLECTION_FINGERPRINT_KEY)
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
        elif key == "表版本" and value.strip() != expected_version:
            problems.append(
                (CONTENT_CATEGORY, f"固定栏目 表版本 必须是本轮冻结的 {expected_version}，实际为 {value.strip()!r}")
            )
    # R19⑥：纯流程主题（版本 2 impl_record）计划行全部填标记时，
    # 代码结果类行清单不要求非空；标记与真实代码行混表按普通内容报错。
    flow_only_exempt = (
        kind == "impl_record"
        and expected_version != "1"
        and impl_table_exempts_code_result_lists(table)
    )
    if kind == "impl_record" and expected_version != "1":
        plan_rows = [r for r in (table.get("代码修改计划") or []) if isinstance(r, dict)]
        marked = [r for r in plan_rows if is_flow_only_plan_row(r)]
        if marked and len(marked) != len(plan_rows):
            problems.append((
                CONTENT_CATEGORY,
                f"代码修改计划 同时存在标记行（{FLOW_ONLY_MARKER}）与真实代码行；"
                "纯流程标记只在全部计划行都是标记时生效，混合表按普通行核对代码记录",
            ))
    for key, definition in schema["row_lists"].items():
        rows = table.get(key)
        if rows is None and not definition.get("required_at_gate", False):
            # 可选行清单（如"核对结论"声明行，R47）：表里没有该键视为未声明，
            # 不要求 AI 预填空数组；旧版本表升级后也不会因缺新栏位报格式问题。
            continue
        if not isinstance(rows, list):
            problems.append((FORMAT_CATEGORY, f"栏目 {key} 必须是行数组"))
            continue
        columns = definition["columns"]
        key_column = definition["key_column"]
        seen_keys: set[str] = set()
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or set(row) != set(columns):
                problems.append((
                    FORMAT_CATEGORY,
                    f"{key} 第 {index} 行栏目与定义不符；允许栏目：{columns}",
                ))
                continue
            key_value = str(row.get(definition["key_column"], "")).strip()
            if definition.get("key_columns"):
                key_value = json.dumps([row[column] for column in definition["key_columns"]], ensure_ascii=False)
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
            # 条件可选（R8）：某控制列取特定值时，关联列允许为空。
            # 控制列本身未填时不放大可选范围，让控制列的"未填写"先报错。
            for control, by_value in definition.get("conditional_optional_by_column", {}).items():
                control_value = str(row.get(control, "")).strip()
                if control_value in by_value:
                    optional |= set(by_value[control_value])
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
                    elif _ttype == "test_entries" and expected_version != "1":
                        from . import test_mapping as test_mapping_mod

                        _, entry_problem = test_mapping_mod.parse_official_target_names(
                            row.get(column)
                        )
                        if entry_problem:
                            # 带上行键（测试项编号），让按表登记的失败清单能直接定位到 TC。
                            row_key = str(row.get(key_column, "")).strip()
                            location = f"{key} 第 {index} 行"
                            if row_key:
                                location += f"（{key_column} {row_key}）"
                            problems.append((
                                FORMAT_CATEGORY,
                                f"{location}的 {entry_problem}",
                            ))
                if column == definition.get("line_range_column"):
                    bare = value.removeprefix("基线").strip()
                    if (re.match(r"^[Ll][ \t]*[0-9]", bare)
                            and LINE_RANGE_RE.fullmatch(bare) is None):
                        problems.append((
                            CONTENT_CATEGORY,
                            f"{key} 第 {index} 行的 {column} {value!r} 不符合 L起始-L结束 格式，例如 L12-L34",
                        ))
                # R19 第①②条（版本 2）：自由描述列拒绝占位词与不达标的最小信息量。
                if expected_version != "1" and column in _FREE_DESCRIPTION_COLUMNS:
                    _substantive_problems(
                        kind, f"{key} 第 {index} 行", column, value, problems
                    )
        if (
            definition.get("required_at_gate")
            and not rows
            and not (flow_only_exempt and key in _FLOW_ONLY_EXEMPT_ROW_LISTS)
        ):
            problems.append((CONTENT_CATEGORY, f"栏目 {key} 至少需要一行记录"))
    for key in schema["narrative"]:
        paragraphs = table.get(key)
        if not isinstance(paragraphs, list):
            problems.append((FORMAT_CATEGORY, f"栏目 {key} 必须是段落数组（一段一条）"))
            continue
        if expected_version == "1":
            continue
        filled = [str(p) for p in paragraphs if str(p).strip()]
        allow_no_content = key in _NARRATIVE_ALLOW_NO_CONTENT.get(kind, set())
        no_content = allow_no_content and len(paragraphs) == 1 and len(filled) == 1 and filled[0].strip() == "暂无"
        content_paragraphs = [] if no_content else filled
        for paragraph in content_paragraphs:
            _substantive_problems(kind, f"叙述栏 {key}", key, paragraph, problems)
        required = _GATE_REQUIRED_NARRATIVE.get(kind, [])
        if kind == "bug_record" and expected_version == "3":
            required = ["缺陷说明", "运行环境", "真实输入", "修复仍存在的不确定性", "修复与验收结果"]
        if key in required and not content_paragraphs and not (allow_no_content and filled):
            problems.append((
                CONTENT_CATEGORY,
                f"叙述栏 {key} 是门禁必填栏，当前为空；请填写实质内容"
                + ("（确无内容时整栏写“暂无”）" if allow_no_content else ""),
            ))
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


def _generate_document_v1(kind: str, table: dict, *, project_root: str = "") -> str:
    """版本 1 表的渲染（历史轮次冻结口径，与升级前的生成器逐字节一致；不再扩展）。"""
    schema = _schema(kind, "1")
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
            cells = {**{c: "" for c in _LEGACY_KIND_SCHEMAS["impl_record"]["row_lists"]["代码修改计划"]["columns"]}, **row}
            cols = _LEGACY_KIND_SCHEMAS["impl_record"]["row_lists"]["代码修改计划"]["columns"]
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
            cells = {**{c: "" for c in _LEGACY_KIND_SCHEMAS["impl_record"]["row_lists"]["实际代码修改"]["columns"]}, **row}
            cols = _LEGACY_KIND_SCHEMAS["impl_record"]["row_lists"]["实际代码修改"]["columns"]
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




def generate_document(kind: str, table: dict, *, project_root: str = "", wf_state=None) -> str:
    """按表生成正式文档；版本 1 表用冻结时的旧渲染，版本 2 表按环节模板全章节渲染（R16/R18）。"""
    if _table_version_of(table) == "1":
        content = _generate_document_v1(kind, table, project_root=project_root)
    else:
        content = _generate_document_v2(kind, table, project_root=project_root, wf_state=wf_state)
    return markdown_links_mod.with_heading_anchors(content)


def _render_rows(section_lines: list[str], columns: list[str], rows: list[dict]) -> None:
    section_lines += ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        cells = {**{c: "" for c in columns}, **(row if isinstance(row, dict) else {})}
        section_lines.append("| " + " | ".join(_md_cell(cells[c]) for c in columns) + " |")


def _declaration_section(table: dict) -> list[str]:
    """渲染“核对结论：无需修改”声明为核对记录一节（推进 R47 / 表 R30）。

    表里没有声明行时返回空列表——正常修改流程的文档不出现该节。
    """
    rows = table.get("核对结论")
    if not isinstance(rows, list) or not rows:
        return []

    def _one_line(value) -> str:
        return re.sub(r"\s*\r?\n\s*", " ", str(value)).strip()

    lines = ["", '<a id="核对记录"></a>', "## 核对记录", "",
             "本主题在退回后重新核对，确认产物无需修改（声明依据如下）。", ""]
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(f"- 核对对象：{_one_line(row.get('核对对象', ''))}")
        lines.append(f"- 核对依据：{_one_line(row.get('核对依据', ''))}")
        lines.append("")
    return lines


def _generate_document_v2(kind: str, table: dict, *, project_root: str = "", wf_state=None) -> str:
    """版本 2 渲染：模板规定的每一节都存在、内容全部来自表栏位、零占位指引句（R16/R18）。"""
    schema = _schema(kind, _table_version_of(table))
    topic = str(table.get("验收主题", ""))
    workflow_id = str(table.get("工作流编号", ""))
    file_key = topic_file_key(project_root, topic) if project_root and topic else (topic or kind)
    lines: list[str] = []

    if kind == "test_result":
        # 测试结果文档依赖机器记录与测试计划表，统一走专用渲染器，保证指纹计算与正式生成分发一致。
        tasks_by_id: dict = {}
        plan_table = None
        if wf_state is not None:
            qa_state = wf_state.stages.get("qa")
            if qa_state is not None:
                tasks_by_id = qa_state.test_tasks.get(topic, {})
            if project_root:
                plan_relative = table_relative_path(
                    project_root, wf_state.workflow_id, "test_plan", topic
                )
                if table_exists(project_root, plan_relative):
                    plan_table = load_table(os.path.join(project_root, plan_relative))
        return _generate_test_result_document_v2(
            topic, table, tasks_by_id, plan_table, project_root
        )

    def _inline(value) -> str:
        return re.sub(r"\s*\r?\n\s*", " ", str(value)).strip()

    def _narrative(heading_prefix: str, key: str, empty_text: str) -> list[str]:
        items = [str(x) for x in table.get(key, []) if str(x).strip()]
        out = ["", heading_prefix, ""]
        out += [f"- {x}" for x in items] if items else [empty_text]
        return out

    def _downstream_cell(rel_path: str, label: str, note: str) -> str:
        # 模板规则：下游文件真实生成后才改成链接；由后续环节门禁回补刷新。
        if project_root and os.path.isfile(os.path.join(project_root, rel_path)):
            return f"| 下游 | [{label}](../{rel_path}) | {note} |"
        return f"| 下游 | `{rel_path}`（待生成） | {note} |"

    def _test_result_upstream_row() -> str:
        # 模板规则：目标文件真实生成后才写链接；纯人工主题写“无自动化测试结果，转主题验收”。
        rel_path = f"qa/{file_key}_测试结果.md"
        note = "自动化或混合主题的正式执行事实"
        if project_root and wf_state is not None:
            plan_relative = table_relative_path(
                project_root, wf_state.workflow_id, "test_plan", topic
            )
            if table_exists(project_root, plan_relative):
                plan_table = load_table(os.path.join(project_root, plan_relative))
                methods = {
                    str(row.get("测试方式", "")).strip()
                    for row in plan_table.get("测试项", [])
                    if isinstance(row, dict)
                }
                if methods and methods <= {"人工验收"}:
                    return f"| 上游 | 无自动化测试结果，转主题验收 | 纯人工主题不生成测试结果文档 |"
        if project_root and os.path.isfile(os.path.join(project_root, rel_path)):
            return f"| 上游 | [主题测试结果](../{rel_path}) | {note} |"
        return f"| 上游 | `{rel_path}`（待生成） | {note} |"

    if kind == "acceptance_plan":
        # 按验收计划模板渲染六节结构（R16/R18 提前落地）：内容全部来自表栏位，禁止占位句。
        lines += [
            f"# 【验收主题】{topic}",
            "",
            f"- 工作流编号：{workflow_id}",
            f"- 验收主题：{topic}",
            "",
            "## 1. 本次需求与验收目标",
            "",
            "### 需求来源",
            "",
        ] + [f"- {item}" for item in table.get("需求来源", [])]
        lines += ["", "### 验收目标", ""] + [f"- {item}" for item in table.get("验收目标说明", [])]
        lines += ["", "## 2. 产品设计依据", ""] + [f"- {item}" for item in table.get("产品设计依据", [])]
        lines += ["", "## 3. 验收范围", "", "### 本主题验收", ""]
        lines += [f"- {item}" for item in table.get("本主题验收", [])]
        lines += ["", "### 本主题不验收", ""] + [f"- {item}" for item in table.get("本主题不验收", [])]
        lines += ["", '<a id="4-验收条件"></a>', "## 4. 验收条件", ""]
        for row in table.get("验收条件", []):
            ac_id = str(row.get("验收条件编号", "")).strip()
            name = str(row.get("验收条件名称", "")).strip() or ac_id
            lines += [f'<a id="{ac_id.lower()}"></a>', f"### {ac_id}：{name}", ""]
            for column in ("开始前状态", "触发动作", "可检查结果", "通过标准", "不通过标准", "产品设计依据"):
                lines.append(f"- {column}：{_inline(row.get(column, ''))}")
            lines.append("")
        lines += ["## 5. 完成判定", ""] + [f"- {item}" for item in table.get("完成判定", [])]
        lines += _declaration_section(table)
        lines += [
            "",
            "## 6. 上下游文档",
            "",
            "| 关系 | 文档 | 说明 |",
            "|---|---|---|",
            f"| 上游 | [产品总说明](../spec/产品总说明.md) | 本主题来自本轮已确认的产品设计 |",
            "| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整交付关系和状态 |",
            _downstream_cell(f"impl/{file_key}_实施记录.md", f"{topic} 实施记录", "下一阶段按代码计划、代码实施、代码结果连续完成实施"),
            _downstream_cell(f"qa/{file_key}_测试计划.md", f"{topic} 测试计划", "代码结果确认后，在一次测试验证阶段内完成计划、测试代码、登记、执行和结果"),
            "",
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

    if kind == "impl_record":
        rl = schema["row_lists"]
        lines += [
            f"# 【实施】{topic}",
            "",
            f"- 工作流编号：{workflow_id}",
            f"- 验收主题：{topic}",
            "",
            "## 1. 实施依据",
            "",
        ]
        _render_rows(lines, rl["实施依据"]["columns"], table.get("实施依据", []))
        lines += ["", '<a id="2-实施前计划"></a>', "## 2. 实施前计划（代码计划）", ""]
        lines += _narrative("### 2.1 预期产品结果", "预期产品结果", "暂无")
        lines += ["", "### 2.2 最低实现设计", ""]
        _render_rows(lines, rl["最低实现设计"]["columns"], table.get("最低实现设计", []))
        lines += ["", "### 2.3 代码修改计划", ""]
        _render_rows(lines, rl["代码修改计划"]["columns"], table.get("代码修改计划", []))
        lines += ["", "#### 开发检查计划", ""]
        _render_rows(lines, rl["开发检查计划"]["columns"], table.get("开发检查计划", []))
        lines += _narrative("### 2.4 未决问题", "未决问题", "暂无")
        lines += ["", '<a id="3-实施后记录"></a>', "## 3. 实施后记录（代码实施与代码结果）", ""]
        lines += ["### 3.1 实施动作记录", ""]
        _render_rows(lines, rl["实施动作记录"]["columns"], table.get("实施动作记录", []))
        lines += _narrative("### 3.2 实施中问题与处理", "实施中问题与处理", "暂无")
        lines += ["", "### 3.3 未完成内容", "", str(table.get("未完成状态", "状态：无"))]
        lines += ["", "### 3.4 代码结果", "", "#### 3.4.1 实际代码修改", ""]
        _render_rows(lines, rl["实际代码修改"]["columns"], table.get("实际代码修改", []))
        lines += ["", "#### 3.4.2 开发检查记录", ""]
        _render_rows(lines, rl["开发检查记录"]["columns"], table.get("开发检查记录", []))
        lines += _declaration_section(table)
        lines += [
            "",
            "## 4. 上下游文档",
            "",
            "| 关系 | 文档 | 说明 |",
            "|---|---|---|",
            f"| 上游 | [验收计划](../acceptance/{file_key}_验收计划.md) | 本主题要达到的用户结果和验收条件 |",
            "| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整交付链路 |",
            _downstream_cell(f"qa/{file_key}_测试计划.md", f"{topic} 测试计划", "代码结果确认后，在测试验证开始时确认范围和通过标准"),
            _downstream_cell(f"qa/{file_key}_测试结果.md", f"{topic} 测试结果", "同一测试验证阶段连续完成测试代码、登记、执行和结果"),
            _downstream_cell(f"acceptance/{file_key}_验收结果.md", f"{topic} 验收结果", "正式测试后执行主题验收"),
            "",
        ]
        return "\n".join(lines)

    if kind == "test_plan":
        rl = schema["row_lists"]
        columns = rl["测试项"]["columns"]
        # 模板 13 列覆盖表：验收条件链接 + 测试项（锚点+TC 编号+直白名称）+ 其余设计语义列；机器执行列由程序登记时从表读取。
        header_columns = ["验收条件链接", "测试项", "前置测试项", "测试方式",
                          "产品入口", "代码入口", "测试入口", "准备数据", "执行动作",
                          "观察位置", "预期结果", "不通过表现", "证据要求"]
        lines += [
            f"# {topic}测试计划",
            "",
            f"- 工作流编号：{workflow_id}",
            f"- 上游验收计划：[{topic}验收计划](../acceptance/{file_key}_验收计划.md)",
            "",
            "## 1. 验收条件覆盖",
            "",
            "| " + " | ".join(header_columns) + " |",
            "|" + "---|" * len(header_columns),
        ]
        # AC 编号→名称取自本主题验收计划表（渲染链接需带名称，模板与解析器一致）
        ac_names: dict[str, str] = {}
        _ap_rel = table_relative_path(project_root, workflow_id, "acceptance_plan", topic) if project_root else ""
        if _ap_rel and table_exists(project_root, _ap_rel):
            _ap = load_table(os.path.join(project_root, _ap_rel))
            for arow in _ap.get("验收条件", []):
                if isinstance(arow, dict):
                    _ac_id = str(arow.get("验收条件编号", "")).strip()
                    ac_names[_ac_id] = str(arow.get("验收条件名称", "")).strip() or _ac_id
        for row in table.get("测试项", []):
            cells = {**{c: "" for c in columns}, **(row if isinstance(row, dict) else {})}
            tc_id = str(cells.get("测试项编号", "")).strip()
            anchor_id = re.sub(r"[^a-z0-9:-]", "-", tc_id.lower())
            ac_refs: list[str] = []
            for ac in re.split(r"[、,，]\s*", str(cells.get("对应验收条件", ""))):
                ac = ac.strip()
                if ac:
                    ac_refs.append(f"[{ac}：{ac_names.get(ac, ac)}](../acceptance/{file_key}_验收计划.md#{ac.lower()})")
            view = {
                "验收条件链接": "、".join(ac_refs),
                "测试项": f'<a id="{anchor_id}"></a>[{tc_id} {cells.get("直白测试名称", "")}](#{anchor_id})',
                "前置测试项": _inline(cells.get("前置测试项", "")),
                "测试方式": _inline(cells.get("测试方式", "")),
                "产品入口": _inline(cells.get("产品入口", "")),
                "代码入口": f"`{cells.get('代码入口', '')}`" if str(cells.get("代码入口", "")).strip() else "",
                "测试入口": f"`{cells.get('测试入口', '')}`" if str(cells.get("测试入口", "")).strip() else "",
                "准备数据": _inline(cells.get("准备数据", "")),
                "执行动作": _inline(cells.get("执行动作", "")),
                "观察位置": _inline(cells.get("观察位置", "")),
                "预期结果": _inline(cells.get("预期结果", "")),
                "不通过表现": _inline(cells.get("不通过表现", "")),
                "证据要求": _inline(cells.get("证据要求", "")),
            }
            lines.append("| " + " | ".join(_md_cell(view.get(c, "")) for c in header_columns) + " |")
        lines += _narrative("## 2. 针对性回归范围", "针对性回归范围", "- 暂无；由最终全量回归统一检查")
        lines += _narrative("## 3. 测试条件要求", "测试条件要求", "- 暂无")
        lines += _narrative("## 4. 未决测试条件", "未决测试条件", "- 暂无")
        lines += _declaration_section(table)
        has_auto = any(
            str(r.get("测试方式", "")).strip() in {"自动化测试", "自动化测试 + 人工验收"}
            for r in table.get("测试项", []) if isinstance(r, dict)
        )
        if has_auto:
            result_rel = f"qa/{file_key}_测试结果.md"
            # 模板规则：结果文档真实生成后才改成链接，生成前保持（待生成）
            if project_root and os.path.isfile(os.path.join(project_root, result_rel)):
                pending_result = f"| 下游 | [{topic}测试结果](./{file_key}_测试结果.md) | 记录正式执行的结构化报告事实 |"
            else:
                pending_result = f"| 下游 | `./{file_key}_测试结果.md`（待生成） | 记录正式执行的结构化报告事实 |"
        else:
            pending_result = "| 下游 | 无自动化测试结果，转主题验收 | 纯人工验收主题不生成测试结果文档 |"
        lines += [
            "",
            "## 5. 上下游文档",
            "",
            "| 关系 | 文档 | 说明 |",
            "|---|---|---|",
            f"| 上游 | [{topic}验收计划](../acceptance/{file_key}_验收计划.md) | 本测试计划依据的验收条件 |",
            f"| 上游 | [实施记录](../impl/{file_key}_实施记录.md) | 测试入口和观察位置来自已确认实施与真实代码 |",
            "| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整交付关系和状态 |",
            pending_result,
            "",
        ]
        return "\n".join(lines)

    if kind == "acceptance_result":
        rl = schema["row_lists"]
        columns = rl["验收结果"]["columns"]
        conclusions = [str(r.get("验收结论", "")).strip() for r in table.get("验收结果", [])]
        if conclusions and all(c == "passed" for c in conclusions):
            overall = "通过"
        elif any(c == "failed" for c in conclusions):
            overall = "失败"
        elif any(c == "blocked" for c in conclusions):
            overall = "阻塞"
        else:
            overall = "通过" if not conclusions else "未完成"
        # 验收计划表承载人工验收步骤（R18：结果文档渲染、结果表不复述）
        plan_steps: dict[str, dict] = {}
        plan_table = None
        if project_root and topic:
            _plan_rel = table_relative_path(project_root, workflow_id, "acceptance_plan", topic)
            if table_exists(project_root, _plan_rel):
                plan_table = load_table(os.path.join(project_root, _plan_rel))
                for srow in (plan_table or {}).get("人工验收步骤", []):
                    if isinstance(srow, dict):
                        plan_steps[str(srow.get("验收条件编号", "")).strip()] = srow
        ac_names: dict[str, str] = {}
        ac_pass: dict[str, str] = {}
        for arow in (plan_table or {}).get("验收条件", []):
            if isinstance(arow, dict):
                _ac = str(arow.get("验收条件编号", "")).strip()
                ac_names[_ac] = str(arow.get("验收条件名称", "")).strip() or _ac
                ac_pass[_ac] = _inline(arow.get("通过标准", ""))
        records_by_id: dict[str, object] = {}
        if wf_state is not None:
            stage_state = wf_state.stages.get("topic_acceptance")
            if stage_state is not None:
                records_by_id = dict(stage_state.acceptance_records.get(topic, {}))
        confirmed_times = [
            getattr(rec, "confirmed_at", None) for rec in records_by_id.values()
            if getattr(rec, "confirmed_at", None)
        ]
        finish_time = max(confirmed_times) if confirmed_times else "待验收记录回填"
        lines += [
            f"# 【主题验收结果】{topic}",
            "",
            f"- 工作流编号：{workflow_id}",
            f"- 验收主题：{topic}",
            f"- 验收结果：{overall}",
            f"- 验收完成时间：{finish_time}",
            "",
            "## 1. 验收依据",
            "",
            "| 关系 | 文档 | 说明 |",
            "|---|---|---|",
            f"| 上游 | [主题验收计划](./{file_key}_验收计划.md) | 本主题全部验收条件 |",
            _test_result_upstream_row(),
            f"| 上游 | [实施记录](../impl/{file_key}_实施记录.md) | 本主题实际实施内容 |",
            "| 全局追踪 | [需求交付追踪表](../需求交付追踪表.md) | 当前验收条件的完整上下游关系 |",
            "",
            "## 2. 验收条件结果",
            "",
        ]
        judgment = {"passed": "通过", "failed": "失败", "blocked": "阻塞"}
        for row in table.get("验收结果", []):
            cells = {**{c: "" for c in columns}, **(row if isinstance(row, dict) else {})}
            ac = str(cells.get("验收条件编号", "")).strip()
            anchor_id = re.sub(r"[^a-z0-9:-]", "-", ac.lower())
            lines += [
                f'<a id="{anchor_id}"></a>',
                f"### {ac}：{ac_names.get(ac, ac)}",
                "",
                f"- 验收方式：{_inline(cells.get('验收方式', ''))}",
                f"- 验收条件：[{ac}：{ac_names.get(ac, ac)}](./{file_key}_验收计划.md#{anchor_id}) {ac_pass.get(ac, '')}".strip(),
                f"- 自动化依据：{_inline(cells.get('自动化依据', ''))}",
                f"- 机器测试记录编号：{_inline(cells.get('机器测试记录编号', ''))}",
                "",
                "#### 人工验收步骤",
                "",
            ]
            step = plan_steps.get(ac)
            if step:
                steps = [s.strip() for s in re.split(r"[;；]\s*", str(step.get("操作步骤", ""))) if s.strip()]
                lines += [
                    f"- 验收对象：{_inline(step.get('验收对象', ''))}",
                    f"- 开始前条件：{_inline(step.get('开始前条件', ''))}",
                    "- 操作步骤：",
                ]
                lines += [f"  {i}. {s}" for i, s in enumerate(steps, 1)] or ["  1. 未填写"]
                lines += [
                    f"- 观察内容：{_inline(step.get('观察内容', ''))}",
                    f"- 预期结果：{_inline(step.get('预期结果', ''))}",
                    f"- 用户需要回答：{_inline(step.get('用户需要回答', ''))}",
                ]
            else:
                lines.append("不适用（纯自动化验收条件，不需要人工操作）。")
            record = records_by_id.get(ac)
            confirmed_at = getattr(record, "confirmed_at", None) if record is not None else None
            lines += [
                "",
                f"- 用户实际回答：{_inline(cells.get('用户实际回答', ''))}",
                f"- 人工确认：{_inline(cells.get('人工确认', ''))}",
                f"- 确认时间：{confirmed_at or '不适用'}",
                f"- 实际结果：{_inline(cells.get('实际观察结果', ''))}",
                f"- 判定：{judgment.get(str(cells.get('验收结论', '')).strip(), _inline(cells.get('验收结论', '')))}",
                f"- 验收证据：{_inline(cells.get('证据', ''))}",
                f"- 验收记录编号：{_inline(cells.get('验收记录编号', ''))}",
                "",
            ]
        lines += _narrative("## 3. 验收说明", "验收说明", "暂无")
        lines += _declaration_section(table)
        lines += [
            "",
            "## 4. 上下游文档",
            "",
            "| 关系 | 文档 | 说明 |",
            "|---|---|---|",
            f"| 上游 | [主题验收计划](./{file_key}_验收计划.md) | 验收标准来源 |",
            _test_result_upstream_row(),
            f"| 上游 | [实施记录](../impl/{file_key}_实施记录.md) | 被验收的实际实现 |",
            "| 全局追踪 | [需求交付追踪表](../需求交付追踪表.md) | 本主题在完整交付链路中的位置 |",
            "| 下游 | 最终全量回归 | 所有主题通过后执行 |",
            "",
        ]
        return "\n".join(lines)

    if kind == "spike_conclusion":
        rl = schema["row_lists"]
        lines += [
            "# 【穿刺】穿刺结论汇总",
            "",
            f"- 工作流编号：{workflow_id}",
            "",
        ]
        for row in table.get("穿刺项", []):
            cells = {**{c: "" for c in rl["穿刺项"]["columns"]}, **(row if isinstance(row, dict) else {})}
            sp_id = str(cells.get("穿刺项编号", "")).strip()
            anchor_id = re.sub(r"[^a-z0-9:-]", "-", sp_id.lower())
            lines += [f'<a id="{anchor_id}"></a>', f"## {sp_id}", ""]
            for column in rl["穿刺项"]["columns"][1:]:
                lines.append(f"- {column}：{_inline(cells.get(column, ''))}")
            lines.append("")
        lines += ["## 可复用资产", ""]
        _render_rows(lines, rl["可复用资产"]["columns"], table.get("可复用资产", []))
        lines += _narrative("## 结论说明", "结论说明", "暂无")
        return "\n".join(lines)

    if kind == "bug_record":
        rl = schema["row_lists"]
        lines += [f"# 【缺陷】{topic or '缺陷记录'}", "", f"- 工作流编号：{workflow_id}", ""]
        lines += ["## 缺陷信息", ""]
        _render_rows(lines, rl["缺陷信息"]["columns"], table.get("缺陷信息", []))
        lines += _narrative("## 缺陷说明", "缺陷说明", "暂无")
        lines += _narrative("## 真实复现条件", "真实复现条件", "暂无")
        if _table_version_of(table) == "3":
            lines += _narrative("## 运行环境", "运行环境", "暂无")
            lines += _narrative("## 真实输入", "真实输入", "暂无")
        else:
            lines += _narrative("## 根因证据", "根因证据", "暂无")
        lines += _narrative("## 修复仍存在的不确定性", "修复仍存在的不确定性", "暂无")
        lines += _narrative("## 修复与验收结果", "修复与验收结果", "暂无（由后续阶段按实际结果追加）")
        return "\n".join(lines)

    if kind in {"design_sync", "topic_relations", "architecture_changes"}:
        # 无环节文档模板的轮次级表：标题 + 行清单表 + 叙述段，内容同样全部来自表栏位。
        title = f"{schema['doc_name']}：{topic}" if topic else schema["doc_name"]
        lines += [f"# 【工作记录】{title}", "", f"- 工作流编号：{workflow_id}"]
        if topic:
            lines.append(f"- 验收主题：{topic}")
        for key, definition in schema["row_lists"].items():
            lines += ["", f"## {key}", ""]
            _render_rows(lines, definition["columns"], table.get(key, []))
        for key in schema["narrative"]:
            items = [str(x) for x in table.get(key, []) if str(x).strip()]
            lines += ["", f"## {key}", ""] + ([f"- {x}" for x in items] or ["暂无"])
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
    if kind == "bug_record":
        return _sync_bug_record_tables(project_root, workflow_id, selected_topics=topics, regenerate=regenerate)
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
        table_problems = validate_table(kind, table, _workflow_table_version(project_root, workflow_id), project_root=project_root)
        problems.extend(table_problems)
        if any(category == FORMAT_CATEGORY for category, _ in table_problems):
            continue
        wf_state = state_mod.load_state(project_root) if kind == "acceptance_result" else None
        if kind == "acceptance_result":
            record_problems = _fill_acceptance_record_ids(wf_state, topic, table)
            problems.extend(record_problems)
            if record_problems:
                continue
        expected_name = _expected_document_path(project_root, kind, topic, table)
        doc_relative = expected_name
        doc_full = os.path.join(project_root, doc_relative)
        content = generate_document(kind, table, project_root=project_root, wf_state=wf_state)
        if _document_was_edited(project_root, kind, table, doc_relative, content):
            problems.append((
                CONTENT_CATEGORY,
                _table_document_conflict_facts(
                    project_root,
                    kind,
                    table,
                    doc_relative,
                    f"{KIND_SCHEMAS[kind]['doc_name']}（按表生成的章节）",
                    content,
                ),
            ))
            continue
        if regenerate:
            content = markdown_links_mod.with_heading_anchors(content, previous_content=_read_document(doc_full))
            _write_text(doc_full, content)
            doc_hash = _file_sha256(doc_full)
            table[DOC_HASH_KEY] = doc_hash
            table[GENERATED_DOC_PATH_KEY] = doc_relative
            _atomic_write(full, table)
            _save_generation_receipt(project_root, kind, table, {doc_relative: content})
    return problems, documents


def _expected_document_path(project_root: str, kind: str, topic: str, table: dict) -> str:
    if kind == "bug_record":
        topic = _storage_topic(project_root, kind, table)
    elif kind in WORKFLOW_LEVEL_KINDS:
        topic = ""
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


_FEATURES_SECTION_RE = re.compile(
    r'(## 7\. 产品功能\n)(.*?)(?=\n(?:<a id="[^"]+"></a>\n)*## 8\. )', re.DOTALL,
)


def _generation_receipt_path(project_root: str, kind: str, table: dict) -> str:
    workflow_id = str(table.get("工作流编号", ""))
    if not workflow_id or workflow_id in {".", ".."} or any(c in workflow_id for c in "/\\"):
        raise RecordsError("工作流编号无效，无法核对程序专用字段")
    topic = _storage_topic(project_root, kind, table)
    filename = os.path.basename(table_relative_path(project_root, workflow_id, kind, topic))
    return os.path.join(records_dir(project_root, workflow_id), ".generated", filename)


def _generation_fields(table: dict) -> dict:
    return {
        DOC_HASH_KEY: table.get(DOC_HASH_KEY) or None,
        GENERATED_DOC_PATH_KEY: table.get(GENERATED_DOC_PATH_KEY) or None,
        BUG_DOC_HASHES_KEY: table.get(BUG_DOC_HASHES_KEY) or {},
    }


def _load_generation_receipt(project_root: str, kind: str, table: dict) -> dict | None:
    path = _generation_receipt_path(project_root, kind, table)
    if not os.path.isfile(path):
        return None
    receipt = load_table(path)
    if not isinstance(receipt.get("fields"), dict) or not isinstance(receipt.get("documents"), dict):
        raise RecordsError(f"程序生成凭据损坏：{path}；不能采用表内指纹覆盖正式文档")
    return receipt


def _owned_document_content(kind: str, relative: str, content: str) -> str:
    if kind == "product_features":
        section = _FEATURES_SECTION_RE.search(content)
        return section.group(0) if section else content
    if kind == "bug_record" and relative.startswith("bug/缺陷_"):
        # 后续验收追加的三级结论块不归复现表所有，保留它们但不误判为正文手改。
        content = markdown_links_mod.without_generated_anchors(content)
        section = _BUG_RESULT_SECTION_RE.search(content)
        if section:
            block = re.search(r'^###\s+', section.group(1), re.MULTILINE)
            if block:
                content = content[:section.start(1) + block.start()].rstrip() + "\n"
    return content


def _body_hash(kind: str, relative: str, content: str, *, project_root: str = "", table: dict | None = None) -> str:
    if kind == "bug_record" and relative == "bug/索引.md" and table is not None:
        from .bug_record import index_entry

        filename = f"缺陷_{bug_file_key(project_root, str(table.get('验收主题', '')))}.md"
        entry = index_entry(content, filename)
        # 共享索引的状态由验收阶段维护；凭据只绑定本主题的入口、现象和根因。
        owned = json.dumps(entry[1][:-1] if entry else [], ensure_ascii=False)
        return hashlib.sha256(owned.encode("utf-8")).hexdigest()
    owned = _owned_document_content(kind, relative, content)
    return hashlib.sha256(markdown_links_mod.without_generated_anchors(owned).encode("utf-8")).hexdigest()


def _legacy_generation_is_verified(project_root: str, kind: str, table: dict) -> bool:
    fields = _generation_fields(table)
    if not any(fields.values()):
        return True
    topic = str(table.get("验收主题", ""))
    relative = _expected_document_path(project_root, kind, topic, table)
    wf_state = state_mod.load_state(project_root)
    if wf_state is not None and wf_state.workflow_id != table.get("工作流编号"):
        wf_state = None
    generated = generate_document(kind, table, project_root=project_root, wf_state=wf_state)
    raw_generated = (_generate_document_v1(kind, table, project_root=project_root)
                     if _table_version_of(table) == "1" else
                     _generate_document_v2(kind, table, project_root=project_root, wf_state=wf_state))
    expected = {relative: generated}
    if kind == "bug_record":
        expected.update(_bug_defect_documents(table, project_root))
    hashes = dict(fields[BUG_DOC_HASHES_KEY])
    if fields[DOC_HASH_KEY] is not None:
        hashes[relative] = fields[DOC_HASH_KEY]
    elif fields[GENERATED_DOC_PATH_KEY] is not None:
        return False
    for path, recorded_hash in hashes.items():
        current = _read_document(os.path.join(project_root, path))
        if kind == "product_features":
            section = _FEATURES_SECTION_RE.search(current)
            if section is None:
                return False
            expected[path] = section.group(1) + "\n" + generated + "\n\n"
        current_owned = _owned_document_content(kind, path, current)
        candidates = {hashlib.sha256(text.encode("utf-8")).hexdigest() for text in (current, current_owned)}
        if path == relative:
            candidates.add(hashlib.sha256(raw_generated.encode("utf-8")).hexdigest())
        if recorded_hash not in candidates or _body_hash(kind, path, current, project_root=project_root, table=table) != _body_hash(kind, path, expected[path], project_root=project_root, table=table):
            return False
    return True


def _program_field_problems(project_root: str, kind: str, table: dict) -> list[tuple[str, str]]:
    fields = _generation_fields(table)
    invalid = set()
    for key in (DOC_HASH_KEY, GENERATED_DOC_PATH_KEY):
        if table.get(key) is not None and not isinstance(table.get(key), str):
            invalid.add(key)
    if fields[DOC_HASH_KEY] is not None and not re.fullmatch(r"[0-9a-f]{64}", str(fields[DOC_HASH_KEY])):
        invalid.add(DOC_HASH_KEY)
    if (table.get(BUG_DOC_HASHES_KEY) is not None and not isinstance(table.get(BUG_DOC_HASHES_KEY), dict)) or (kind != "bug_record" and fields[BUG_DOC_HASHES_KEY]):
        invalid.add(BUG_DOC_HASHES_KEY)
    if project_root:
        try:
            expected_path = _expected_document_path(project_root, kind, str(table.get("验收主题", "")), table)
            if fields[GENERATED_DOC_PATH_KEY] not in (None, expected_path):
                invalid.add(GENERATED_DOC_PATH_KEY)
            if isinstance(fields[BUG_DOC_HASHES_KEY], dict):
                allowed = {"bug/索引.md", f"bug/缺陷_{bug_file_key(project_root, str(table.get('验收主题', '')).strip() or '缺陷记录')}.md"} if kind == "bug_record" else set()
                if any(path not in allowed or not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for path, value in fields[BUG_DOC_HASHES_KEY].items()):
                    invalid.add(BUG_DOC_HASHES_KEY)
            receipt = _load_generation_receipt(project_root, kind, table)
            if receipt is not None:
                invalid.update(key for key in PROGRAM_FIELD_KEYS if fields[key] != receipt["fields"].get(key))
            elif not invalid and not _legacy_generation_is_verified(project_root, kind, table):
                invalid.update(key for key in PROGRAM_FIELD_KEYS if fields[key])
        except (RecordsError, OSError, TypeError, ValueError, KeyError):
            invalid.update(key for key in PROGRAM_FIELD_KEYS if fields[key])
            if not invalid:
                invalid.update(PROGRAM_FIELD_KEYS)
    else:
        invalid.update(key for key in PROGRAM_FIELD_KEYS if fields[key])
    return [(FORMAT_CATEGORY,
             f"程序专用字段“{key}”不能由填写者填写或改动，或缺少可核实的生成凭据；"
             "请保留程序写回的原值，新表保持空值，只修改事实栏目后重新执行；程序不会据此改写正式文件")
            for key in PROGRAM_FIELD_KEYS if key in invalid]


def _save_generation_receipt(project_root: str, kind: str, table: dict, generated: dict[str, str] | None = None) -> None:
    receipt = _load_generation_receipt(project_root, kind, table)
    if receipt is None:
        receipt = {"fields": {}, "documents": {}}
        if generated is None:
            # 只供已通过旧表生成内容核验的首次接续；已有凭据不从磁盘重建基线。
            paths = set(_generation_fields(table)[BUG_DOC_HASHES_KEY])
            if table.get(GENERATED_DOC_PATH_KEY):
                paths.add(table[GENERATED_DOC_PATH_KEY])
            generated = {path: _read_document(os.path.join(project_root, path)) for path in paths}
    receipt["fields"] = _generation_fields(table)
    for relative, content in (generated or {}).items():
        receipt["documents"][relative] = {"body_hash": _body_hash(kind, relative, content, project_root=project_root, table=table)}
        if kind == "bug_record" and relative == "bug/索引.md":
            receipt["documents"][relative]["scope"] = "bug-index-row"
    path = _generation_receipt_path(project_root, kind, table)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write(path, receipt)


def _document_was_edited(project_root: str, kind: str, table: dict, relative: str, expected: str) -> bool:
    full = os.path.join(project_root, relative)
    if not os.path.isfile(full):
        return False
    current = _read_document(full)
    current_body = _body_hash(kind, relative, current, project_root=project_root, table=table)
    if current_body == _body_hash(kind, relative, expected, project_root=project_root, table=table):
        return False
    previous = (table.get(BUG_DOC_HASHES_KEY) or {}).get(relative) if relative.startswith("bug/") else table.get(DOC_HASH_KEY)
    if previous is None:
        return False
    if hashlib.sha256(_owned_document_content(kind, relative, current).encode("utf-8")).hexdigest() == previous:
        return False
    receipt = _load_generation_receipt(project_root, kind, table)
    if receipt is not None and kind == "bug_record" and relative == "bug/索引.md":
        if receipt["documents"].get(relative, {}).get("scope") != "bug-index-row":
            current_body = _body_hash(kind, relative, current)
    return receipt is None or current_body != receipt["documents"].get(relative, {}).get("body_hash")


def _table_document_conflict_facts(
    project_root: str,
    kind: str,
    table: dict,
    relative: str,
    section_label: str,
    expected_content: str,
) -> str:
    """R46：表文档不一致类失败带差异章节块与两个指纹，并按事实区分修复路径。

    表未更新（按当前表生成的内容与上次凭据一致）时提示把改动写回表；
    表已更新（按当前表生成的内容与上次凭据不同）、仅文档被手改时提示
    恢复文档由程序按表重写。不把两种情况笼统归为"写回表"。
    """
    current_hash = _file_sha256(os.path.join(project_root, relative))
    receipt = None
    try:
        receipt = _load_generation_receipt(project_root, kind, table)
    except RecordsError:
        receipt = None
    previous_hash = None
    if receipt is not None:
        document_receipt = receipt["documents"].get(relative)
        if isinstance(document_receipt, dict):
            previous_hash = document_receipt.get("body_hash")
    facts = (
        f"正式文档 {relative} 与工作记录表不一致：差异章节块：{section_label}；"
        f"程序凭据指纹（上次生成正文摘要）：{previous_hash or '（无凭据）'}；"
        f"当前指纹：{current_hash or '（无法读取）'}。"
    )
    if previous_hash is not None:
        # 表是否已更新：按当前表生成的正文摘要是否不同于上次凭据
        expected_body_hash = _body_hash(
            kind, relative, expected_content, project_root=project_root, table=table
        )
        table_updated = expected_body_hash != previous_hash
        if table_updated:
            facts += (
                "修复路径：表已更新、仅文档该章节被手改——该章节归程序生成，"
                "把文档该章节恢复为程序上次生成的内容（或删除该章节），"
                "重新执行门禁后程序会按表重新写入；不要再改表。"
            )
        else:
            facts += (
                "修复路径：表未更新——把文档中的改动写回工作记录表后重新执行门禁；"
                "程序不会悄悄覆盖手改内容。"
            )
    else:
        facts += (
            "修复路径：缺少上次生成凭据，无法区分两种情况——"
            "核对文档改动是否已写入工作记录表；已写入则把文档该章节恢复为程序生成内容。"
        )
    return facts


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
        "update_code_design": ("design_sync", "architecture_changes"),
    }
    return mapping.get(stage, ())


def table_is_filled(table: dict) -> bool:
    """表内是否已经有 AI 填写的内容；空表不启用表路径，保证旧流程兼容。"""
    schema_name = table.get("验收主题")
    for key, value in table.items():
        if key in {"表版本", "工作流编号", "验收主题", "填写说明", *PROGRAM_FIELD_KEYS}:
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


def workflow_uses_tables(wf_state, project_root: str | None = None) -> bool:
    """本轮是否启用工作记录表：以开工时冻结在状态里的表版本为准（R11）。

    判定不看某一张表是否存在、是否已填或能否解析——那些情况要报具体错误并停留
    当前环节，不能因此退回按正式文档正文逐字检查的旧方式。

    冻结字段是后加的：更早开工、已经建过表的轮次状态里没有它。给出 project_root
    时按“本轮是否已经有过表文件”兜底，避免这些轮次中途换判定方式。两条都不成立
    的才是功能上线前的旧轮次，继续走原有文档检查。
    """
    if getattr(wf_state, "table_format_version", "") or "":
        return True
    workflow_id = getattr(wf_state, "workflow_id", "") or ""
    if not project_root or not workflow_id:
        return False
    run_dir = os.path.join(project_root, RECORDS_ROOT, workflow_id)
    try:
        return any(name.endswith(".json") for name in os.listdir(run_dir))
    except OSError:
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
    from .topic import acceptance_topics

    stage = wf_state.current_stage
    kinds = stage_table_kinds(stage)
    if not kinds:
        return []
    try:
        topics = acceptance_topics(project_root, wf_state.intent, stage, list(wf_state.topics))
    except ValueError:
        if stage != "acceptance_plan":
            raise
        # 首次进入验收计划时旧索引还没有本轮章节，先建表，不依赖尚未生成的索引。
        topics = list(wf_state.topics)
    if stage == "reproduce":
        problems, existing = bug_record_tables(project_root, wf_state.workflow_id)
        if problems:
            raise RecordsError("；".join(detail for _, detail in problems))
        targets = [_storage_topic(project_root, "bug_record", table) for _, table in existing]
        covered = {table["验收主题"] for _, table in existing}
        targets.extend(topic for topic in topics if topic not in covered)
        return [create_or_complete_table(project_root, wf_state.workflow_id, "bug_record", topic)
                for topic in targets or [""]]
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
    problems.extend(validate_table("product_features", table, _workflow_table_version(project_root, workflow_id), project_root=project_root))
    if any(category == FORMAT_CATEGORY for category, _ in problems):
        return problems, documents
    overview_rel = artifact_paths_mod.PRODUCT_OVERVIEW_DOC
    overview_full = os.path.join(project_root, overview_rel)
    if not os.path.isfile(overview_full):
        problems.append((CONTENT_CATEGORY, f"{overview_rel} 不存在，无法写入功能清单"))
        return problems, documents
    content = open(overview_full, "r", encoding="utf-8").read()
    block = generate_document("product_features", table, project_root=project_root)
    pattern = _FEATURES_SECTION_RE
    if not pattern.search(content):
        problems.append((CONTENT_CATEGORY, f"{overview_rel} 缺少“## 7. 产品功能”章节，无法按表写入功能清单"))
        return problems, documents
    new_content = pattern.sub(lambda match: match.group(1) + "\n" + block + "\n\n", content, count=1)
    # R19 第③项（修复轮）：记录与手改比对一律用"功能清单章节块"指纹。
    # 之前记录的是整文件哈希，产品总说明其他章节变化（修改记录追加、上下游文档更新）
    # 会让下次同步误报"文档被直接修改"。块级口径保证只对本节内容负责：
    # 当前块既不是上次生成的结果也不是本次要生成的结果 → 本节被手改，报告并保留；
    # 当前块等于上次登记 → 其他章节变化，正常重新写入本块。
    current_section = pattern.search(content)
    current_block_hash = hashlib.sha256(
        (current_section.group(0)).encode("utf-8")
    ).hexdigest()
    expected_hash = hashlib.sha256(
        (current_section.group(1) + "\n" + block + "\n\n").encode("utf-8")
    ).hexdigest()
    if _document_was_edited(project_root, "product_features", table, overview_rel, new_content):
        problems.append((
            CONTENT_CATEGORY,
            _table_document_conflict_facts(
                project_root,
                "product_features",
                table,
                overview_rel,
                "产品总说明的功能清单（第 7 章）",
                new_content,
            ),
        ))
        return problems, documents
    if current_block_hash != expected_hash:
        _write_text(overview_full, new_content)
    table[DOC_HASH_KEY] = expected_hash
    table[GENERATED_DOC_PATH_KEY] = overview_rel
    _atomic_write(full, table)
    _save_generation_receipt(project_root, "product_features", table, {overview_rel: new_content})
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


def _test_result_machine_lines(record, row: dict, ac_text: str) -> list[str]:
    """单个测试项的机器事实行（模板字段标签与校验器逐字段比对一致）。"""
    from .artifact_validation import (
        _argv_text,
        _environment_text,
        _output_tail_text,
    )

    checks = [
        ("对应验收条件", ac_text),
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
    return [f"- {label}：{value}" for label, value in checks] + [""]


def generate_test_result_document(
    topic: str,
    table: dict,
    tasks_by_id: dict,
    plan_table: dict | None = None,
    project_root: str = "",
) -> str:
    """按结果表和当前机器记录生成测试结果文档；版本 1 表用旧渲染，版本 2 表按模板六节渲染。"""
    if _table_version_of(table) == "1":
        content = _generate_test_result_document_v1(topic, table, tasks_by_id, plan_table)
    else:
        content = _generate_test_result_document_v2(topic, table, tasks_by_id, plan_table, project_root)
    return markdown_links_mod.with_heading_anchors(content)


def _generate_test_result_document_v1(
    topic: str,
    table: dict,
    tasks_by_id: dict,
    plan_table: dict | None = None,
) -> str:
    """版本 1 测试结果渲染（历史轮次冻结口径，与升级前逐字节一致）。"""
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
        lines += _test_result_machine_lines(record, row, ac_by_id.get(test_id, ""))
    return "\n".join(lines)


def _generate_test_result_document_v2(
    topic: str,
    table: dict,
    tasks_by_id: dict,
    plan_table: dict | None = None,
    project_root: str = "",
) -> str:
    """版本 2 测试结果渲染：模板六节全部生成，机器事实由程序写入（R16/R18）。"""
    workflow_id = str(table.get("工作流编号", ""))
    file_key = topic_file_key(project_root, topic) if project_root and topic else topic
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
    # 人工验收状态按测试计划表"测试方式"列判定（R18：不靠 AI 手写标注）
    needs_manual = False
    tc_names: dict[str, str] = {}
    ac_by_id: dict[str, str] = {}
    for row in (plan_table or {}).get("测试项", []):
        if isinstance(row, dict):
            _tc = str(row.get("测试项编号", "")).strip()
            tc_names[_tc] = str(row.get("直白测试名称", "")).strip() or _tc
            ac_by_id[_tc] = str(row.get("对应验收条件", "")).strip()
            if str(row.get("测试方式", "")).strip() in {"人工验收", "自动化测试 + 人工验收"}:
                needs_manual = True
    finished_times = []
    for _row in table.get("测试结果", []):
        _task = tasks_by_id.get(str(_row.get("测试项编号", "")).strip())
        _rec = _task.current_record if _task is not None else None
        if _rec is not None and getattr(_rec, "finished_at", None):
            finished_times.append(str(_rec.finished_at))
    finish_time = max(finished_times) if finished_times else "待全部测试项执行完成后回填"
    lines = [
        f"# 【主题测试结果】{topic}",
        "",
        f"- 工作流编号：{workflow_id}",
        f"- 验收主题：{topic}",
        f"- 自动化测试结果：{_overall}",
        f"- 人工验收状态：{'待主题验收' if needs_manual else '无需人工验收'}",
        f"- 测试完成时间：{finish_time}",
        "",
        "## 1. 测试依据",
        "",
        f"- [验收计划](../acceptance/{file_key}_验收计划.md)",
        f"- [测试计划](./{file_key}_测试计划.md)",
        f"- [代码计划、实施和结果](../impl/{file_key}_实施记录.md)",
        "- [需求交付追踪表](../需求交付追踪表.md)",
        "",
        "## 2. 测试环境和执行说明",
        "",
    ]
    items = [str(x) for x in table.get("执行说明", []) if str(x).strip()]
    lines += [f"- {x}" for x in items] if items else ["- 暂无"]
    lines += ["", "## 3. 测试项结果", ""]
    for row in table.get("测试结果", []):
        test_id = str(row.get("测试项编号", "")).strip()
        task = tasks_by_id.get(test_id)
        record = task.current_record if task is not None else None
        display_name = tc_names.get(test_id) or str(row.get("实际结果说明", ""))[:40]
        lines += [f"### {test_id}：{display_name}", ""]
        if record is None:
            lines += ["- 自动化测试结果：未执行", ""]
            continue
        lines += _test_result_machine_lines(record, row, ac_by_id.get(test_id, ""))
    lines += ["## 4. 人工验收交接", ""]
    handoff_items = [str(x) for x in table.get("人工验收交接", []) if str(x).strip()]
    if handoff_items:
        lines += [f"- {x}" for x in handoff_items]
    elif needs_manual:
        lines += ["待填写：混合测试的人工验收对象、检查方法、自动化已证明部分与还需用户确认的内容"]
    else:
        lines += ["无需人工验收"]
    lines += ["", "## 5. 未通过或阻塞", ""]
    fail_items = [str(x) for x in table.get("未通过或阻塞", []) if str(x).strip()]
    lines += [f"- {x}" for x in fail_items] if fail_items else ["暂无"]
    lines += _narrative_result_section(table)
    lines += _declaration_section(table)
    lines += [
        "",
        "## 6. 上下游文档",
        "",
        "| 关系 | 文档 | 说明 |",
        "|---|---|---|",
        f"| 上游 | [验收计划](../acceptance/{file_key}_验收计划.md) | 说明什么算完成 |",
        f"| 上游 | [测试计划](./{file_key}_测试计划.md) | 说明本次覆盖哪些测试项 |",
        f"| 上游 | [实施记录](../impl/{file_key}_实施记录.md) | 说明本次代码怎样实现 |",
        "| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整链路 |",
        (
            # 模板规则：验收结果文档真实生成后才改成链接（纯人工主题写无自动化测试结果）
            f"| 下游 | [{topic}验收结果](../acceptance/{file_key}_验收结果.md) | 混合测试在这里接收人工确认 |"
            if project_root and os.path.isfile(
                os.path.join(project_root, "acceptance", f"{file_key}_验收结果.md")
            )
            else f"| 下游 | `acceptance/{file_key}_验收结果.md`（待生成） | 混合测试在这里接收人工确认 |"
        ),
        "",
    ]
    return "\n".join(lines)


def _narrative_result_section(table: dict) -> list[str]:
    items = [str(x) for x in table.get("结果说明", []) if str(x).strip()]
    if not items:
        return []
    return ["", "### 结果说明", ""] + [f"- {x}" for x in items]


def sync_stage_tables(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[list[tuple[str, str]], list[str]]:
    """第二道门前同步当前环节的工作记录表：校验、按表生成文档、检测手改。"""
    from .topic import acceptance_topics

    stage = wf_state.current_stage
    kinds = stage_table_kinds(stage)
    if not kinds:
        return [], []
    try:
        topics = acceptance_topics(
            project_root, wf_state.intent, stage, list(wf_state.topics)
        )
    except ValueError:
        # 索引格式错误由各阶段校验报告；此处回退 state 主题，不中断同步。
        topics = list(wf_state.topics) or []
    # 断言三（表为唯一输入）：中途新增主题时索引尚是"待生成"占位、文档未生成，
    # 主题解析可能失败或拿不到新主题；此时从 topic_relations 表读取并合并，
    # 使文档生成不被"索引需要文档、文档需要主题"的循环卡死。
    _relations_rel = table_relative_path(
        project_root, wf_state.workflow_id, "topic_relations", ""
    )
    if table_exists(project_root, _relations_rel):
        try:
            _ttable = load_table(os.path.join(project_root, _relations_rel))
            _table_topics = [
                str(r.get("验收主题", "")).strip()
                for r in _ttable.get("主题关系", [])
                if str(r.get("验收主题", "")).strip()
            ]
        except RecordsError:
            _table_topics = []
        # 表内主题为准（保留 state 主题中已不在表里的历史主题，避免误删）
        topics = list(dict.fromkeys([*topics, *_table_topics]))
    if not topics:
        topics = list(wf_state.topics) or []
    # R11：表启用以开工时冻结的标记为准；旧轮次没有冻结版本时才走原有文档检查。
    if not workflow_uses_tables(wf_state, project_root):
        return [], []
    if stage == "reproduce":
        from .topic import list_reproduce_topics

        required_topics = list(dict.fromkeys(topics + list_reproduce_topics(project_root, wf_state.workflow_id)))
        return _sync_bug_record_tables(project_root, wf_state.workflow_id, required_topics=required_topics)
    if stage == "update_code_design":
        return _sync_design_tables(project_root, wf_state)
    problems: list[tuple[str, str]] = []
    documents: list[str] = []
    written_docs: set[str] = set()  # 本轮门禁首次真实生成的正式文档（触发生成方）
    receipt_targets: set[tuple[str, str]] = set()
    for kind in kinds:
        for topic in ([""] if kind in WORKFLOW_LEVEL_KINDS else topics or [""]):
            receipt_targets.add((kind, topic))
            relative = table_relative_path(project_root, wf_state.workflow_id, kind, topic)
            if table_exists(project_root, relative):
                table = load_table(os.path.join(project_root, relative))
                problems.extend(_program_field_problems(project_root, kind, table))
                doc_path = _expected_document_path(project_root, kind, topic, table)
                receipt_targets.update(_document_reference_map(project_root, wf_state.workflow_id, topic).get(doc_path, []))
    if problems:
        return problems, []
    # 首次接续旧表先核实上游原文，再生成下游；否则新增链接会改变旧表的可重建内容。
    for kind, topic in sorted(receipt_targets):
        relative = table_relative_path(project_root, wf_state.workflow_id, kind, topic)
        if table_exists(project_root, relative):
            table = load_table(os.path.join(project_root, relative))
            if not _program_field_problems(project_root, kind, table) and _load_generation_receipt(project_root, kind, table) is None:
                _save_generation_receipt(project_root, kind, table)
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
        # R19 第⑤条：本环节按主题建表时，某主题缺表要报具体错误，不静默跳过
        needs_topic_table = kind in {
            "acceptance_plan", "impl_record", "test_plan", "test_result",
            "acceptance_result",
        }
        for topic in targets:
            relative = table_relative_path(project_root, wf_state.workflow_id, kind, topic)
            if not table_exists(project_root, relative):
                if needs_topic_table and topic:
                    problems.append((
                        CONTENT_CATEGORY,
                        f"主题「{topic}」缺少{KIND_SCHEMAS[kind]['doc_name']}工作记录表（{relative}）；"
                        "请执行 workflow scaffold 补齐后重新门禁",
                    ))
                continue
            table = load_table(os.path.join(project_root, relative))
            if kind == "test_result":
                # 机器采集（主题一）：三列回填先于空表守卫——程序把当前任务的
                # 编号/结论/机器记录写进表后，表即非空；无任务的表保持空由
                # 守卫报告。回填失败（如表结构异常）不阻塞，交给后续校验。
                try:
                    _fill_machine_record_ids(project_root, wf_state, topic, table)
                except Exception:
                    pass
            if kind != "topic_relations" and not table_is_filled(table):
                # R11：空表也属于启用表流程，报"尚未填写"，不退回文档模式
                if any(
                    definition.get("required_at_gate")
                    for definition in KIND_SCHEMAS[kind]["row_lists"].values()
                ):
                    problems.append((
                        CONTENT_CATEGORY,
                        f"主题「{topic or kind}」的{KIND_SCHEMAS[kind]['doc_name']}工作记录表尚未填写内容；"
                        "请填写表内必填栏目后重新门禁（程序不会退回文档模式读取正式文档）",
                    ))
                continue
            documents.append(relative)
            kind_problems = validate_table(kind, table, _workflow_table_version(project_root, wf_state.workflow_id), project_root=project_root)
            if kind == "topic_relations":
                problems.extend(kind_problems)
                continue
            problems.extend(kind_problems)
            if any(category == FORMAT_CATEGORY for category, _ in kind_problems):
                continue
            if kind == "test_result":
                record_problems = _fill_machine_record_ids(project_root, wf_state, topic, table)
                problems.extend(record_problems)
            if kind == "acceptance_result":
                record_problems = _fill_acceptance_record_ids(wf_state, topic, table)
                problems.extend(record_problems)
                if record_problems:
                    continue
            if kind == "test_plan" and topic:
                pass
            doc_relative = _expected_document_path(project_root, kind, topic, table)
            doc_full = os.path.join(project_root, doc_relative)
            expected_content = generate_document(kind, table, project_root=project_root, wf_state=wf_state)
            if _document_was_edited(project_root, kind, table, doc_relative, expected_content):
                problems.append((
                    CONTENT_CATEGORY,
                    _table_document_conflict_facts(
                        project_root,
                        kind,
                        table,
                        doc_relative,
                        f"{KIND_SCHEMAS[kind]['doc_name']}（按表生成的章节）",
                        expected_content,
                    ),
                ))
                continue
            if kind == "test_result" and wf_state.stages.get("qa") is not None:
                tasks_by_id = wf_state.stages["qa"].test_tasks.get(topic, {})
                plan_table = None
                plan_relative = table_relative_path(project_root, wf_state.workflow_id, "test_plan", topic)
                if table_exists(project_root, plan_relative):
                    plan_table = load_table(os.path.join(project_root, plan_relative))
                content = generate_test_result_document(
                    topic, table, tasks_by_id, plan_table, project_root=project_root
                )
            else:
                content = expected_content
            existed_before = os.path.isfile(doc_full)
            content = markdown_links_mod.with_heading_anchors(content, previous_content=_read_document(doc_full))
            _write_text(doc_full, content)
            table[DOC_HASH_KEY] = _file_sha256(doc_full)
            table[GENERATED_DOC_PATH_KEY] = doc_relative
            _atomic_write(os.path.join(project_root, relative), table)
            _save_generation_receipt(project_root, kind, table, {doc_relative: content})
            if kind == "bug_record":
                # 模板要求缺陷记录落在 bug/ 目录（缺陷记录 + 索引），按表内容同步生成。
                # 与其它环节文档一样先检出手改：命中时保留磁盘内容并报告，不覆盖。
                bug_problems = _write_bug_documents(project_root, table)
                problems.extend(bug_problems)
                if not bug_problems:
                    documents.extend(
                        rel for rel, _ in _bug_defect_documents(table, project_root)
                    )
                    _atomic_write(os.path.join(project_root, relative), table)
            if not existed_before:
                # 本环节首次真实生成的下游文档，触发上游引用回补
                written_docs.add(doc_relative)
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
    # 下游文档真实生成后，反向回补引用它的上游文档（如验收计划的下游链接），不无脑全刷。
    documents.extend(
        _backfill_referencing_documents(
            project_root, wf_state.workflow_id, topics, set(written_docs)
        )
    )
    return problems, documents


def _check_architecture_change_references(
    project_root: str,
    table: dict,
) -> list[tuple[str, str]]:
    """正文变更的代码位置引用按真实代码符号核对（机器采集延伸）。

    从正文变更的 依据 与 新文 列提取 文件::符号 引用：.py 文件按符号
    索引核对（不存在给相近符号建议）；非 Python 文件查存在；不存在的
    文件报路径无效。返回内容问题清单。
    """
    changes = table.get("正文变更", [])
    if not isinstance(changes, list) or not changes:
        return []
    from . import code_symbols as code_symbols_mod

    index, failures = code_symbols_mod.build_symbol_index(project_root)
    problems: list[tuple[str, str]] = []
    if failures:
        problems.append((
            CONTENT_CATEGORY,
            "代码符号索引存在解析失败文件（不影响其余核对）：" + "、".join(failures),
        ))
    for position, row in enumerate(changes, 1):
        if not isinstance(row, dict):
            continue
        texts = [
            str(row.get("新文", "") or ""),
            str(row.get("依据", "") or ""),
        ]
        for text in texts:
            for detail in code_symbols_mod.check_text_references(
                project_root, index, text
            ):
                problems.append((
                    CONTENT_CATEGORY,
                    f"正文变更第 {position} 行的代码位置引用核对失败：{detail}",
                ))
    return problems


def _sync_design_tables(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[list[tuple[str, str]], list[str]]:
    from .design_sync import prepare_design_sync

    problems: list[tuple[str, str]] = []
    tables: dict[str, tuple[str, dict]] = {}
    outputs: dict[str, str] = {}
    for kind in ("design_sync", "architecture_changes"):
        relative = table_relative_path(project_root, wf_state.workflow_id, kind, "")
        if not table_exists(project_root, relative):
            if kind == "design_sync":
                problems.append((CONTENT_CATEGORY, f"缺少最终同步工作记录表 {relative}"))
            continue
        try:
            table = load_table(os.path.join(project_root, relative))
            if table.get("工作流编号") != wf_state.workflow_id or table.get("验收主题") != "":
                problems.append((CONTENT_CATEGORY, f"{relative} 的轮次或主题身份不正确；最终同步使用本轮轮次级表"))
                continue
            table_problems = validate_table(kind, table, _workflow_table_version(project_root, wf_state.workflow_id), project_root=project_root)
            # 机器采集延伸：正文变更的 文件::符号 引用按真实代码符号核对
            if kind == "architecture_changes":
                symbol_problems = _check_architecture_change_references(
                    project_root, table
                )
                table_problems = [*table_problems, *symbol_problems]
            problems.extend((category, f"{relative}：{detail}") for category, detail in table_problems)
            if table_problems:
                continue
            doc_relative = _expected_document_path(project_root, kind, "", table)
            content = generate_document(kind, table, project_root=project_root, wf_state=wf_state)
            if _document_was_edited(project_root, kind, table, doc_relative, content):
                problems.append((CONTENT_CATEGORY, f"{doc_relative} 被直接修改；请把事实写回 {relative}，保留现有文档"))
                continue
            outputs[doc_relative] = markdown_links_mod.with_heading_anchors(content, previous_content=_read_document(os.path.join(project_root, doc_relative)))
            tables[kind] = (relative, table)
        except RecordsError as exc:
            problems.append((FORMAT_CATEGORY, str(exc)))
    if problems:
        return problems, []
    sync_table = tables["design_sync"][1]
    receipt = _load_generation_receipt(project_root, "design_sync", sync_table)
    previous = receipt.get("architecture") if receipt is not None else None
    if previous is not None and not isinstance(previous, dict):
        return [(FORMAT_CATEGORY, "正式架构生成凭据损坏；保留正式架构，不重建基准")], []
    architecture = artifact_paths_mod.CODE_DESIGN_DOC
    current = _read_document(os.path.join(project_root, architecture))
    try:
        content, baseline = prepare_design_sync(
            project_root, wf_state, sync_table,
            tables.get("architecture_changes", ("", None))[1], current, previous,
        )
    except ValueError as exc:
        return [(CONTENT_CATEGORY, str(exc))], []
    outputs[architecture] = content
    for relative, content in outputs.items():
        _write_text(os.path.join(project_root, relative), content)
    for kind, (relative, table) in tables.items():
        doc_relative = _expected_document_path(project_root, kind, "", table)
        table[GENERATED_DOC_PATH_KEY] = doc_relative
        table[DOC_HASH_KEY] = _file_sha256(os.path.join(project_root, doc_relative))
        _atomic_write(os.path.join(project_root, relative), table)
        _save_generation_receipt(project_root, kind, table, {doc_relative: outputs[doc_relative]})
    receipt = _load_generation_receipt(project_root, "design_sync", sync_table)
    receipt["architecture"] = baseline
    _atomic_write(_generation_receipt_path(project_root, "design_sync", sync_table), receipt)
    return [], [relative for relative, _ in tables.values()] + list(outputs)


def bug_file_key(project_root: str, defect_name: str) -> str:
    """缺陷记录的稳定文件标识：与门禁登记同取缺陷分类，避免生成路径与登记路径分叉。"""
    from .project import load_project

    return artifact_paths_mod.resolve_key_for(load_project(project_root), "bug", defect_name)


def _anchored_heading(heading: str) -> list[str]:
    """缺陷记录固定章节标题带稳定锚点，供上游按章节编号直接链接（R17）。"""
    anchor = re.sub(r"[^a-z0-9\u4e00-\u9fff:-]", "-", heading.replace(". ", "-").strip().lower())
    return [f'<a id="{anchor}"></a>', f"## {heading}", ""]


def refresh_references_after_removal(
    project_root: str,
    wf_state,
    topics: list[str],
) -> list[str]:
    """删除下游结果文件后，把引用它们的上游文档和索引改回“（待生成）”。

    退回和自动失效都会删除测试结果、验收结果等下游文档，但指向它们的链接是程序
    自己写进上游文档和索引的。删除时不同步回补，下一次门禁就会把这些链接报成坏
    链接（模板规则：目标文件不存在时只写普通路径加“（待生成）”）。
    返回实际重写的文档路径；表未启用或表缺失时安全返回空清单。
    """
    if not workflow_uses_tables(wf_state, project_root):
        return []
    refreshed: list[str] = []
    for index_path in regenerate_workflow_indexes(project_root, wf_state.workflow_id):
        refreshed.append(index_path)
    referencing_kinds = (
        "acceptance_plan",
        "impl_record",
        "test_plan",
        "test_result",
        "acceptance_result",
    )
    for topic in topics or []:
        for kind in referencing_kinds:
            try:
                refreshed.extend(
                    _refresh_stage_document(
                        project_root,
                        wf_state.workflow_id,
                        kind,
                        topic,
                        only_existing=True,
                    )
                )
            except RecordsError:
                # 表损坏由所属环节的表校验报告；回补不接管它的诊断，也不中断其它主题。
                continue
    return list(dict.fromkeys(refreshed))


def _bug_defect_documents(table: dict, project_root: str, *, index_content: str | None = None) -> list[tuple[str, str]]:
    """按 bug_record 表生成模板结构的缺陷记录文档与索引条目（bug/ 目录）。"""
    topic_name = str(table.get("验收主题", "")).strip() or "缺陷记录"
    workflow_id = str(table.get("工作流编号", ""))
    file_key = bug_file_key(project_root, topic_name)
    rows = [row for row in table.get("缺陷信息", []) if isinstance(row, dict)]
    lines: list[str] = [
        f"# 【缺陷】{topic_name}",
        "",
        f"- 工作流编号：{workflow_id}",
        "- 复现状态：已复现",
        "- 根因状态：已确认",
        f"- 验收主题：{topic_name}",
        "",
    ]
    lines += _anchored_heading("1. 缺陷现象")
    lines += [f"- {row.get('现象', '')}".rstrip() for row in rows]
    lines += [""] + _anchored_heading("2. 真实复现条件")
    if _table_version_of(table) == "3":
        for key in ("运行环境", "真实输入"):
            lines += [f"- {key}：{item}" for item in table.get(key, []) if str(item).strip()]
    conditions = table.get("真实复现条件", table.get("缺陷说明", []) if _table_version_of(table) == "1" else [])
    lines += [f"- {item}".rstrip() for item in conditions if str(item).strip()]
    lines += [""] + _anchored_heading("3. 复现步骤")
    lines += [f"- {row.get('复现步骤', '')}".rstrip() for row in rows]
    lines += [""] + _anchored_heading("4. 实际结果")
    lines += [f"- {row.get('实际结果', row.get('现象', ''))}".rstrip() for row in rows]
    lines += [""] + _anchored_heading("5. 期望结果")
    lines += [f"- {row.get('期望结果', row.get('预期行为', ''))}".rstrip() for row in rows]
    lines += [""] + _anchored_heading("6. 根因")
    for row in rows:
        lines += [f"**{row.get('缺陷编号', '')}**", ""]
        if _table_version_of(table) == "3":
            segments = [f"{key}：{row.get(key, '')}" for key in ("根因说明", "根因位置", "根因证据")]
        else:
            root_cause = str(row.get("根因", "")).strip()
            segments = re.split(r"(?=根因说明：|根因位置：|根因证据：)", root_cause)
        for segment in segments:
            segment = segment.strip()
            if segment:
                lines.append(f"- {segment}")
        lines.append("")
    lines += _anchored_heading("7. 修复仍存在的不确定性")
    uncertainty = [str(x).strip() for x in table.get("修复仍存在的不确定性", []) if str(x).strip()]
    lines += [f"- {item}" for item in uncertainty] or ["暂无"]
    lines += [""] + _anchored_heading("8. 修复与验收结果")
    lines += [f"- {item}".rstrip() for item in table.get("修复与验收结果", []) if str(item).strip()]
    defect_rel = f"bug/缺陷_{file_key}.md"
    # 第 8 节的阶段结论块由主题验收、全量回归和整体验收按实际结果追加，不来自本表；
    # 重新生成时原样保留，否则重走缺陷复现会抹掉已经发生的事实。
    preserved = _existing_bug_result_blocks(os.path.join(project_root, defect_rel))
    if preserved:
        lines += ["", *preserved]
    documents: list[tuple[str, str]] = [(defect_rel, markdown_links_mod.with_heading_anchors("\n".join(lines).rstrip() + "\n"))]

    from .bug_record import index_entry, index_width, replace_index_entry

    first_row = rows[0] if rows else {}
    index_cells = [
        f"[{topic_name}](./缺陷_{file_key}.md)",
        _inline_cell(first_row.get("现象", "")),
        _inline_cell(first_row.get("根因说明", first_row.get("根因", ""))),
        "根因已确认",
    ]
    if index_content is None:
        index_content = _read_document(os.path.join(project_root, "bug", "索引.md"))
    if index_width(index_content) == 2:
        index_cells = [index_cells[0], index_cells[-1]]
    entry = index_entry(index_content, f"缺陷_{file_key}.md")
    if entry is not None:
        row_range, current_cells = entry
        index_cells[-1] = current_cells[-1]
        index_content = replace_index_entry(index_content, row_range, index_cells)
    else:
        if not index_content:
            index_content = "# Bug 索引\n\n| Bug 记录 | 现象 | 根因 | 状态 |\n|---|---|---|---|\n"
        index_row = "| " + " | ".join(_md_cell(cell) for cell in index_cells) + " |\n"
        index_content = index_content.rstrip() + "\n" + index_row
    documents.append(("bug/索引.md", index_content))
    return documents


_BUG_RESULT_SECTION_RE = re.compile(
    r"^##\s+8\.\s*修复与验收结果\s*$\n(.*?)(?=^##\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _existing_bug_result_blocks(full_path: str) -> list[str]:
    """读出缺陷记录第 8 节里由后续阶段追加的结论块（以三级标题开头的段落）。"""
    try:
        with open(full_path, "r", encoding="utf-8") as stream:
            content = stream.read()
    except OSError:
        return []
    section = _BUG_RESULT_SECTION_RE.search(content)
    if section is None:
        return []
    blocks = re.findall(r"^###\s+.*?(?=^###\s+|\Z)", section.group(1), re.MULTILINE | re.DOTALL)
    return [block.rstrip() for block in blocks if block.strip()]


def _write_bug_documents(project_root: str, table: dict) -> list[tuple[str, str]]:
    """写缺陷记录与缺陷索引；文档被绕过表直接修改时报告并保留手改内容（R5）。"""
    problems = _program_field_problems(project_root, "bug_record", table)
    if problems:
        return problems
    stored = table.get(BUG_DOC_HASHES_KEY)
    recorded = dict(stored) if isinstance(stored, dict) else {}
    pending: list[tuple[str, str, str]] = []
    for relative, content in _bug_defect_documents(table, project_root):
        full = os.path.join(project_root, relative)
        content = markdown_links_mod.with_heading_anchors(content, previous_content=_read_document(full))
        current = _file_sha256(full) if os.path.isfile(full) else None
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if current == expected:
            recorded[relative] = expected
            continue
        if _document_was_edited(project_root, "bug_record", table, relative, content):
            problems.append((
                CONTENT_CATEGORY,
                _table_document_conflict_facts(
                    project_root,
                    "bug_record",
                    table,
                    relative,
                    "缺陷记录（按表生成的章节）",
                    content,
                ),
            ))
            continue
        pending.append((relative, content, expected))
    if problems:
        return problems
    for relative, content, expected in pending:
        _write_text(os.path.join(project_root, relative), content)
        recorded[relative] = expected
    table[BUG_DOC_HASHES_KEY] = recorded
    _save_generation_receipt(project_root, "bug_record", table, {relative: _read_document(os.path.join(project_root, relative)) for relative in recorded})
    return problems


def _sync_bug_record_tables(
    project_root: str,
    workflow_id: str,
    *,
    required_topics: list[str] | None = None,
    selected_topics: list[str] | None = None,
    regenerate: bool = True,
) -> tuple[list[tuple[str, str]], list[str]]:
    """缺陷整批预检后生成；任一输入或正文冲突都不覆盖本批正式文档。"""
    problems, tables = bug_record_tables(project_root, workflow_id, required_topics)
    if selected_topics:
        base = table_relative_path(project_root, workflow_id, "bug_record", "")
        tables = [(relative, table) for relative, table in tables
                  if table["验收主题"] in selected_topics or ("" in selected_topics and relative == base)]
        found = {table["验收主题"] for _, table in tables}
        for topic in selected_topics:
            if topic and topic not in found:
                problems.append((CONTENT_CATEGORY, f"主题「{topic}」缺少缺陷记录工作记录表"))
    if not tables and not problems:
        problems.append((CONTENT_CATEGORY, "缺陷记录工作记录表尚未填写内容；请逐个主题填写复现事实"))
    outputs: dict[str, str] = {}
    internal_paths: dict[str, str] = {}
    version = _workflow_table_version(project_root, workflow_id)
    for relative, table in tables:
        table_problems = validate_table("bug_record", table, version, project_root=project_root)
        problems.extend((category, f"{relative}：{detail}") for category, detail in table_problems)
        if table_problems:
            continue
        try:
            internal = _expected_document_path(project_root, "bug_record", table["验收主题"], table)
            generated = {internal: generate_document("bug_record", table, project_root=project_root)}
            generated.update(_bug_defect_documents(table, project_root, index_content=outputs.get("bug/索引.md")))
            for path, content in generated.items():
                current = _read_document(os.path.join(project_root, path))
                if path.startswith("bug/缺陷_") and current:
                    from .topic import TOPIC_FIELD_RE, WORKFLOW_FIELD_RE

                    owner = WORKFLOW_FIELD_RE.search(current)
                    topic_owner = TOPIC_FIELD_RE.search(current)
                    if owner is None or owner.group(1).strip() != workflow_id or topic_owner is None or topic_owner.group(1).strip() != table["验收主题"]:
                        problems.append((CONTENT_CATEGORY, f"{path} 已有内容的轮次或主题与 {relative} 冲突，保留原文"))
                        continue
                if _document_was_edited(project_root, "bug_record", table, path, content):
                    problems.append((CONTENT_CATEGORY, f"正式文档 {path} 与 {relative} 不一致：文档被直接修改；请把改动写回工作记录表，程序不会覆盖手改内容"))
                outputs[path] = markdown_links_mod.with_heading_anchors(content, previous_content=current)
            internal_paths[relative] = internal
        except (RecordsError, ValueError) as exc:
            problems.append((CONTENT_CATEGORY, f"{relative}：{exc}"))
    if problems:
        return problems, []
    documents = [relative for relative, _ in tables] + list(outputs)
    if not regenerate:
        return [], documents
    for path, content in outputs.items():
        _write_text(os.path.join(project_root, path), content)
    for relative, table in tables:
        internal = internal_paths[relative]
        defect = f"bug/缺陷_{bug_file_key(project_root, table['验收主题'])}.md"
        table[GENERATED_DOC_PATH_KEY] = internal
        table[DOC_HASH_KEY] = _file_sha256(os.path.join(project_root, internal))
        table[BUG_DOC_HASHES_KEY] = {path: _file_sha256(os.path.join(project_root, path)) for path in (defect, "bug/索引.md")}
        _atomic_write(os.path.join(project_root, relative), table)
        _save_generation_receipt(project_root, "bug_record", table, {path: outputs[path] for path in (internal, defect, "bug/索引.md")})
    return [], documents


def _inline_cell(value: object) -> str:
    return re.sub(r"\s*\r?\n\s*", " ", str(value)).strip()


def _document_reference_map(project_root: str, workflow_id: str, topic: str) -> dict[str, list[tuple[str, str]]]:
    """某主题工作流内文档的下游引用登记：生成 X 时需要回补哪些引用了 X 的表文档。

    方向固定为「被生成文档路径 → 待回补的（表类型, 主题）」：只刷新引用方，不无脑全刷。
    新环节模板加入带存在性的下游链接时，在本表加一行即可复用同一回补程序。
    """
    file_key = topic_file_key(project_root, topic) if topic else ""
    refs: dict[str, list[tuple[str, str]]] = {}
    if file_key:
        for generator_path in (
            f"impl/{file_key}_实施记录.md",
            f"qa/{file_key}_测试计划.md",
            f"acceptance/{file_key}_验收结果.md",
        ):
            refs.setdefault(generator_path, []).append(("acceptance_plan", topic))
        # 验收结果文档生成后，验收计划、实施记录与测试结果中的引用都要回补为真实链接
        refs.setdefault(f"acceptance/{file_key}_验收结果.md", []).append(
            ("impl_record", topic)
        )
        refs.setdefault(f"acceptance/{file_key}_验收结果.md", []).append(
            ("test_result", topic)
        )
        # 测试结果文档生成后，同主题五类环节文档中指向它的引用都要回补为真实链接
        result_refs = refs.setdefault(f"qa/{file_key}_测试结果.md", [])
        for referencing_kind in (
            "acceptance_plan",
            "impl_record",
            "test_plan",
            "test_result",
            "acceptance_result",
        ):
            if (referencing_kind, topic) not in result_refs:
                result_refs.append((referencing_kind, topic))
    return refs


def _backfill_referencing_documents(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    written_paths: set[str],
) -> list[str]:
    """下游文档真实生成后，反向查找引用它的上游文档并重刷（模板规则：文件真实生成才改成链接）。

    只重写生成文档并更新程序专用键，表内容不变，不触发下游失效（R7）；
    检测到手改的文档跳过，由本环节手改报告处理。
    """
    refreshed: list[str] = []
    if not written_paths:
        return refreshed
    targets: set[tuple[str, str]] = set()
    for topic in topics or [""]:
        for path in written_paths:
            targets.update(_document_reference_map(project_root, workflow_id, topic).get(path, []))
    for kind, topic in sorted(targets):
        refreshed.extend(_refresh_stage_document(project_root, workflow_id, kind, topic))
    return refreshed


def _refresh_stage_document(
    project_root: str,
    workflow_id: str,
    kind: str,
    topic: str,
    *,
    only_existing: bool = False,
) -> list[str]:
    """按当前表重新生成某主题的正式文档（检测到手改时跳过并报告）。返回生成路径。

    ``only_existing`` 供删除后回补使用：只刷新磁盘上仍存在的引用方文档，不重新
    生成刚被退回或失效删除的结果文档，否则回补会把已经作废的结论恢复回来。
    """
    relative = table_relative_path(project_root, workflow_id, kind, topic)
    if not table_exists(project_root, relative):
        return []
    table = load_table(os.path.join(project_root, relative))
    if not table_is_filled(table):
        return []
    if _program_field_problems(project_root, kind, table):
        return []
    doc_relative = _expected_document_path(project_root, kind, topic, table)
    doc_full = os.path.join(project_root, doc_relative)
    if only_existing and not os.path.isfile(doc_full):
        return []
    current_hash = _file_sha256(doc_full) if os.path.isfile(doc_full) else None
    # 回补必须与主生成路径使用同一台机器事实来源：test_result 文档渲染依赖
    # qa 阶段 test_tasks，缺少 wf_state 时空任务集会覆盖已通过结果（BUG-09）。
    wf_state = None
    if kind == "test_result":
        wf_state = state_mod.load_state(project_root)
        if (
            wf_state is None
            or wf_state.workflow_id != workflow_id
            or wf_state.stages.get("qa") is None
            or not wf_state.stages["qa"].test_tasks.get(topic)
        ):
            # 拿不到当前机器任务集时不重写，保留磁盘上已有的正式结果文档。
            return []
    content = generate_document(kind, table, project_root=project_root, wf_state=wf_state)
    if _document_was_edited(project_root, kind, table, doc_relative, content):
        return []
    content = markdown_links_mod.with_heading_anchors(content, previous_content=_read_document(doc_full))
    if current_hash is not None and content == _read_document(doc_full):
        return [doc_relative]
    _write_text(doc_full, content)
    table[DOC_HASH_KEY] = _file_sha256(doc_full)
    table[GENERATED_DOC_PATH_KEY] = doc_relative
    _atomic_write(os.path.join(project_root, relative), table)
    _save_generation_receipt(project_root, kind, table, {doc_relative: content})
    return [doc_relative]


def _read_document(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read()
    except OSError:
        return ""


def _fill_acceptance_record_ids(
    wf_state: state_mod.WorkflowState | None,
    topic: str,
    table: dict,
    *,
    project_root: str = "",
) -> list[tuple[str, str]]:
    """验收程序编号只取当前有效状态；缺证据时不改表或正式文档。

    R26（v4）：验收方式、验收结论、机器测试记录编号、用户实际回答、人工确认
    五列由程序从当前有效验收记录直接回填，AI 不手抄；回填后校验退化为程序
    自校验。failed/blocked 或记录失效的条目标记"待重做"，AI 叙述栏保留。
    """
    from .acceptance_records import record_is_current

    if _table_version_of(table) == "1":
        return []
    if (
        wf_state is None
        or wf_state.workflow_id != table.get("工作流编号")
        or topic not in wf_state.topics
        or table.get("验收主题") != topic
    ):
        return [(CONTENT_CATEGORY, f"{topic} 的验收结果缺少对应当前轮次的有效状态")]
    stage_state = wf_state.stages.get("topic_acceptance")
    current = stage_state.acceptance_records.get(topic, {}) if stage_state is not None else {}
    problems: list[tuple[str, str]] = []
    updates: list[tuple[dict, str]] = []
    program_fill = _table_version_of(table) == "4"
    for row in table.get("验收结果", []):
        if not isinstance(row, dict):
            continue
        criterion_id = str(row.get("验收条件编号", "")).strip()
        record = current.get(criterion_id)
        if (
            record is None
            or record.topic != topic
            or record.criterion_id != criterion_id
            or not record_is_current(record, wf_state)
        ):
            if program_fill:
                # R26：记录缺失或失效时标记待重做，叙述列保留
                row["验收方式"] = row.get("验收方式") or ""
                row["验收结论"] = "待重做"
                row["机器测试记录编号"] = row.get("机器测试记录编号") or ""
                row["用户实际回答"] = row.get("用户实际回答") or ""
                row["人工确认"] = row.get("人工确认") or ""
                problems.append((
                    CONTENT_CATEGORY,
                    f"{topic} / {criterion_id} 缺少当前有效验收记录，已标记待重做；"
                    "按重新验收后的记录由程序回填",
                ))
            else:
                problems.append((CONTENT_CATEGORY, f"{topic} / {criterion_id} 缺少当前有效验收记录；程序编号不能手填"))
            continue
        if program_fill:
            _fill_acceptance_row_columns(row, record)
        else:
            if row.get("验收方式") != record.method or row.get("验收结论") != record.result:
                problems.append((CONTENT_CATEGORY, f"{topic} / {criterion_id} 的验收方式或结论与当前记录不一致"))
            machine_ids = str(row.get("机器测试记录编号", "")).strip()
            if record.method == "人工验收":
                matching_evidence = machine_ids == "不适用"
            else:
                matching_evidence = set(re.split(r"[、,，;；\s]+", machine_ids)) == set(record.test_record_ids)
            if not matching_evidence:
                problems.append((CONTENT_CATEGORY, f"{topic} / {criterion_id} 的机器测试记录编号与当前验收依据不一致"))
        updates.append((row, record.record_id))
    if not problems:
        for row, record_id in updates:
            row["验收记录编号"] = record_id
    return problems


def _fill_acceptance_row_columns(row: dict, record) -> None:
    """R26：五列由程序从当前有效验收记录取值写入，AI 手填值被程序值覆盖。

    机器测试记录编号取 record.test_record_ids（机器执行记录 RUN-xx），
    与原校验口径一致；纯自动化条件按验收方式归并不适用字段。
    """
    is_automated = str(record.method) == "自动化测试"
    machine_ids = "、".join(
        str(identifier) for identifier in (record.test_record_ids or [])
    ) or "不适用"
    row["验收方式"] = str(record.method or "")
    row["验收结论"] = str(record.result or "")
    row["机器测试记录编号"] = machine_ids
    row["用户实际回答"] = "不适用" if is_automated else str(record.user_answer or "")
    row["人工确认"] = "不适用" if is_automated else "通过"


def _fill_machine_record_ids(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    topic: str,
    table: dict,
) -> list[tuple[str, str]]:
    """测试结果表三列由程序从当前测试任务回填，不由 AI 手抄。

    三列：测试项编号（行存在性）、执行结论、机器记录编号。
    已有行按测试项编号对齐更新三列（AI 叙述列不动）；当前任务在表中
    没有行时按任务追加新行；任务无当前记录时结论与编号留空待执行。
    该主题没有任何测试任务时返回空（空表守卫继续报尚未填写）。
    """
    problems: list[tuple[str, str]] = []
    stage_state = wf_state.stages.get(wf_state.current_stage)
    if stage_state is None:
        stage_state = wf_state.stages.get("qa")
    topic_tasks = stage_state.test_tasks.get(topic, {}) if stage_state is not None else {}
    if not topic_tasks:
        return problems
    from . import machine_collect as machine_collect_mod

    machine_rows = {
        str(row.get("测试项编号", "")).strip(): row
        for row in machine_collect_mod.test_result_columns(
            project_root, wf_state, topic
        )
    }
    # 更新已有行的三列（叙述列不动）
    seen_ids: set[str] = set()
    for row in table.get("测试结果", []):
        if not isinstance(row, dict):
            continue
        test_id = str(row.get("测试项编号", "")).strip()
        seen_ids.add(test_id)
        machine_row = machine_rows.get(test_id)
        if machine_row is None:
            continue
        row["执行结论"] = machine_row["执行结论"]
        row["机器记录编号"] = machine_row["机器记录编号"]
    # 当前任务在表中没有行时追加（新行只含三列机器值，叙述留待 AI）
    for test_id in sorted(machine_rows):
        if test_id in seen_ids:
            continue
        table.setdefault("测试结果", []).append(
            {
                "测试项编号": test_id,
                "执行结论": machine_rows[test_id]["执行结论"],
                "机器记录编号": machine_rows[test_id]["机器记录编号"],
                "实际结果说明": "",
            }
        )
    # 任务无当前记录且结论为空时提示（不阻塞，等待执行）
    for test_id, task in topic_tasks.items():
        if getattr(task, "current_record", None) is None:
            problems.append((
                CONTENT_CATEGORY,
                f"{topic} 的测试项 {test_id} 还没有当前成功机器记录；机器记录编号由程序回填，不能手填",
            ))
    return problems
