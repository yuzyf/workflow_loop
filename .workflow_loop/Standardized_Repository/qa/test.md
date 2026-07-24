# test 规范

## 命名
- Stage 名：`test`
- 产物：`qa/<topic>_result.md` + 更新 `qa/index.md`

## 强制规则
- 按照 `qa/<topic>_plan.md` 执行全部必要测试
- 逐项记录 pass / fail / blocked 及命令、日志、截图或人工测试证据
- 结果绑定当前代码/实施记录哈希与测试计划哈希
- 门2要求所有必测项通过且无未解决 fail/blocked
- 失败必须回到 `topic_execution` 中修改受影响主题，修改后该主题旧测试与验收状态失效并重新测试
- blocked 不得按通过处理
- 强制 Stage，不提供 `--skip`

## 禁止
- 写测试计划冒充测试执行
- 只写"测试通过"无逐项证据
- 修代码后沿用旧测试结果
- 跳过测试
- impl 后直接进入 `update_code_design`
