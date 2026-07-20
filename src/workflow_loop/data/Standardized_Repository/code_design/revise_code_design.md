# revise_code_design 规范

## 命名
- Stage 名：`revise_code_design`
- 产物：`spec/architecture_code_design.md`（更新，不是新建）

## 强制规则
- 必须在 `product_change` 路径的 `spec` 之后、`plan` 之前
- 文件已存在（来自 `project_design_init` 或上一轮），本次是修改
- 门2校验文件有变化（内容哈希前后比对）
- 门3确认后置 `architecture.preliminary_done=true`
- 与末段 `update_code_design`（详细落地）名称分离，避免同一 Run 内 stage 名冲突

## 禁止
- 与 `update_code_design` 共用同一 stage 名当主键
- 改设计却不改架构图
- 在 `spec` 之前或 `plan` 之后跑这个 stage
