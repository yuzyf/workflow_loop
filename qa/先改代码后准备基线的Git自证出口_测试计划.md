# 先改代码后准备基线的Git自证出口测试计划

- 工作流编号：2026-09-08-1207-product_change
- 上游验收计划：[先改代码后准备基线的Git自证出口验收计划](../acceptance/先改代码后准备基线的Git自证出口_验收计划.md)

<a id="1-验收条件覆盖"></a>
## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 产品入口 | 代码入口 | 测试入口 | 准备数据 | 执行动作 | 观察位置 | 预期结果 | 不通过表现 | 证据要求 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [AC-01：已修改文件可用Git自证原内容](../acceptance/先改代码后准备基线的Git自证出口_验收计划.md#ac-01) | <a id="tc-01"></a>[TC-01 自证放行与新文件放行](#tc-01) | 无 | 自动化测试 | workflow gate impl --prepare-code | `src/workflow_loop/rollback.py::prepare_impl` | `tests/test_git_baseline_exit.py::test_prepare_allows_changed_file_matching_head` | git 仓库；进场快照记录文件等于 HEAD 版本；进场后修改该文件并新建另一文件 | 执行首次准备 | 准备结果与清单 | 快照=HEAD 的文件用 HEAD 字节补副本放行；新文件直接放行；manifest 生成 | 可以自证却拒绝；或新文件阻塞 | pytest junitxml 报告与退出码 |
| [AC-02：无法自证时保持原有拒绝](../acceptance/先改代码后准备基线的Git自证出口_验收计划.md#ac-02) | <a id="tc-02"></a>[TC-02 不可自证保持拒绝](#tc-02) | 无 | 自动化测试 | workflow gate impl --prepare-code | `src/workflow_loop/rollback.py::prepare_impl` | `tests/test_git_baseline_exit.py::test_prepare_rejects_unverifiable_change` | 进场快照哈希不等于 HEAD 版本（无法证明进场内容） | 执行首次准备 | 异常消息 | 按文件列出不能用 Git 证明进场时内容的原因并拒绝 | 无法自证却放行 | pytest junitxml 报告与退出码 |
| [AC-03：采集链路随之打通](../acceptance/先改代码后准备基线的Git自证出口_验收计划.md#ac-03) | <a id="tc-03"></a>[TC-03 主题合并打破死循环](#tc-03) | 无 | 自动化测试 | workflow gate acceptance_plan --confirmed | `src/workflow_loop/topic.py::current_workflow_topics` | `tests/test_git_baseline_exit.py::test_current_workflow_topics_merges_table` | state.topics 有旧主题；topic_relations 表含新主题 | 读取当前主题 | 返回清单 | state 与表主题合并去重，新主题可被读到 | 只返回 state.topics 漏新主题 | pytest junitxml 报告与退出码 |

<a id="2-针对性回归范围"></a>
## 2. 针对性回归范围

- tests/test_rollback.py 回退流程回归（1 处断言随新报错文案等价更新）。

<a id="3-测试条件要求"></a>
## 3. 测试条件要求

- 可写临时目录与 git 命令可用。

<a id="4-未决测试条件"></a>
## 4. 未决测试条件

- 暂无

<a id="5-上下游文档"></a>
## 5. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [先改代码后准备基线的Git自证出口验收计划](../acceptance/先改代码后准备基线的Git自证出口_验收计划.md) | 本测试计划依据的验收条件 |
| 上游 | [实施记录](../impl/先改代码后准备基线的Git自证出口_实施记录.md) | 测试入口和观察位置来自已确认实施与真实代码 |
| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整交付关系和状态 |
| 下游 | [先改代码后准备基线的Git自证出口测试结果](./先改代码后准备基线的Git自证出口_测试结果.md) | 记录正式执行的结构化报告事实 |
