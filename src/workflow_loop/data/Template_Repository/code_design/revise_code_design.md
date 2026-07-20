# revise_code_design 提示词

## 角色
架构文档修订者

## 任务
在 `product_change` 路径上、`spec`（产品设计与功能拆分）之后的设计期改架构 Stage。

按变更后的产品设计修改 `spec/architecture_code_design.md`：
- 反映产品变更对架构的影响
- 标注新增/修改/删除的模块
- 更新模块划分、数据流、关键设计决策
- 记录已知技术债的变更

## 约束
- 这是设计期改架构，不是末段详细收尾。末段 `update_code_design` 在测试与最终验收后才走
- 文件已存在（来自 `project_design_init` 或上一轮 `revise_code_design`），本次是修改不是新建
- 改完后通过门2（`gate revise_code_design`）校验文件有变化，门3用户确认后置 `architecture.preliminary_done=true`

## 产出
- `spec/architecture_code_design.md`（更新，不是新建）
