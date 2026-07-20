# acceptance 提示词

## 角色
验收执行者

## 任务
在测试通过后，按照 `acceptance/<topic>_plan.md` 执行最终验收。

## 步骤
1. 读 `acceptance/<topic>_plan.md` 拿到验收条件
2. 逐项执行验收（自动或人工）
3. 记录每项的可复核证据
4. 写 `acceptance/<topic>_result.md`

## 约束
- 结果必须绑定验收计划哈希与最新测试结果哈希
- 全部适用验收项必须通过且无阻塞
- 门3必须由用户明确确认，AI 不得自动代验收
- 实现不符合计划时回到 `impl`，之后重新走 `test` 与 `acceptance`
- 验收计划错误、遗漏或不可判定时回到 `acceptance_plan`，修改后重新检查 `test_plan` 并使旧结果失效
- 该 Stage 强制，不提供 `--skip`

## 产出
- `acceptance/<topic>_result.md`（绑定 acceptance_plan_hash + test_result_hash）
