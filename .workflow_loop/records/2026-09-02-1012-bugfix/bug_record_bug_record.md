# 【缺陷】计划路径非法时门禁一次说清而不是抛异常

- 工作流编号：2026-09-02-1012-bugfix

## 缺陷信息

| 缺陷编号 | 现象 | 复现步骤 | 实际结果 | 期望结果 | 根因 |
|---|---|---|---|---|---|
| BUG-01 | 实施记录工作记录表的代码修改计划行把工作流过程文档路径填进文件列时，执行代码实施第二道门不输出问题清单，只打印一行“错误：命令执行失败（ValueError: ...）”。同一次检查发现的其它问题不再报出，AI 只能改完这一条再跑一次才能看到剩下的问题。 | 在隔离项目建代码实施环节状态并填好实施记录工作记录表；把代码修改计划第一行的文件列填成 .workflow_loop 下的规范文件路径；调用 rollback.planned_code_paths 取计划路径；再把同一个路径改填到实际代码修改行的文件列，调用 rollback.validate_actual_implementation_changes_report 做对照 | 计划一侧抛出 ValueError，异常文字为“…“文件”列：代码修改计划不能把工作流过程文档当成实施代码：…”，调用栈顶为 src/workflow_loop/rollback.py 第 1450 行；实际改动一侧对同一个非法路径返回 2 条结构化诊断，检查标识为 impl.implementation_record.acceptance_source_invalid 和 impl.implementation_record.path_invalid。两条链路对同一类错误的失败方式不同。 | 计划一侧和实际改动一侧一样返回结构化诊断：每条写明检查标识、位置（表文件、行号、列名）、预期、实际、证据、影响和下一动作，与本次检查发现的其它问题在同一份报告里一次列全。 | 根因说明：解析计划路径的函数已经把每个非法路径构造成完整的结构化诊断对象，但对外入口只取其中的证据字段拼成一个字符串抛出异常，其余字段（检查标识、位置、预期、影响、下一动作）全部丢弃；异常沿调用链向上传播，门禁调用链里的两处调用不捕获，最终由命令层兜底处理打印成一行错误。根因位置：src/workflow_loop/rollback.py 第 1447 至 1451 行的 planned_code_paths，函数体为 changes, diagnostics = _planned_code_changes(...) 后 if diagnostics: raise ValueError(把每条诊断的证据字段换行拼接)；不捕获该异常的调用方是同文件第 1808 行的 validate_prepared 与第 2016 行的 prepare_impl，另有 verification.py 第 822 至 828 行的 _active_registered_paths 在实施记录文档已存在时按设计重新抛出。根因证据：沙盒对同一非法路径分别调用两条链路，计划一侧抛 ValueError 且栈顶为 rollback.py:1450，实际改动一侧返回 2 条结构化诊断；读源码确认 _planned_code_changes 第 1419 至 1434 行已生成带七个字段的 Diagnostic 对象。 |

## 缺陷说明

- 门禁的既定要求是一次列出当前输入下全部可以独立确认的问题，每项带位置、预期、实际、证据、影响和下一动作。计划路径这一条违反了这个要求：它把已经构造好的结构化诊断压成一句异常文字，既丢掉定位信息，也让同一次检查的其它问题无法一起报出。
- 代价是每撞上一次就多花一整轮门禁。上一轮真实发生过：一次门禁报了 3 条结构化问题，改完后再跑才以异常形式冒出计划行的路径问题，第四次执行才通过。
- 本轮只改失败的报告方式，不改判定本身：什么样的路径算非法保持原样。

## 真实复现条件

- 运行环境：macOS 26.4.1，Python 3.13.12（仓库 .venv），workflow-loop 0.3.7 以 editable 方式安装并加载本仓库 src/workflow_loop 真实源码。
- 代码基线：本仓库提交 b89d0d8（fix: 修通退回重走时门禁反复失败的 12 个缺陷），工作区无未提交修改。
- 真实输入：由 project.create_project 建立的隔离临时项目，实施记录工作记录表由 records.create_or_complete_table 生成后按真实栏目填写；非法路径取真实存在的 .workflow_loop/Standardized_Repository/qa/test_plan.md，不是编造路径。
- 复现脚本：/tmp/wf_repro_bug13/repro.py，分对照组和缺陷组两次构建隔离项目，分别调用实际改动一侧和计划一侧的真实函数。
- 另有上一轮 2026-09-02-0752-bugfix 在真实门禁命令中的观察作为佐证：workflow gate impl 第一次报 3 条结构化问题、改完后第二次才以异常形式报出计划行路径问题。

## 根因证据

- 沙盒对照：同一个非法路径写在实际代码修改列时返回 2 条结构化诊断（impl.implementation_record.acceptance_source_invalid、impl.implementation_record.path_invalid）；写在代码修改计划列时抛出 ValueError。
- 调用栈顶为 src/workflow_loop/rollback.py 第 1450 行 raise ValueError(把诊断证据换行拼接)。
- 读源码确认 _planned_code_changes 在第 1419 至 1434 行已经为每个非法路径构造了带 check_id、location、expected、actual、evidence、impact、next_action 七个字段的 Diagnostic 对象，异常只保留其中的 evidence。
- 不捕获该异常的调用方：rollback.py 第 1808 行 validate_prepared、第 2016 行 prepare_impl；verification.py 第 822 至 828 行 _active_registered_paths 在实施记录文档存在时按设计重新抛出。已捕获的对照：verification.py 第 186 行 stage_responsibility_paths、第 2213 行 _topic_owned_paths、rollback.py 第 2674 行 validate_existing_implementation_paths。

## 修复仍存在的不确定性

- planned_code_paths 是多处共用的公开函数，除门禁外还被回退准备和登记快照使用。改成返回诊断后，各调用方是照旧忽略、还是把诊断并入自己的报告，需要在代码计划阶段逐个调用点确认，本阶段不预设结论。

## 修复与验收结果

- 本节由主题验收、最终全量回归和整体验收三个阶段按实际结果由程序追加；缺陷复现阶段不填写任何结论。