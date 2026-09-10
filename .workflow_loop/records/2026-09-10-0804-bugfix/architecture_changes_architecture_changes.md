# 【工作记录】架构正文变更

- 工作流编号：2026-09-10-0804-bugfix

<a id="正文变更"></a>
## 正文变更

| 章节 | 原文 | 新文 | 依据 |
|---|---|---|---|
| 6.10 【功能】编写并执行测试（`qa` 测试验证） | 执行前删除旧报告，按主题和测试依赖运行后读取新报告，从具体用例重算计数，并要求实际目标集合与登记集合完全相等；程序根据当前机器记录生成或回填测试结果文档，纯人工主题只核对测试计划和人工交接状态 | 执行前删除旧报告，按主题和测试依赖运行后读取新报告，从具体用例重算计数，并要求实际目标集合与登记集合完全相等；程序根据当前机器记录生成或回填测试结果文档，混合主题汇总只统计自动化项且第 3 节人工项渲染为测试方式人工验收说明（不写自动化测试结果未执行），自动化项编号集合由 test_mapping.automated_test_ids_in_plan 单一数据源提供给生成器与校验器共用，纯人工主题只核对测试计划和人工交接状态 | src/workflow_loop/test_mapping.py::automated_test_ids_in_plan（新增单一数据源）；src/workflow_loop/records.py::_generate_test_result_document_v2（汇总与第 3 节渲染）；src/workflow_loop/artifact_validation.py::_validate_topic_test_execution_result（第 3 节两组检查）；验证位置 tests/test_mixed_topic_test_result.py 的四个测试函数 |