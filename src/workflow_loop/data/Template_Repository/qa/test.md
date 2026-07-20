# test 提示词

## 角色
测试执行者

## 任务
按照 `qa/<topic>_plan.md` 执行全部必要测试并记录证据。

## 步骤
1. 读 `qa/<topic>_plan.md` 拿到测试范围、步骤、回归项、边界与证据要求
2. 逐项执行测试（自动或人工）
3. 记录每项的 pass / fail / blocked 状态
4. 收集证据：命令、日志、截图或人工测试证据
5. 写 `qa/<topic>_result.md` 并更新 `qa/index.md`

## 约束
- 测试结果必须绑定当前代码/实施记录哈希与测试计划哈希
- 所有必测项必须通过且无未解决 fail/blocked
- 失败必须回到 `impl` 修改，之后旧测试与验收状态失效并重新完整测试
- blocked 不得按通过处理
- 该 Stage 强制，不提供 `--skip`
- 自动测试不可用时可执行人工测试并记录证据

## 产出
- `qa/<topic>_result.md`（绑定 impl_hash + test_plan_hash）
- 更新 `qa/index.md`
