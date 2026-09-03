# 【缺陷】登记测试项时入口填不对当场说清而不是测完才失败

- 工作流编号：2026-09-03-0231-bugfix

## 缺陷信息

| 缺陷编号 | 现象 | 复现步骤 | 实际结果 | 期望结果 | 根因 |
|---|---|---|---|---|---|
| BUG-01 | 启用工作记录表的轮次走到测试验证环节，AI 按程序写在表里的填写说明填 test_plan 的“正式目标名称”列。按说明字面填入纯测试标题后，按表登记不报错、执行前的登记校验也回“与工作记录表一致”，测试进程真实通过，工作流仍把该测试项判为 failed，错误是“结构化测试报告无效”。同一行的“测试入口”列已经填了正确的 项目相对路径::测试函数，登记程序不读它，也不提示。 | 在隔离临时项目建立测试验证环节状态并用 records.create_or_complete_table 生成 test_plan 工作记录表；读表内“正式目标名称”的填写说明并按字面填入纯测试标题“验证上传完成”，同一行“测试入口”填正确的 tests/test_upload.py::test_upload；调用 records.validate_table 做表校验；调用 test_execution.prepare_task 按表登记该测试项；调用 test_execution.validate_prepared_tasks 做执行前登记校验；调用 test_execution.run_prepared_tasks 真实执行 pytest；只把“正式目标名称”改成 tests/test_upload.py::test_upload 后重跑一次作单变量对照；另建一个隔离项目，让一个测试项由同文件两个测试函数覆盖，“正式目标名称”按正确形状只填其中一个入口后执行，再改成用顿号连接两个入口后执行 | 单入口场景：records.validate_table 返回 0 项问题；prepare_task 正常返回，登记入口为 ['验证上传完成']；validate_prepared_tasks 回“全部 1 个测试项的登记任务与工作记录表一致”；pytest 进程退出码 0，它自己写出的 junit 报告是 tests="1" failures="0" skipped="0"；工作流判定 failed，错误为“结构化测试报告无效：pytest 报告包含未登记的原始测试入口: tests/test_upload.py::test_upload”。只把该单元格改成 tests/test_upload.py::test_upload、其余一字不动后重跑，判定 passed。多函数场景：“正式目标名称”按正确形状填其中一个入口时判定 failed，错误为“未登记的原始测试入口: tests/test_upload.py::test_upload_overwrites_existing”；改成用顿号连接两个入口后仍判定 failed，登记入口是把整串当成的一个字符串。 | “正式目标名称”的填写说明写明该列必须写成 项目相对路径::报告里的目标名，并写明同一行“测试入口”列不作为登记入口；一个测试项覆盖多个测试函数时，说明写清怎样在该列填多个入口。填写不符合这个形状、或漏填该测试项实际会执行的入口时，workflow test prepare --from-tables 当场拒绝登记，一次列出哪个验收主题的哪个测试项、哪一列、实际值、正确形状和下一步动作。填写正确且测试真实通过时判定 passed。问题不再推迟到测试执行完由报告解析报出。 | 根因说明：表模式把登记入口直接等同于“正式目标名称”单元格的原始字符串，既不校验形状，也只接受一个值，而这个字符串最终要与结构化报告里的每个目标精确一一对应。填写说明只写“测试报告里的正式目标名，用于精确匹配”，没有写出 项目相对路径::目标名 这个必须形状，也没有说明同一行已经存在的“测试入口”列不参与登记，因此按说明字面填纯标题是填表人的合理行为。文档模式对同一件事本来有两项能力：解析测试计划时按 项目相对文件::可定位标识 校验测试入口并要求指向真实测试文件，以及从 Workflow-Test 标识按测试项收集多个入口；表模式两项都没有承接。根因位置：src/workflow_loop/records.py 第 385 行“正式目标名称”填写说明与第 373 行“测试入口”填写说明；src/workflow_loop/test_execution.py 第 264 与 266 行把“正式目标名称”同时当测试名和登记入口，第 281 行 entries = [item.test_entry] if item.test_entry else [test_id] 决定一个测试项只装得下一个入口；src/workflow_loop/test_mapping.py 第 259 行表模式构造测试计划项时同样只读“正式目标名称”；src/workflow_loop/test_execution.py 第 362 至 413 行 _validate_prepared_tasks_from_tables 只比对命令参数数组，不校验入口形状；src/workflow_loop/records.py 第 106 至 146 行 test_plan 表 schema 没有为这两列声明任何格式。根因证据：单变量沙盒对照证明判定只由这一个单元格决定——同一张表、同一条命令、同一个真实通过的测试，填纯标题时 pytest 退出码为 0、报告为 tests="1" failures="0" skipped="0" 而判定 failed，只把该单元格改成 tests/test_upload.py::test_upload 后判定 passed；多函数沙盒证明一格装不下两个入口，按正确形状填一个入口报“未登记的原始测试入口”，用顿号连接两个入口后整串被当成一个入口仍然失败；读源码确认文档模式的对应能力存在而表模式没有实现——src/workflow_loop/test_mapping.py 第 172 至 180 行要求恰好一个 :: 且路径不含空格、第 183 至 215 行要求指向真实测试文件、第 390 至 399 行在解析自动化测试项时调用它，src/workflow_loop/test_execution.py 第 289 行按测试项收集标识返回入口列表，而表模式的 src/workflow_loop/test_mapping.py 第 218 至 268 行两者都没有。 |

## 缺陷说明

- 这条缺陷的代价不是一次报错，而是一个闭环：填表人按说明填，登记通过，测试真的通过，门禁仍判失败；而唯一能过的填法在说明里一个字都没写，只能靠撞上报错再翻源码反推。用户所在的一轮里 13 个测试项全部踩了同一个坑。
- 同一张表里还有一列“测试入口”，说明写的是 tests/文件::测试函数，填对了也被登记程序静默忽略。两列语义重叠，一列真正决定判定、一列只进生成文档，表面上看不出区别。
- 一个测试项由多个测试函数覆盖是产品明确允许的做法，但表模式一格只装得下一个入口，用顿号连接也不被解析。这类测试项在表模式下按任何写法都无法判定通过，因此和填写说明一起在本轮修复。
- 本轮边界：只改登记入口的取值方式、登记时的校验和这两列的填写说明，不改结构化报告的判定标准。报告里的目标必须与登记入口双向一一对应这条要求保持原样。

## 真实复现条件

- 运行环境：macOS 26.4.1，Python 3.13.12（仓库 .venv），workflow-loop 0.3.7 以 editable 方式安装，加载本仓库 src/workflow_loop 真实源码。
- 代码基线：本仓库提交 c73c09d（fix: 计划路径非法时门禁一次说清而不是抛异常），工作区除本轮新建的 .workflow_loop/records/2026-09-03-0231-bugfix/ 与 .workflow_loop/rollback/ 外没有修改。
- 真实输入：由 project.create_project 建立的隔离临时项目；test_plan 工作记录表由 records.create_or_complete_table 生成，填写说明取自程序真实写入的内容；被测代码和测试代码都是可真实运行的 pytest 测试，junit 报告由 pytest 自己写出，不是手工构造的样本。
- 复现脚本：/tmp/wf_entry_repro/repro.py 覆盖单入口填错与单变量对照，/tmp/wf_entry_repro/multi.py 覆盖一个测试项由两个测试函数覆盖的情况。
- 现场佐证：用户先在一个使用 vitest 适配器的真实轮次里遇到同一问题，13 个测试项按纯标题填写后全部被判 failed，报“Vitest 登记入口必须是 <项目相对路径>::<测试标题>”。

## 根因证据

- 单变量对照：同一张表、同一条命令、同一个真实通过的测试，“正式目标名称”填纯标题时判定 failed，改成 tests/test_upload.py::test_upload 后判定 passed，其余单元格一字未动。
- 机器事实：失败那次 pytest 进程退出码为 0，它写出的报告为 tests="1" failures="0" skipped="0"，其中 workflow_loop_nodeid 属性值正是 tests/test_upload.py::test_upload，与登记入口不同的只有形状。
- 多入口证据：一个测试项由 test_upload_writes_content 和 test_upload_overwrites_existing 两个函数覆盖时，按正确形状只填一个入口报“未登记的原始测试入口”；用顿号连接两个入口后，登记入口变成包含顿号的单个字符串，仍然失败。
- 报告侧要求来自 src/workflow_loop/test_report.py：第 305 行要求 vitest 登记入口写成 项目相对路径::测试标题，第 352 行对 pytest 报告中未登记的 nodeid 直接报错，第 357 至 370 行要求报告目标与登记入口双向一一对应。
- 文档模式对照：src/workflow_loop/test_mapping.py 第 172 至 180 行 _entry_parts 要求恰好一个 :: 且路径不含空格，第 183 至 215 行 _validate_plan_entry 另要求指向项目内真实测试文件，第 390 至 399 行在解析自动化测试项时调用它；多入口能力来自 src/workflow_loop/test_execution.py 第 289 行按测试项收集 Workflow-Test 标识返回入口列表。表模式的 src/workflow_loop/test_mapping.py 第 218 至 268 行没有任何对应实现。
- 影响面核对：本仓库 .workflow_loop/records 下 8 个历史轮次的 test_plan 表中，“正式目标名称”的值全部已经是 项目相对路径::标识 形状，因此新增登记校验不会让历史轮次的表立即变成报错。

## 修复仍存在的不确定性

- 没有需要技术穿刺的未知事实。一格里怎样表示多个入口（分隔符或数组）、表版本 1 的旧轮次是否一并校验，都是实施阶段在已知事实上的取舍，不依赖新的技术验证。
- vitest 适配器一侧没有在本仓库实机验证：本仓库没有 Node 工程，本次复现使用 pytest 适配器。vitest 一侧的依据是用户所在项目的真实执行结果，以及 src/workflow_loop/test_report.py 第 298 至 334 行的代码事实——两个适配器要求的入口形状同构，都是 项目相对路径::目标名。

## 修复与验收结果

- 本节由主题验收、最终全量回归和整体验收三个阶段按实际结果由程序追加；缺陷复现阶段不填写任何结论。