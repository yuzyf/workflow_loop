# 【主题测试结果】先改代码后准备基线的Git自证出口

- 工作流编号：2026-09-08-1207-product_change
- 验收主题：先改代码后准备基线的Git自证出口
- 自动化测试结果：通过
- 人工验收状态：无需人工验收
- 测试完成时间：2026-09-08T12:40:23+00:00

<a id="1-测试依据"></a>
## 1. 测试依据

- [验收计划](../acceptance/先改代码后准备基线的Git自证出口_验收计划.md)
- [测试计划](./先改代码后准备基线的Git自证出口_测试计划.md)
- [代码计划、实施和结果](../impl/先改代码后准备基线的Git自证出口_实施记录.md)
- [需求交付追踪表](../需求交付追踪表.md)

<a id="2-测试环境和执行说明"></a>
## 2. 测试环境和执行说明

- 真实 pytest 执行（含 git 仓库场景），退出码 0，junitxml 报告齐全。

<a id="3-测试项结果"></a>
## 3. 测试项结果

<a id="tc-01"></a>
<a id="tc-01自证放行与新文件放行"></a>
### TC-01：自证放行与新文件放行

- 对应验收条件：AC-01
- 机器记录编号：RUN-20260908T124020+0000-4b5babbc
- 工作目录：项目根
- 测试入口：["tests/test_git_baseline_exit.py::test_prepare_allows_changed_file_matching_head","tests/test_git_baseline_exit.py::test_prepare_allows_new_file_not_in_snapshot"]
- 执行命令：[".venv/bin/python","-m","pytest","tests/test_git_baseline_exit.py::test_prepare_allows_changed_file_matching_head","tests/test_git_baseline_exit.py::test_prepare_allows_new_file_not_in_snapshot","-q","--basetemp=/tmp/wf-test-tmp/TC-01","-p","workflow_loop.test_report","--junitxml=/Users/yu/business_qt/ai_qt/workflow_loop/.workflow_loop/test_reports/2026-09-08-1207-product_change/先改代码后准备基线的Git自证出口/TC-01.xml"]
- 超时（秒）：600
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-09-08T12:40:20+00:00
- 结束时间：2026-09-08T12:40:21+00:00
- 时长（秒）：0.519
- 退出码：0
- 输出摘要："..                                                                       [100%]\n2 passed in 0.35s\n"
- 输出哈希：b1a06b26972c2140d432c34fda543615763c138b875a7c41cc50eedff85f4e4a
- 输出字节数：98
- 报告适配器：pytest-junitxml
- 报告哈希：02d06c4b794cd331a1d6b869000e0acff7533a722c2c6c6f865573c929014f4c
- 报告字节数：817
- 精确匹配测试入口：["tests/test_git_baseline_exit.py::test_prepare_allows_changed_file_matching_head","tests/test_git_baseline_exit.py::test_prepare_allows_new_file_not_in_snapshot"]
- 实际执行数：2
- 跳过数：0
- 失败数：0
- 错误数：0
- 产品代码哈希：1d1e4fab50f998c99b9961d94baf02f68d22a2c93a24644f5ca077e4b86ca8d3
- 测试代码哈希：087880cfb96b33d0ee592974c006cd1c1c73dcf87fd4a5410efa37af96798893
- 自动化测试结果：通过
- 实际结果：自证放行验证通过：快照等于 HEAD 的文件用 HEAD 字节补副本放行，新文件直接放行（AC-01）
- 证据：机器记录 RUN-20260908T124020+0000-4b5babbc；结构化报告哈希 02d06c4b794cd331a1d6b869000e0acff7533a722c2c6c6f865573c929014f4c

<a id="tc-02"></a>
<a id="tc-02不可自证保持拒绝"></a>
### TC-02：不可自证保持拒绝

- 对应验收条件：AC-02
- 机器记录编号：RUN-20260908T124021+0000-331725e9
- 工作目录：项目根
- 测试入口：["tests/test_git_baseline_exit.py::test_prepare_rejects_unverifiable_change"]
- 执行命令：[".venv/bin/python","-m","pytest","tests/test_git_baseline_exit.py::test_prepare_rejects_unverifiable_change","-q","--basetemp=/tmp/wf-test-tmp/TC-02","-p","workflow_loop.test_report","--junitxml=/Users/yu/business_qt/ai_qt/workflow_loop/.workflow_loop/test_reports/2026-09-08-1207-product_change/先改代码后准备基线的Git自证出口/TC-02.xml"]
- 超时（秒）：600
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-09-08T12:40:21+00:00
- 结束时间：2026-09-08T12:40:22+00:00
- 时长（秒）：0.381
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.20s\n"
- 输出哈希：93c97c10af4fc8b54296201243c032c5e8295479ca6b4adc06019033d6f9e282
- 输出字节数：98
- 报告适配器：pytest-junitxml
- 报告哈希：65283a0192b36067cc8957abf0772ebe5e2760916d21f04e980a74649ac773b3
- 报告字节数：527
- 精确匹配测试入口：["tests/test_git_baseline_exit.py::test_prepare_rejects_unverifiable_change"]
- 实际执行数：1
- 跳过数：0
- 失败数：0
- 错误数：0
- 产品代码哈希：1d1e4fab50f998c99b9961d94baf02f68d22a2c93a24644f5ca077e4b86ca8d3
- 测试代码哈希：087880cfb96b33d0ee592974c006cd1c1c73dcf87fd4a5410efa37af96798893
- 自动化测试结果：通过
- 实际结果：不可自证拒绝验证通过：快照不等于 HEAD 时按文件列出原因拒绝（AC-02）；本轮进场快照为中间态时该拒绝被真实触发
- 证据：机器记录 RUN-20260908T124021+0000-331725e9；结构化报告哈希 65283a0192b36067cc8957abf0772ebe5e2760916d21f04e980a74649ac773b3

<a id="tc-03"></a>
<a id="tc-03主题合并打破死循环"></a>
### TC-03：主题合并打破死循环

- 对应验收条件：AC-03
- 机器记录编号：RUN-20260908T124022+0000-60f9b079
- 工作目录：项目根
- 测试入口：["tests/test_git_baseline_exit.py::test_current_workflow_topics_merges_table"]
- 执行命令：[".venv/bin/python","-m","pytest","tests/test_git_baseline_exit.py::test_current_workflow_topics_merges_table","-q","--basetemp=/tmp/wf-test-tmp/TC-03","-p","workflow_loop.test_report","--junitxml=/Users/yu/business_qt/ai_qt/workflow_loop/.workflow_loop/test_reports/2026-09-08-1207-product_change/先改代码后准备基线的Git自证出口/TC-03.xml"]
- 超时（秒）：600
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-09-08T12:40:22+00:00
- 结束时间：2026-09-08T12:40:23+00:00
- 时长（秒）：0.271
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.08s\n"
- 输出哈希：99a24796443a1d07f66a424f8116a06a2079063af758e7d3c87801c191ad2ecd
- 输出字节数：98
- 报告适配器：pytest-junitxml
- 报告哈希：91e40c1dee446f9c7e72ed2c4d84e8ba21ad6e54337fdf290f69b85a648bac10
- 报告字节数：529
- 精确匹配测试入口：["tests/test_git_baseline_exit.py::test_current_workflow_topics_merges_table"]
- 实际执行数：1
- 跳过数：0
- 失败数：0
- 错误数：0
- 产品代码哈希：1d1e4fab50f998c99b9961d94baf02f68d22a2c93a24644f5ca077e4b86ca8d3
- 测试代码哈希：087880cfb96b33d0ee592974c006cd1c1c73dcf87fd4a5410efa37af96798893
- 自动化测试结果：通过
- 实际结果：主题合并验证通过：state 与 topic_relations 表主题合并去重（AC-03）；本轮中途加第三主题即真实应用
- 证据：机器记录 RUN-20260908T124022+0000-60f9b079；结构化报告哈希 91e40c1dee446f9c7e72ed2c4d84e8ba21ad6e54337fdf290f69b85a648bac10

<a id="4-人工验收交接"></a>
## 4. 人工验收交接

- 本主题全部验收条件均为自动化测试，机器记录已完整覆盖判定依据，无需要用户人工判断的剩余部分。

<a id="5-未通过或阻塞"></a>
## 5. 未通过或阻塞

- 暂无

<a id="结果说明"></a>
### 结果说明

- Git 自证与主题合并全部验证通过；两条修复都在本轮流程中被真实触发过。

<a id="6-上下游文档"></a>
## 6. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [验收计划](../acceptance/先改代码后准备基线的Git自证出口_验收计划.md) | 说明什么算完成 |
| 上游 | [测试计划](./先改代码后准备基线的Git自证出口_测试计划.md) | 说明本次覆盖哪些测试项 |
| 上游 | [实施记录](../impl/先改代码后准备基线的Git自证出口_实施记录.md) | 说明本次代码怎样实现 |
| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整链路 |
| 下游 | [先改代码后准备基线的Git自证出口验收结果](../acceptance/先改代码后准备基线的Git自证出口_验收结果.md) | 混合测试在这里接收人工确认 |
