# align.md
向用户提问，明确当前项目属于什么场景。

按以下决策树问用户：

第 1 步：项目状态
  问：'需要制作新的项目吗？'
  - 是 → start --entry new-project
  - 否 → 问：'项目接入 workflow_loop 了吗？'
    - 没接入 → start --entry existing-no-workflow
    - 已接入 → 进入第 2 步

第 2 步：工作类型（仅项目已接入 workflow_loop 时）
  问：'这次要做什么？'
  - 修 bug → start --entry bugfix
  - 改产品设计/加需求 → start --entry product-mod
