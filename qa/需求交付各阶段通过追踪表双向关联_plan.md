# 需求交付各阶段通过追踪表双向关联测试计划

- 工作流编号：2026-07-20-0637-from_scratch
- 上游验收计划：[需求交付各阶段通过追踪表双向关联验收计划](../acceptance/需求交付各阶段通过追踪表双向关联_plan.md)

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|
| [AC-01：每条验收条件都有完整的后续追踪位置](../acceptance/需求交付各阶段通过追踪表双向关联_plan.md#ac-01) | <a id="tc-01"></a>[TC-01 逐条更新验收条件追踪关系](#tc-01) | 生成测试计划后执行追踪表更新，检查每条验收条件对应的测试计划、测试项、实施、结果和代码设计列 | 每条验收条件单独占一行，测试项列能跳转到具体测试项，其他阶段列保留正确初始状态或后续结果位置 | 保留 `traceability.md` 当前工作流章节、更新前后内容和测试命令输出 |
| [AC-02：验收计划可以直接打开上下游文档](../acceptance/需求交付各阶段通过追踪表双向关联_plan.md#ac-02) | <a id="tc-02"></a>[TC-02 检查上下游链接可导航](#tc-02) | 从验收计划、测试计划和追踪表逐个打开上游、下游和全局追踪链接 | 验收计划可以打开产品设计或缺陷记录、`traceability.md` 和对应测试计划；测试计划可以打开验收计划、实施计划和主题测试结果 | 保留文档链接审查记录和链接目标文件列表 |
| [AC-03：不同工作流的追踪记录互不覆盖](../acceptance/需求交付各阶段通过追踪表双向关联_plan.md#ac-03) | <a id="tc-03"></a>[TC-03 保留历史工作流并保持更新幂等](#tc-03) | 使用包含旧工作流和当前工作流的追踪表，重复执行当前阶段更新，再比较两次结果 | 旧工作流章节不变，当前工作流只更新一次，重复执行不会新增重复行或覆盖旧记录 | 保留 `tests/test_traceability.py::test_traceability_updates_only_current_workflow_and_is_idempotent` 的测试输出和追踪表差异 |

## 2. 针对性回归范围

- 追踪表解析、当前工作流定位、九列表格更新和阶段列写入。相关验证位置为 `tests/test_traceability.py::test_traceability_updates_only_current_workflow_and_is_idempotent` 和 `tests/test_traceability.py::test_traceability_updates_each_downstream_column`。
- 验收计划哈希只绑定主题验收计划，不应因追踪表后续更新而变化。相关验证位置为 `tests/test_traceability.py::test_traceability_updates_do_not_change_acceptance_plan_hash`。

## 3. 测试条件要求

- 需要同时准备一个旧工作流章节和当前工作流章节，才能检查历史是否保留。
- 需要当前工作流的验收计划、测试计划和 `traceability.md`。
- 需要项目虚拟环境中的 Python 测试入口 `scripts/test_all.sh`。
- 链接检查需要在项目根目录按 Markdown 相对路径检查，不把 `.workflow_loop/Template_Repository/` 当成实际产物目录。

## 4. 未决测试条件

- 追踪表字段、当前工作流编号、测试项链接格式和局部上下游路径已经确定，暂无实施后确认项。
- 实施计划、主题测试结果和最终代码设计文件尚未生成，当前只检查它们的稳定链接位置，不填写实际结果。

## 5. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [验收计划](../acceptance/需求交付各阶段通过追踪表双向关联_plan.md) | 本测试计划依据的验收条件 |
| 全局 | [需求交付追踪表](../traceability.md) | 查看所有工作流和阶段状态 |
| 下游 | [实施索引](../impl/index.md) | 实施阶段完成后承接本测试计划 |
| 下游 | [主题测试结果](./需求交付各阶段通过追踪表双向关联_result.md) | 记录实际测试结果和证据 |
