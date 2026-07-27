# 修复缺陷经过主题验收和全量回归后关闭测试计划

- 工作流编号：2026-07-20-0637-from_scratch
- 上游验收计划：[修复缺陷经过主题验收和全量回归后关闭验收计划](../acceptance/修复缺陷经过主题验收和全量回归后关闭_plan.md)

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|
| [AC-01：缺陷复现记录与验收主题一一对应](../acceptance/修复缺陷经过主题验收和全量回归后关闭_plan.md#ac-01) | <a id="tc-01"></a>[TC-01 缺陷记录只登记一个验收主题](#tc-01) | 使用真实结构的缺陷记录和缺陷索引运行缺陷复现阶段校验，并检查主题是否进入当前工作流 | 每份缺陷记录只有一个验收主题，验收计划只能复用该主题，缺陷复现原始事实不能被后续结果覆盖 | 保留 `tests/test_stages.py::test_reproduce_stage_requires_current_structured_bug_record_and_index`、缺陷记录和状态文件 |
| [AC-02：主题验收通过后保留待回归状态](../acceptance/修复缺陷经过主题验收和全量回归后关闭_plan.md#ac-02) | <a id="tc-02"></a>[TC-02 主题验收通过后保留待回归状态](#tc-02) | 调用主题验收结果更新逻辑，检查缺陷记录和 `bug/index.md` 的状态及追加内容 | 状态变为“主题验收通过，待全量回归”，并追加实施记录、主题测试结果和主题验收结果链接；原缺陷复现内容保持不变 | 保留 `tests/test_bug_record.py::test_bug_status_updates_append_results_without_rewriting_reproduction` 的测试输出、缺陷记录前后内容和索引内容 |
| [AC-03：只有最终整体验收通过后才能关闭缺陷](../acceptance/修复缺陷经过主题验收和全量回归后关闭_plan.md#ac-03) | <a id="tc-03"></a>[TC-03 回归和整体验收共同决定缺陷关闭](#tc-03) | 分别验证最终全量回归失败、主题验收结果缺失、全部结果通过三种状态 | 回归失败时状态为“回归失败，重新处理中”且不能进入整体验收；只有主题验收、最终全量回归和整体验收都通过后，状态才变为“已修复并验收” | 保留 `tests/test_stages.py::test_final_regression_requires_current_workflow_and_passed_status`、`tests/test_stages.py::test_overall_acceptance_requires_all_topic_acceptance_and_passed_regression` 和 `tests/test_bug_record.py::test_bug_status_updates_append_results_without_rewriting_reproduction` 的测试输出 |

## 2. 针对性回归范围

- 缺陷记录状态追加、原始复现事实保护、`bug/index.md` 状态同步和重复更新幂等性。相关验证位置为 `tests/test_bug_record.py::test_bug_status_update_is_idempotent`。
- 主题执行、最终全量回归和整体验收的前置条件检查。相关验证位置为 `tests/test_stages.py::test_topic_execution_requires_results_for_every_topic` 和 `tests/test_stages.py::test_overall_acceptance_requires_all_topic_acceptance_and_passed_regression`。

## 3. 测试条件要求

- 需要真实结构的 `bug/<缺陷记录>.md`、`bug/index.md`、实施记录、主题测试结果和主题验收结果。
- 需要分别准备主题验收通过但未回归、回归失败、回归通过但主题结果缺失、全部结果通过的状态。
- 本工作流当前是 `from_scratch`，没有正在处理的真实缺陷记录；本阶段测试计划验证的是代码中对 `bugfix` 流程的固定状态约束，正式 bug 复现输入由后续 bugfix 工作流提供。
- 需要项目虚拟环境中的 Python 测试入口 `scripts/test_all.sh`。

## 4. 未决测试条件

- 状态名称、缺陷记录追加位置、最终回归文件路径和整体验收前置条件已经确定，暂无实施后确认项。
- 真实缺陷输入和真实修复代码不属于当前 `from_scratch` 工作流的执行数据，不能用本工作流的产品文档假装完成 bugfix 现场验证。

## 5. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [验收计划](../acceptance/修复缺陷经过主题验收和全量回归后关闭_plan.md) | 本测试计划依据的验收条件 |
| 全局 | [需求交付追踪表](../traceability.md) | 查看完整交付关系和状态 |
| 下游 | [实施索引](../impl/index.md) | 实施阶段完成后承接本测试计划 |
| 下游 | [主题测试结果](./修复缺陷经过主题验收和全量回归后关闭_result.md) | 记录实际测试结果和证据 |
