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
TABLE_FORMAT_VERSION = "2"

NARRATIVE_KEY = "叙述段落"
DOC_HASH_KEY = "生成文档哈希"
GENERATED_DOC_PATH_KEY = "生成文档路径"

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
    # 测试结果：与 Template_Repository/qa/test.md 模板章节映射（R18）
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
        "代码位置（最终文件）": "最终文件行号范围，例如 L12-L34；局部删除写“基线 L18-L31”；整文件删除写“删除整个文件”",
        "实际执行的动作": "这一步实际增加、删除或修改了什么；写事实，不复制计划文字",
        "当步反馈": "该步完成后的语法、静态检查或局部运行真实反馈；尚未检查时写“待检查”，不写“正式测试通过”",
        "状态": "已完成 或 进行中；全部行完成前不能过第二道门",
    },
    "实际代码修改": {
        "文件": "实际修改文件的项目内相对路径；与 git 真实差异一致，覆盖本轮全部差异文件",
        "代码位置（最终文件）": "最终文件的行号范围，例如 L12-L34；每个不连续差异块都要被至少一行覆盖",
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
        "测试入口": "tests/文件::测试函数；测试文件可以尚未创建，但路径和目标必须明确；人工验收行可留空",
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
        "正式目标名称": "测试报告里的正式目标名，用于精确匹配；人工验收行留空",
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
        "产品设计依据": "现有上游文档的 Markdown 链接加规则级锚点，例如 [工作记录表与正式文档生成 R18](../spec/功能_工作记录表与正式文档生成.md#r-18)；每条规则单独成链、可直接导航到规则行；链接从本主题文档出发可解析；不引用本轮内部代号",
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
        "根因": "导致缺陷的具体判断、状态、数据、配置或外部行为，写到具体位置",
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
                "required_at_gate": False
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
WORKFLOW_LEVEL_KINDS = {"product_features", "topic_relations", "spike_conclusion", "bug_record", "design_sync"}

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


# 表格式版本 → schema/hints。版本 1 是历史轮次冻结使用的快照，保留用于按冻结版本
# 校验和生成旧表（R18：版本 2 只对开工时冻结为版本 2 的轮次生效，旧轮次不迁移）。
_SUPPORTED_TABLE_VERSIONS = {"1", "2"}


def _schema(kind: str, version: str | None = None) -> dict:
    version = version or TABLE_FORMAT_VERSION
    schemas = _LEGACY_KIND_SCHEMAS if version == "1" else KIND_SCHEMAS
    if kind not in schemas:
        raise RecordsError(f"未知的工作记录表类型：{kind}")
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


def _build_hints(schema: dict, hints_map: dict[str, dict[str, str]]) -> dict[str, object]:
    hints: dict[str, object] = {}
    for key in schema["row_lists"]:
        hints[key] = {
            c: hints_map.get(key, {}).get(c, "按栏目含义填写")
            for c in schema["row_lists"][key]["columns"]
        }
    for key in schema["narrative"]:
        hints[key] = NARRATIVE_HINT
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
        expected_keys = set(schema["row_lists"]) | set(schema["narrative"])
        current_hints = table.get("填写说明")
        if not isinstance(current_hints, dict) or set(current_hints) != expected_keys:
            table["填写说明"] = _build_hints(schema, _hints_for(table_version))
            changed = True
        if changed:
            _atomic_write(full, table)
        return relative
    table: dict = _fixed_fields(workflow_id, topic, version)
    for key in schema["row_lists"]:
        table[key] = []
    for key in schema["narrative"]:
        table[key] = []
    for key in schema["enums"]:
        table[key] = schema["enums"][key][0]
    table["填写说明"] = _build_hints(schema, _hints_for(version))
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


def validate_table(kind: str, table: dict, expected_version: str | None = None) -> list[tuple[str, str]]:
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
        elif key == "表版本" and value.strip() != expected_version:
            problems.append(
                (CONTENT_CATEGORY, f"固定栏目 表版本 必须是本轮冻结的 {expected_version}，实际为 {value.strip()!r}")
            )
    # R19⑥：纯流程主题（版本 2 impl_record）计划行全部填标记时，
    # 代码结果类行清单不要求非空；标记与真实代码行混表按普通内容报错。
    flow_only_exempt = (
        kind == "impl_record"
        and expected_version == "2"
        and impl_table_exempts_code_result_lists(table)
    )
    if kind == "impl_record" and expected_version == "2":
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
                if column == definition.get("line_range_column"):
                    bare = value.removeprefix("基线").strip()
                    if (re.match(r"^[Ll][ \t]*[0-9]", bare)
                            and LINE_RANGE_RE.fullmatch(bare) is None):
                        problems.append((
                            CONTENT_CATEGORY,
                            f"{key} 第 {index} 行的 {column} {value!r} 不符合 L起始-L结束 格式，例如 L12-L34",
                        ))
                # R19 第①②条（版本 2）：自由描述列拒绝占位词与不达标的最小信息量。
                if expected_version == "2" and column in _FREE_DESCRIPTION_COLUMNS:
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
        if expected_version != "2":
            continue
        filled = [str(p) for p in paragraphs if str(p).strip()]
        allow_no_content = key in _NARRATIVE_ALLOW_NO_CONTENT.get(kind, set())
        content_paragraphs = [p for p in filled if p.strip() != "暂无"] if allow_no_content else filled
        for paragraph in content_paragraphs:
            _substantive_problems(kind, f"叙述栏 {key}", key, paragraph, problems)
        required = _GATE_REQUIRED_NARRATIVE.get(kind, [])
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
        return _generate_document_v1(kind, table, project_root=project_root)
    return _generate_document_v2(kind, table, project_root=project_root, wf_state=wf_state)


def _render_rows(section_lines: list[str], columns: list[str], rows: list[dict]) -> None:
    section_lines += ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        cells = {**{c: "" for c in columns}, **(row if isinstance(row, dict) else {})}
        section_lines.append("| " + " | ".join(_md_cell(cells[c]) for c in columns) + " |")


def _generate_document_v2(kind: str, table: dict, *, project_root: str = "", wf_state=None) -> str:
    """版本 2 渲染：模板规定的每一节都存在、内容全部来自表栏位、零占位指引句（R16/R18）。"""
    schema = _schema(kind, "2")
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
        lines += _narrative("## 根因证据", "根因证据", "暂无")
        lines += _narrative("## 修复仍存在的不确定性", "修复仍存在的不确定性", "暂无")
        lines += _narrative("## 修复与验收结果", "修复与验收结果", "暂无（由后续阶段按实际结果追加）")
        return "\n".join(lines)

    if kind in {"design_sync", "topic_relations"}:
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
        problems.extend(validate_table(kind, table, _workflow_table_version(project_root, workflow_id)))
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
    problems.extend(validate_table("product_features", table, _workflow_table_version(project_root, workflow_id)))
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
    recorded = table.get(DOC_HASH_KEY)
    if (
        recorded is not None
        and current_block_hash != recorded
        and current_block_hash != expected_hash
    ):
        problems.append((
            CONTENT_CATEGORY,
            "产品总说明的功能清单与工作记录表不一致：文档被直接修改；"
            "请把改动写回工作记录表后重新执行门禁，程序不会悄悄覆盖手改内容",
        ))
        return problems, documents
    if current_block_hash != expected_hash:
        _write_text(overview_full, new_content)
    table[DOC_HASH_KEY] = expected_hash
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
        return _generate_test_result_document_v1(topic, table, tasks_by_id, plan_table)
    return _generate_test_result_document_v2(topic, table, tasks_by_id, plan_table, project_root)


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
    # R11：表启用以表文件是否存在为准（空表也启用表流程），不以内容是否已填为准
    if not has_any_table_file(
        project_root, wf_state.workflow_id, stage, topics + [""]
    ) and "topic_relations" not in kinds:
        return [], []
    problems: list[tuple[str, str]] = []
    documents: list[str] = []
    written_docs: set[str] = set()  # 本轮门禁首次真实生成的正式文档（触发生成方）
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
            kind_problems = validate_table(kind, table, _workflow_table_version(project_root, wf_state.workflow_id))
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
                generate_document(kind, table, project_root=project_root, wf_state=wf_state).encode("utf-8")
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
                content = generate_test_result_document(
                    topic, table, tasks_by_id, plan_table, project_root=project_root
                )
            else:
                content = generate_document(kind, table, project_root=project_root)
            existed_before = os.path.isfile(doc_full)
            _write_text(doc_full, content)
            table[DOC_HASH_KEY] = _file_sha256(doc_full)
            table[GENERATED_DOC_PATH_KEY] = doc_relative
            _atomic_write(os.path.join(project_root, relative), table)
            if kind == "bug_record":
                # 模板要求缺陷记录落在 bug/ 目录（缺陷_<标识>.md + 索引.md），按表内容同步生成
                for bug_rel, bug_content in _bug_defect_documents(table, project_root):
                    _write_text(os.path.join(project_root, bug_rel), bug_content)
                    documents.append(bug_rel)
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


def _bug_defect_documents(table: dict, project_root: str) -> list[tuple[str, str]]:
    """按 bug_record 表生成模板结构的缺陷记录文档与索引条目（bug/ 目录）。"""
    topic_name = str(table.get("验收主题", "")).strip() or "缺陷记录"
    workflow_id = str(table.get("工作流编号", ""))
    file_key = topic_file_key(project_root, topic_name)
    rows = [row for row in table.get("缺陷信息", []) if isinstance(row, dict)]
    lines: list[str] = [
        f"# 【缺陷】{topic_name}",
        "",
        f"- 工作流编号：{workflow_id}",
        "- 复现状态：已复现",
        "- 根因状态：已确认",
        f"- 验收主题：{topic_name}",
        "",
        "## 1. 缺陷现象",
        "",
    ]
    lines += [f"- {row.get('现象', '')}".rstrip() for row in rows]
    lines += ["", "## 2. 真实复现条件", ""]
    lines += [f"- {item}".rstrip() for item in table.get("真实复现条件", []) if str(item).strip()]
    lines += ["", "## 3. 复现步骤", ""]
    lines += [f"- {row.get('复现步骤', '')}".rstrip() for row in rows]
    lines += ["", "## 4. 实际结果", ""]
    lines += [f"- {row.get('实际结果', '')}".rstrip() for row in rows]
    lines += ["", "## 5. 期望结果", ""]
    lines += [f"- {row.get('期望结果', '')}".rstrip() for row in rows]
    lines += ["", "## 6. 根因", ""]
    root_cause_labels = ("根因说明：", "根因位置：", "根因证据：")
    for row in rows:
        lines += [f"**{row.get('缺陷编号', '')}**", ""]
        root_cause = str(row.get("根因", "")).strip()
        segments = re.split(r"(?=根因说明：|根因位置：|根因证据：)", root_cause)
        for segment in segments:
            segment = segment.strip()
            if segment:
                lines.append(f"- {segment}")
        lines.append("")
    lines += ["## 7. 修复仍存在的不确定性", ""]
    uncertainty = [str(x).strip() for x in table.get("修复仍存在的不确定性", []) if str(x).strip()]
    lines += [f"- {item}" for item in uncertainty] or ["暂无"]
    lines += ["", "## 8. 修复与验收结果", ""]
    lines += [f"- {item}".rstrip() for item in table.get("修复与验收结果", []) if str(item).strip()]
    defect_rel = f"bug/缺陷_{file_key}.md"
    documents: list[tuple[str, str]] = [(defect_rel, "\n".join(lines).rstrip() + "\n")]

    index_path = os.path.join(project_root, "bug", "索引.md")
    first_row = rows[0] if rows else {}
    index_row = (
        f"| [{topic_name}](./缺陷_{file_key}.md) "
        f"| {_inline_cell(first_row.get('现象', ''))} "
        f"| {_inline_cell(first_row.get('根因', ''))} | 根因已确认 |"
    )
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as stream:
            index_content = stream.read()
        if f"(./缺陷_{file_key}.md)" not in index_content:
            index_content = index_content.rstrip() + "\n" + index_row + "\n"
    else:
        index_content = (
            "# Bug 索引\n\n"
            "| Bug 记录 | 现象 | 根因 | 状态 |\n|---|---|---|---|\n" + index_row + "\n"
        )
    documents.append(("bug/索引.md", index_content))
    return documents


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
) -> list[str]:
    """按当前表重新生成某主题的正式文档（检测到手改时跳过并报告）。返回生成路径。"""
    relative = table_relative_path(project_root, workflow_id, kind, topic)
    if not table_exists(project_root, relative):
        return []
    table = load_table(os.path.join(project_root, relative))
    if not table_is_filled(table):
        return []
    doc_relative = _expected_document_path(project_root, kind, topic, table)
    doc_full = os.path.join(project_root, doc_relative)
    current_hash = _file_sha256(doc_full) if os.path.isfile(doc_full) else None
    if (current_hash is not None and table.get(DOC_HASH_KEY) is not None
            and current_hash != table.get(DOC_HASH_KEY)):
        return []  # 手改检测已在本环节报告，不重复处理
    content = generate_document(kind, table, project_root=project_root)
    if current_hash is not None and content == _read_document(doc_full):
        return [doc_relative]
    _write_text(doc_full, content)
    table[DOC_HASH_KEY] = _file_sha256(doc_full)
    table[GENERATED_DOC_PATH_KEY] = doc_relative
    _atomic_write(os.path.join(project_root, relative), table)
    return [doc_relative]


def _read_document(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read()
    except OSError:
        return ""


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
