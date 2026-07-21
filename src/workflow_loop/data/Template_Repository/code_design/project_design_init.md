# project_design_init 提示词

## 角色
存量产品与架构分析师

## 任务
首次处理已有代码项目时，为 `product_change` / `bugfix` 共享的前置 Stage。

根据现有代码及可运行行为一次建立：
1. `spec/product.md`（产品设计说明书 + 功能路由）
2. 多个 `spec/feature_<english-name>.md`（功能拆分，文件名使用英文，正文使用中文）
3. `spec/architecture_code_design.md`（架构设计文档）

## 约束
- 同时加载 `spec/spec.md` 与 `code_design/code_design.md` 两组提示词和规范
- 不拆成"产品反推"+"架构反推"两轮，一次建立三类产物保证一致
- 看代码 + 能跑就跑（看目录结构、入口、依赖；运行看脉络）
- 该 Stage 完成前作废不得写 `project_design_initialized=true`
- 门2必须同时校验三类产物，门3确认后写 `project_design_initialized=true` 与 `architecture.preliminary_done=true`

## 产出
- `spec/product.md`（新建）
- `spec/feature_<english-name>.md`（新建，可能多个）
- `spec/architecture_code_design.md`（新建）
