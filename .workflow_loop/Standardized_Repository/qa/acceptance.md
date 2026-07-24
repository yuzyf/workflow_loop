# acceptance 规范

## 命名
- Stage 名：`acceptance`
- 产物：`acceptance/<topic>_result.md`

## 强制规则
- 在某个验收主题的测试通过后，按照 `acceptance/<topic>_plan.md` 执行该主题验收
- 结果绑定验收计划哈希与最新测试结果哈希
- 逐项给出可复核证据
- 门2要求全部适用验收项通过且无阻塞
- 门3必须由用户明确确认，AI 不得自动代验收
- 实现不符合计划时，回到 `topic_execution` 中修正受影响主题，再重做该主题的测试与验收
- 验收计划错误、遗漏或不可判定时回到 `acceptance_plan`，修改后重新检查 `test_plan` 并使旧结果失效
- 强制 Stage，不提供 `--skip`

## 禁止
- AI 自动替用户验收
- 测试未通过就验收
- 验收失败只改结果文件
- 修改验收标准后沿用旧测试或验收结果
- 跳过主题验收
