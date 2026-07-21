# project_design_init 规范

## 命名
- Stage 名：`project_design_init`
- 产物：`spec/product.md` + `spec/feature_<english-name>.md`（多个）+ `spec/architecture_code_design.md`

## 强制规则
- 仅 `product_change` / `bugfix` 在 `project_design_initialized=false` 时执行
- 一次建立三类产物，不拆成"产品反推"+"架构反推"两轮
- 同时加载 spec 与 code_design 两组提示词和规范
- 门2同时校验三类产物
- 门3确认后写 `project_design_initialized=true` 与 `architecture.preliminary_done=true`
- 完成前作废不得写 true

## 禁止
- 只生成 `architecture_code_design.md`
- 用旧文档存在冒充本次初始化完成
- `from_scratch` 走这个 stage（from_scratch 走 `spec` + `code_design` 两步）
