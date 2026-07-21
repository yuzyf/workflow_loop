# Workflow Loop — 代码架构设计

## 1. 文档说明

### 1.1 文档目的

本文说明 Workflow Loop 的代码怎样落实当前已经确认的产品设计，主要给维护项目的人阅读。

维护者可以从本文看清：产品设计文档生成经过哪些代码环节；命令、阶段规则、状态文件、提示词和门禁怎样协作；关键判断和文件写入发生在哪里；哪些行为已经有测试或运行证据；哪些产品要求目前只靠提示词约束，还没有程序校验。

本文是当前 `code_design`（初步代码架构）阶段的产物。代码已经存在，因此文中使用真实文件和真实函数名称；但本阶段还没有经过用户最终确认，也不是测试和验收完成后的最终架构版本。

### 1.2 设计依据

当前产品设计把“生成产品设计文档”定义为一个完整功能：AI 和用户先形成共同理解，再生成或修改产品总说明和功能文档；从零设计、修改已有产品、根据已有代码初始化产品设计、修 bug 前初始化产品设计使用同一套文档结构，但进入条件和处理方式不同。

- [产品总说明](./product.md)
- [【功能】生成产品设计文档](./feature_product_design_document_generation.md)
- [项目设计说明](../DESIGN.md)
- [领域词汇与已确认决定](../CONTEXT.md)

### 1.3 事实状态

| 结论 | 证据状态 | 依据 |
|---|---|---|
| 命令入口、阶段路径、三道门禁和状态写入按本文所述工作 | 测试确认、代码确认 | 2026-07-21 运行完整测试，52 项通过；已阅读 `cli.py`、`path_composer.py`、`state.py` 和阶段实现 |
| 当前项目处于 `code_design` 阶段，产品设计阶段已经完成 | 运行确认 | 2026-07-21 实际执行 `workflow status` |
| `workflow discuss` 已加载新的代码架构模板和规范 | 运行确认 | 2026-07-21 在当前项目实际执行 `workflow discuss` |
| 新项目安装后会得到新的四份代码设计提示词 | 运行确认、测试确认 | 在临时目录实际执行本地 `workflow install-project`；安装和提示词内容测试通过 |
| AI 是否真的完成代码调查、是否编造产品内容 | 未由程序确认 | 当前由提示词、用户审查和门禁操作约束，程序没有语义检查能力 |

## 2. 产品概览

Workflow Loop 用命令和状态文件管理 AI 驱动的软件开发过程。用户不直接填写状态文件，而是提出需求；AI 根据 `AGENTS.md` 调用 `workflow` 命令，并按照每条命令输出的“下一步”继续。

当前产品文档只正式定义了一个产品功能：**生成产品设计文档**。该功能包含四种场景：

1. 从零生成产品设计文档。
2. 更新已有产品设计文档。
3. 根据已有代码建立产品设计文档。
4. 修 bug 前初始化产品设计。

代码仓库还实现了穿刺、计划、实施、测试、验收和代码设计更新等后续阶段。这些代码构成完整 Workflow Loop，但当前产品文档没有把它们分别定义为产品功能。本文仍会说明这些共享架构代码，未建立产品映射的部分在第 8 章明确列出。

影响代码的主要产品规则是：

- 用户确认共同理解后，AI 才能生成或修改正式产品文档。
- 从零设计、修改产品、已有代码初始化和修 bug 使用不同进入条件。
- 已有代码初始化时必须查看代码和测试，具备安全条件时实际运行。
- 产品设计文档必须包含 `spec/product.md` 和至少一个英文文件名的 `spec/feature_*.md`。
- 修 bug 时，项目设计尚未初始化才先建立产品设计；需要改变产品行为时应改走 `product_change`（修改产品）。

## 3. 产品设计如何决定代码架构

| 已确认的产品要求 | 对代码提出的具体要求 | 承担该要求的代码层或关键节点 | 关联功能 |
|---|---|---|---|
| AI 必须根据项目现状选择从零设计、修改产品或修 bug | 命令必须接收工作意图，并按意图和项目初始化状态生成不同阶段路径 | 命令编排层的 `cmd_start()`；工作流规则层的 `build_stage_path()` | 生成产品设计文档的四个场景 |
| 用户确认共同理解后才能写正式文档 | 每个阶段必须先记录讨论完成，再允许产物校验和用户确认 | `cmd_gate()` 和 `GateState` 三道门禁 | 所有场景 |
| AI 需要得到产品模板、讨论规范和全局写作规则 | 当前阶段必须加载完整提示词、规范、角色和产出要求 | `cmd_discuss()`、`load_doc_content()`、`StageStrategy` 文档路径方法 | 所有场景 |
| 从零设计和修改已有产品都要生成产品总说明与功能文档 | 产品设计阶段必须声明产物，并检查 `product.md` 和至少一个 `feature_*.md` 存在 | `SpecStage.artifact_paths()`、`SpecStage.code_validate()` | 从零生成、更新已有产品 |
| 已有代码初始化要同时建立产品文档和代码架构文档 | 初始化阶段必须同时加载产品与代码设计规则，并校验三类文件 | `ProjectDesignInitStage.additional_doc_paths()`、`ProjectDesignInitStage.code_validate()` | 根据已有代码建立文档、修 bug 前初始化 |
| 修 bug 时只在项目设计未初始化时先生成产品文档 | 项目必须保存跨工作流的初始化状态，路径生成时据此决定是否前置初始化阶段 | `ProjectState.project_design_initialized`、`build_stage_path()` | 修 bug 前初始化 |
| 从零重做不能沿用旧设计产物 | 开始时发现旧产物必须先获得清场确认，确认后删除约定目录并重置初始化状态 | `detect_clean_artifacts()`、`clean_artifacts()`、`cmd_start()` | 从零生成 |
| 后续验证只对当前代码和计划有效 | 上游实施、测试计划或验收计划改变时，已通过的下游门禁必须失效 | `VerificationState`、`check_invalidation()` | 当前产品文档未单独定义；属于全项目约束 |
| 每条命令都要告诉 AI 下一步做什么 | 所有改变流程的命令必须在输出末尾给出下一条操作 | `print_next_step()` 和各 `cmd_*()` 命令 | 所有场景及后续阶段 |

## 4. 代码架构分层

### 4.1 整体架构图

下图只表示代码职责和依赖方向。箭头表示上层代码会调用或读取下层代码，不表示某个产品场景的执行顺序。

```mermaid
flowchart TB
    L1["命令与 AI 协作层<br/>承接用户提出需求、AI 调命令和 stdout 下一步<br/>src/workflow_loop/cli.py"]
    L2["工作流规则层<br/>决定阶段路径、每个阶段的产物、提示词和校验<br/>path_composer.py / stages/ / role_doc.py"]
    L3["状态与一致性层<br/>保存当前 Run、项目级初始化状态、验证哈希和审计记录<br/>state.py / project.py / verification.py / journal.py"]
    L4["提示词与安装资源层<br/>保存模板、规范和安装到目标项目的运行骨架<br/>data/ / installer.py / install.sh / pyproject.toml"]

    L1 --> L2
    L1 --> L3
    L1 --> L4
    L2 --> L3
    L4 --> L3
```

### 4.2 命令与 AI 协作层

- **承接的产品内容**：用户通过 AI 使用产品；命令输出驱动 AI 继续；用户确认后工作流才推进。
- **代码职责**：解析命令参数，定位项目，调用工作流规则和状态模块，打印当前结果与下一步。
- **代码位置**：[src/workflow_loop/cli.py](../src/workflow_loop/cli.py)。
- **主要符号**：
  - `main()`：命令行总入口，中文职责是解析 `start`、`discuss`、`gate`、`status`、`done`、`abort` 和 `install-project`。
  - `cmd_start()`：启动或检查工作流。
  - `cmd_discuss()`：完整打印当前阶段的角色、全局写作规范、模板、流程规范和产出要求。
  - `cmd_gate()`：执行讨论完成、代码校验、用户确认三道门禁，并推进阶段。
  - `print_next_step()`：在命令输出末尾打印下一条操作。
- **对外约定**：调用方传入命令行参数；成功时得到当前状态和下一步；非法阶段、门禁顺序错误或项目未安装时打印明确错误并退出。
- **依赖关系**：调用工作流规则层决定当前阶段；调用状态与一致性层读写状态；读取提示词与安装资源层中的 Markdown 文件。
- **验证位置**：[tests/test_commands.py](../tests/test_commands.py)。

### 4.3 工作流规则层

- **承接的产品内容**：不同场景走不同流程；每个阶段知道自己需要什么提示词、产生什么文件、怎样检查产物。
- **代码职责**：组合阶段路径；为每个阶段提供名称、提示词路径、规范路径、产物路径、校验规则和推进钩子。
- **代码位置**：
  - [src/workflow_loop/path_composer.py](../src/workflow_loop/path_composer.py)：`build_stage_path()`，即根据工作意图和项目初始化状态拼出阶段路径。
  - [src/workflow_loop/stages/base.py](../src/workflow_loop/stages/base.py)：`StageStrategy`，即所有阶段共同遵守的代码接口。
  - [src/workflow_loop/stages/stages.py](../src/workflow_loop/stages/stages.py)：`SpecStage`、`ProjectDesignInitStage` 等具体阶段。
  - [src/workflow_loop/role_doc.py](../src/workflow_loop/role_doc.py)：`ROLE_DOC_MAP`，即阶段角色和中文职责说明。
- **对外约定**：`build_stage_path()` 接收 `from_scratch`、`product_change` 或 `bugfix`，返回有顺序的阶段对象；未知意图直接抛出错误。每个阶段对象提供统一方法供 CLI 调用。
- **关键逻辑**：`product_change` 和 `bugfix` 只有在 `project_design_initialized=false` 时前置 `ProjectDesignInitStage`；`from_scratch` 固定先 `SpecStage`，再 `CodeDesignStage`。
- **验证位置**：[tests/test_path_composer.py](../tests/test_path_composer.py)、[tests/test_stages.py](../tests/test_stages.py)。

### 4.4 状态与一致性层

- **承接的产品内容**：工作流不能跳过门禁；项目初始化状态跨多次工作流保留；上游内容改变后旧测试和验收不能继续有效。
- **代码职责**：把当前状态写入 JSON；把历史动作追加到 JSONL；计算上游内容哈希；发现变化时清零下游门禁。
- **代码位置**：
  - [src/workflow_loop/state.py](../src/workflow_loop/state.py)：`WorkflowState` 是单次工作流快照，`GateState` 是三道门禁状态，`save_state()` 和 `load_state()` 负责 `.workflow_loop/state.json`。
  - [src/workflow_loop/project.py](../src/workflow_loop/project.py)：`ProjectState` 是跨工作流项目状态，`project_design_initialized` 表示项目设计是否已经初始化。
  - [src/workflow_loop/verification.py](../src/workflow_loop/verification.py)：`check_invalidation()` 检查实施、测试计划和验收计划是否变化。
  - [src/workflow_loop/journal.py](../src/workflow_loop/journal.py)：`append_entry()` 向 `.workflow_loop/journal.jsonl` 追加历史记录。
- **对外约定**：状态模块接收项目根目录和数据对象；成功后文件落盘。读取不到状态时返回 `None`，由命令层决定提示用户启动或安装。
- **验证位置**：[tests/test_state.py](../tests/test_state.py)、[tests/test_project.py](../tests/test_project.py)、[tests/test_verification.py](../tests/test_verification.py)。

### 4.5 提示词与安装资源层

- **承接的产品内容**：所有项目获得同一套产品设计模板、代码设计模板、阶段规范和全局写作规则。
- **代码职责**：保存随 Python 包发布的 Markdown 资源；安装时复制到目标项目；写入最小 `AGENTS.md` 契约和项目级状态。
- **代码位置**：
  - [src/workflow_loop/data/Template_Repository](../src/workflow_loop/data/Template_Repository)：最终文档模板和阶段任务提示。
  - [src/workflow_loop/data/Standardized_Repository](../src/workflow_loop/data/Standardized_Repository)：讨论、调查、生成和写作规范。
  - [src/workflow_loop/installer.py](../src/workflow_loop/installer.py)：`install_project()` 复制资源并创建项目运行骨架。
  - [install.sh](../install.sh)：用户确认项目目录后，检查全局 `workflow` 命令并调用 `workflow install-project`。
  - [pyproject.toml](../pyproject.toml)：声明 `workflow = workflow_loop.cli:main` 命令入口，并把 `data/**/*` 打包。
- **对外约定**：首次安装会覆盖目标项目的 `AGENTS.md`，创建 `.workflow_loop/Template_Repository`、`.workflow_loop/Standardized_Repository` 和 `.workflow_loop/project.json`；同版本重复安装不修改文件。
- **验证位置**：[tests/test_installer.py](../tests/test_installer.py)。

## 5. 架构关键节点

### 5.1 工作意图与阶段路径生成

- **为什么关键**：它决定用户进入产品设计、已有项目初始化还是修 bug；路径错误会让整个后续工作流走错。
- **对应产品内容**：四种产品设计文档生成场景，以及修 bug 时是否需要先初始化产品设计。
- **代码位置**：`src/workflow_loop/cli.py` 中的 `cmd_start()`；`src/workflow_loop/path_composer.py` 中的 `build_stage_path()`。
- **上游**：AI 调用 `workflow start --intent <意图>`。
- **主要处理**：检查安装和活跃工作流；从零设计时检查是否需要清场；读取项目初始化状态；生成阶段对象；初始化每个阶段的门禁状态。
- **下游**：调用 `save_state()` 写入 `.workflow_loop/state.json`，调用 `append_entry()` 记录启动和路径，最后提示执行 `workflow discuss`。
- **状态和数据**：写入 `workflow_id`、`intent`、`stage_path`、`current_stage`、每个阶段的 `GateState`；从零设计同时把 `project_design_initialized` 重置为 `false`。
- **失败结果**：项目未安装、已有活跃工作流或意图非法时停止；发现旧产物但没有清场确认时不删除、不启动。
- **验证位置**：`test_start_*`、`test_active_run_guard`、`test_from_scratch_path`、`test_product_change_*`、`test_bugfix_*`。

### 5.2 当前阶段提示词装配

- **为什么关键**：Python 程序本身不和用户讨论产品，也不生成产品语义；AI 能否正确工作取决于这里是否完整加载正确提示词。
- **对应产品内容**：需求讨论、共同理解确认、正式产品文档生成和已有代码调查。
- **代码位置**：`src/workflow_loop/cli.py` 中的 `cmd_discuss()`、`load_doc_content()`；`src/workflow_loop/stages/stages.py` 中各阶段的文档路径方法。
- **上游**：当前工作流已经启动，AI 调用 `workflow discuss`。
- **主要处理**：根据当前阶段获得角色；读取全局写作规范；读取阶段模板和规范；对 `ProjectDesignInitStage` 继续读取产品模板、产品规范、代码架构模板和代码设计规范。
- **下游**：完整打印给 AI，并记录“提示词加载”和“角色文档加载”。
- **状态和数据**：只追加 journal，不改变阶段门禁。
- **失败结果**：没有工作流、工作流已结束、阶段实现不存在时停止；某个 Markdown 不存在时把缺失路径打印出来。
- **验证位置**：`test_discuss_loads_global_writing_standard_before_stage_docs`、`test_code_design_discuss_prints_product_driven_architecture_rules`、`test_project_design_init_discuss_prints_investigation_and_output_rules`。

### 5.3 三道门禁与阶段推进

- **为什么关键**：它是“讨论完成、产物存在、用户确认”不能跳步的实际执行位置。
- **对应产品内容**：用户确认共同理解后才能生成正式文档，用户检查产物后才能作为后续依据。
- **代码位置**：`src/workflow_loop/cli.py` 中的 `cmd_gate()`；`src/workflow_loop/state.py` 中的 `GateState`。
- **上游**：AI 分别调用 `workflow gate <stage> --discuss-done`、`workflow gate <stage>`、`workflow gate <stage> --confirmed`。
- **主要处理**：第一道门写 `discussion_complete=true`；第二道门调用当前阶段的 `code_validate()`；第三道门写 `user_confirmed=true`、阶段状态 `done`，执行阶段推进钩子并进入下一阶段。
- **下游**：更新状态文件和 journal；架构阶段更新架构标记；项目设计初始化完成时更新项目级初始化状态。
- **状态和数据**：写 `.workflow_loop/state.json`、`.workflow_loop/project.json` 和 `.workflow_loop/journal.jsonl`。
- **失败结果**：跳过前一道门、产物缺失或上游验证失效时不推进。
- **验证位置**：`test_gate_order_enforced`、各阶段 `code_validate` 测试和命令测试。

### 5.4 产品设计产物校验

- **为什么关键**：这是程序判断产品设计文档是否已经出现的唯一位置。
- **对应产品内容**：产品设计阶段必须产生产品总说明和至少一份功能文档；已有项目初始化必须同时产生代码架构文档。
- **代码位置**：`src/workflow_loop/stages/stages.py` 中的 `SpecStage.code_validate()` 和 `ProjectDesignInitStage.code_validate()`。
- **上游**：`cmd_gate()` 执行第二道门。
- **主要处理**：检查 `spec/product.md`；使用 `glob` 查找英文前缀 `feature_*.md`；初始化阶段额外检查 `spec/architecture_code_design.md`。
- **下游**：返回 `(是否通过, 具体说明)` 给 `cmd_gate()`。
- **状态和数据**：校验通过后，`cmd_gate()` 写 `code_validated=true` 和 `artifact_produced_at`。
- **失败结果**：缺少任一必需文件时列出缺失项并停留在当前阶段。
- **验证位置**：`tests/test_stages.py`。

### 5.5 项目级设计初始化状态

- **为什么关键**：修 bug 或修改产品时，是否先建立产品和代码设计基线由它决定，不能只看某个文件是否存在。
- **对应产品内容**：项目设计未初始化时先建立文档；已经初始化时直接使用已有设计。
- **代码位置**：`src/workflow_loop/project.py` 中的 `ProjectState`、`is_project_design_initialized()`、`set_project_design_initialized()`；`cmd_gate()` 中的初始化状态更新分支。
- **上游**：安装时初始为 `false`；路径生成时读取；项目初始化或从零设计的产品与代码设计都确认后写为 `true`。
- **主要处理**：跨工作流保存在 `.workflow_loop/project.json`，不随新 `state.json` 覆盖。
- **下游**：`build_stage_path()` 据此决定 `product_change` 和 `bugfix` 是否前置 `ProjectDesignInitStage`。
- **失败结果**：文件缺失时按未初始化处理；从零设计开始时强制重置为 `false`。
- **验证位置**：`tests/test_project.py`、`tests/test_path_composer.py`。

### 5.6 上游变化后的验证失效

- **为什么关键**：代码或计划改变后，旧测试和验收结果不能继续被当作有效证据。
- **对应产品内容**：当前产品文档没有单独定义该行为；它是整个 Workflow Loop 的一致性约束。
- **代码位置**：`src/workflow_loop/verification.py` 中的 `compute_impl_hash()`、`check_invalidation()` 和 `clear_stage_gates()`。
- **上游**：实施、测试计划或验收计划确认时记录哈希；后续执行第二道门时重新计算。
- **主要处理**：发现实施变化时清零测试和验收；测试计划变化时清零测试和验收；验收计划变化时清零验收并退回测试计划检查。
- **状态和数据**：读写 `WorkflowState.verification` 和下游阶段门禁。
- **失败结果**：发现变化时不继续当前校验，要求重新生成下游产物。
- **验证位置**：`tests/test_verification.py`。

## 6. 各产品功能的代码设计

### 6.1 【功能】生成产品设计文档

#### 6.1.1 产品要求

AI 和用户先形成共同理解。用户确认后，AI 根据统一模板生成或修改 `spec/product.md` 和 `spec/feature_<english-name>.md`。已有代码项目首次初始化时，还要同时生成 `spec/architecture_code_design.md`。对应产品说明见[功能文档](./feature_product_design_document_generation.md)。

Python 程序负责选择阶段、打印提示词、保存门禁状态和检查文件是否存在。产品内容本身由 AI 根据提示词写入文件，不是由 Python 函数自动拼接生成。

#### 6.1.2 场景：从零生成产品设计文档

本图描述从 AI 启动 `from_scratch` 工作流，到产品设计文件通过程序校验。用户最终确认产物后，工作流进入代码设计阶段。

```mermaid
flowchart TD
    A["AI 启动从零设计<br/>workflow start --intent from_scratch"] --> B["生成从零阶段路径<br/>cli.py / cmd_start()<br/>path_composer.py / build_stage_path()"]
    B --> C["保存当前阶段为 spec<br/>state.py / save_state()<br/>写 state.json 和 journal.jsonl"]
    C --> D["加载产品模板和规范<br/>cli.py / cmd_discuss()<br/>SpecStage 文档路径"]
    D --> E["AI 与用户讨论并取得共同理解<br/>使用 spec 模板与规范；Python 不参与聊天"]
    E --> F["记录讨论完成<br/>cli.py / cmd_gate()<br/>discussion_complete=true"]
    F --> G["AI 写产品文档<br/>spec/product.md + spec/feature_*.md<br/>没有对应 Python 生成函数"]
    G --> H["检查文件存在<br/>stages.py / SpecStage.code_validate()"]
    H --> I["用户确认后推进<br/>cli.py / cmd_gate()<br/>current_stage=code_design"]
```

| 图中步骤 | 触发和输入 | 代码位置 | 具体处理逻辑 | 产生的状态、数据或输出 | 失败时的结果 | 验证位置 |
|---|---|---|---|---|---|---|
| 生成从零阶段路径 | AI 传入 `from_scratch` | `cli.py` 的 `cmd_start()`；`path_composer.py` 的 `build_stage_path()` | 检查安装和活跃工作流；发现清场范围内存在旧产物时进入清场确认；返回以 `spec` 开始的固定阶段列表 | `state.json` 中 `current_stage=spec` | 有活跃工作流时拒绝；有旧产物但未确认清场时不启动 | `test_start_with_intent_from_scratch_no_artifacts`、清场测试、路径测试 |
| 加载产品模板和规范 | 当前阶段为 `spec` | `cli.py` 的 `cmd_discuss()`；`SpecStage.prompt_doc_path()` 和 `standard_doc_path()` | 完整读取全局写作规范、产品模板、产品流程规范和角色说明 | stdout 给 AI 完整工作材料；journal 追加加载记录 | 文档缺失时打印具体缺失路径 | `test_discuss_loads_global_writing_standard_before_stage_docs` |
| 记录讨论完成 | 用户已经明确同意共同理解 | `cli.py` 的 `cmd_gate()` | 处理 `--discuss-done`，把第一道门写为通过 | `GateState.discussion_complete=true` | 没有当前工作流或阶段不存在时停止 | `test_gate_order_enforced` 反向证明不能跳过 |
| 写产品文档 | 已经通过讨论完成门禁 | 无 Python 生成函数；依据 `Template_Repository/spec/spec.md` | AI 按九章产品总说明和六章功能文档模板写文件 | `spec/product.md`、至少一个 `spec/feature_*.md` | 内容错误由用户审查；程序当前只检查文件存在 | 产品文档本身、安装提示词测试 |
| 校验并推进 | 文件已写完，随后用户确认 | `SpecStage.code_validate()`；`cmd_gate()` | 第二道门检查文件；第三道门标记用户确认并进入 `code_design` | 阶段状态 `done`，下一阶段 `in_progress` | 文件缺失时停留在 `spec`；未过第二道门不能确认 | `tests/test_stages.py`、命令门禁测试 |

#### 6.1.3 场景：更新已有产品设计文档

本图描述项目设计已经初始化时，`product_change` 直接进入产品设计阶段。若尚未初始化，系统先走下一节的已有项目初始化流程。

```mermaid
flowchart TD
    A["AI 启动修改产品<br/>workflow start --intent product_change"] --> B["读取项目初始化状态<br/>project.py / is_project_design_initialized()"]
    B -->|true| C["生成 product_change 路径<br/>path_composer.py / build_stage_path()<br/>当前阶段为 spec"]
    B -->|false| D["先进入 project_design_init<br/>复用 6.1.4 的初始化流程"]
    C --> E["加载现有产品修改规则<br/>cli.py / cmd_discuss()<br/>SpecStage 文档路径"]
    E --> F["AI 读取现有 product.md、feature_*.md 和相关代码<br/>按确认结果修改受影响文件"]
    F --> G["检查产品文件存在<br/>stages.py / SpecStage.code_validate()"]
    G --> H["用户确认后进入 revise_code_design<br/>cli.py / cmd_gate()"]
```

| 图中步骤 | 触发和输入 | 代码位置 | 具体处理逻辑 | 产生的状态、数据或输出 | 失败时的结果 | 验证位置 |
|---|---|---|---|---|---|---|
| 判断是否需要初始化 | AI 传入 `product_change` | `project.py` 的 `is_project_design_initialized()`；`path_composer.py` 的 `build_stage_path()` | 读取 `.workflow_loop/project.json`，决定是否在 `spec` 前加入 `ProjectDesignInitStage` | 不同的 `stage_path` | 项目状态文件缺失时按未初始化处理 | `test_product_change_with_uninitialized`、`test_product_change_with_initialized` |
| 修改受影响文档 | 用户已经确认本次变化 | 无 Python 修改函数；依据产品设计流程规范 | AI 自行读取现有文档和代码，只修改确认受影响的内容 | 更新 `product.md` 和一个或多个 `feature_*.md` | 程序不能判断是否误改无关内容 | 产品流程规范；当前无自动内容测试 |
| 文件校验 | AI 写完文档 | `SpecStage.code_validate()` | 检查产品总说明和至少一份英文功能文件存在 | 第二道门可通过 | 当前不会校验文件是否真的发生变化 | `tests/test_stages.py`；差异见第 8 章 |

#### 6.1.4 场景：根据已有代码建立产品设计文档

本图描述 `product_change` 或 `bugfix` 在项目设计未初始化时，共用的 `project_design_init` 流程。

```mermaid
flowchart TD
    A["路径要求初始化<br/>path_composer.py / build_stage_path()<br/>project_design_initialized=false"] --> B["加载专用调查规则和两套文档模板<br/>cli.py / cmd_discuss()<br/>ProjectDesignInitStage.additional_doc_paths()"]
    B --> C["AI 查看说明、配置、入口、调用链和测试<br/>具备安全条件时运行项目<br/>由提示词约束，无 Python 自动调查函数"]
    C --> D["用户确认当前产品和代码理解<br/>cli.py / cmd_gate()<br/>discussion_complete=true"]
    D --> E["AI 一次写三类文档<br/>product.md + feature_*.md + architecture_code_design.md"]
    E --> F["同时检查三类文件<br/>stages.py / ProjectDesignInitStage.code_validate()"]
    F --> G["用户确认初始化结果<br/>cli.py / cmd_gate()<br/>project.py / set_project_design_initialized()"]
    G --> H["写初始化状态和初步架构标记<br/>project_design_initialized=true<br/>architecture.preliminary_done=true"]
```

| 图中步骤 | 触发和输入 | 代码位置 | 具体处理逻辑 | 产生的状态、数据或输出 | 失败时的结果 | 验证位置 |
|---|---|---|---|---|---|---|
| 加载组合规则 | 当前阶段为 `project_design_init` | `ProjectDesignInitStage.prompt_doc_path()`、`standard_doc_path()`、`additional_doc_paths()`；`cmd_discuss()` | 先打印专用调查提示词和规范，再附加打印产品文档模板/规范与代码架构模板/规范 | AI 同时获得调查方法和三类文档结构 | 任一资源缺失时打印缺失路径 | `test_project_design_init_discuss_prints_investigation_and_output_rules`、`test_project_design_init_loads_specialized_and_shared_documents` |
| 查看和运行代码 | 已有代码项目可安全调查 | 无 Python 自动调查函数；由 `project_design_init` 规范约束 AI | AI 阅读项目并执行测试、构建或主要入口，把结论分成运行确认、测试确认、代码确认、未确认和冲突 | 形成用户确认的当前产品与代码理解 | 是否真的执行只能由运行记录、聊天和用户审查确认 | 当前提示词测试；本项目本次实际运行提供示例证据 |
| 一次写三类文档 | 用户确认当前理解 | 无 Python 生成函数；依据三套模板 | AI 写产品总说明、全部必要功能文档和代码架构文档 | 三类 `spec/` 文件 | 文档之间是否一致目前没有程序语义校验 | 用户审查；差异见第 8 章 |
| 校验和标记初始化 | 三类文件已经存在并经用户确认 | `ProjectDesignInitStage.code_validate()`；`cmd_gate()`；`set_project_design_initialized()` | 第二道门检查文件；第三道门更新阶段、架构标记和项目级初始化状态 | 后续工作流可跳过重复初始化 | 任一文件缺失时不推进 | `tests/test_stages.py`、项目状态和路径测试 |

#### 6.1.5 场景：修 bug 前初始化产品设计

本场景复用上一节的初始化代码，只是入口和初始化后的下一阶段不同。

```mermaid
flowchart TD
    A["AI 启动修 bug<br/>workflow start --intent bugfix"] --> B["读取项目初始化状态<br/>project.py / is_project_design_initialized()"]
    B -->|false| C["前置 ProjectDesignInitStage<br/>path_composer.py / build_stage_path()"]
    C --> D["执行 6.1.4 的代码调查、文档生成和三类文件校验"]
    D --> E["初始化完成后进入 reproduce<br/>cli.py / cmd_gate()<br/>current_stage=reproduce"]
    B -->|true| E
```

| 图中步骤 | 触发和输入 | 代码位置 | 具体处理逻辑 | 产生的状态、数据或输出 | 失败时的结果 | 验证位置 |
|---|---|---|---|---|---|---|
| 生成 bugfix 路径 | AI 传入 `bugfix` | `path_composer.py` 的 `build_stage_path()` | 未初始化时返回 `project_design_init → reproduce → fix_plan → ...`；已初始化时从 `reproduce` 开始 | `state.json` 保存固定阶段路径 | 未知意图时抛出错误 | `test_bugfix_with_uninitialized`、`test_bugfix_with_initialized` |
| 初始化后推进 | 三类文档通过校验并由用户确认 | `cli.py` 的 `cmd_gate()` | 设置项目初始化状态和初步架构标记，进入下一阶段 `reproduce` | 修复过程获得产品和代码设计基线 | 未通过门禁时不能进入复现阶段 | 项目状态、阶段和命令测试 |

#### 6.1.6 产品规则和异常怎样落实

| 产品规则或异常 | 发生条件 | 流程中的处理位置 | 对应代码或提示词 | 处理结果 |
|---|---|---|---|---|
| 用户确认共同理解后才能写文档 | 产品设计讨论结束 | 所有场景的第一道门 | `cmd_gate()` 的 `--discuss-done` 分支；产品流程规范 | `discussion_complete=true` 后命令才提示写产物 |
| 未确认就尝试校验 | 第一门仍为 `false` | 产品文件校验前 | `cmd_gate()` 第二道门前置检查 | 打印错误并停止，不执行 `code_validate()` |
| 产品总说明缺失 | 执行产品设计文件校验 | `SpecStage.code_validate()` | `stages.py` | 返回失败并指出 `spec/product.md` 不存在 |
| 没有英文功能文档 | `spec/` 中没有 `feature_*.md` | `SpecStage.code_validate()` | `glob.glob(..., "feature_*.md")` | 返回失败，旧中文文件名不能冒充功能文档 |
| 已有项目三类文档不完整 | 执行初始化文件校验 | `ProjectDesignInitStage.code_validate()` | `stages.py` | 列出缺少的产品总说明、功能文档或代码架构文档 |
| 从零设计发现旧产物 | `spec/`、`plan/` 等约定目录已有文件 | `cmd_start()` 的清场分支 | `detect_clean_artifacts()`、`clean_artifacts()` | 未确认时只列清单；确认后才删除并启动 |
| 已有活跃工作流 | 再次执行带意图的 `start` | `cmd_start()` 开始位置 | `state.is_active_run()` | 拒绝启动，要求先完成或作废旧工作流 |
| 产品历史没有依据 | AI 准备写产品背景或历史原因 | 产品讨论和写文档阶段 | 产品模板、产品流程规范、全局写作规范 | 要求继续询问或标记未确认；程序当前不能自动发现编造 |
| 已有项目运行有风险 | 需要生产账号、真实数据、付费服务或外部写入 | `project_design_init` 调查阶段 | 专用初始化规范 | AI 必须先取得用户同意；程序当前没有运行权限记录字段 |
| 修 bug 需要改变产品行为 | 缺陷修复会改变规则、边界或用户结果 | 工作意图判断和修复讨论 | 产品流程规范；`INTENT_CHOICES` 支持 `product_change` | 应停止按普通 bugfix 处理，重新以修改产品启动；程序不能自动判断语义变化 |

## 7. 多个功能共同使用的代码

### 7.1 阶段策略接口

`StageStrategy` 是所有阶段共同使用的代码接口。它统一提供阶段名称、产物路径、提示词路径、规范路径、代码校验和推进钩子。`cmd_discuss()` 和 `cmd_gate()` 因此不需要为每个阶段分别写一套加载与门禁代码。

修改该接口会影响产品设计、代码设计、穿刺、计划、实施、测试、验收和缺陷复现全部阶段。验证位置是阶段单元测试、路径测试和命令测试。

### 7.2 单次工作流状态

`WorkflowState` 保存一轮工作流的意图、当前阶段、阶段路径、三道门禁、架构完成度和验证哈希。所有改变阶段的命令都必须通过 `load_state()` 读取，再通过 `save_state()` 写回。

`.workflow_loop/state.json` 是“现在在哪里”；它会在下一轮工作流启动时被覆盖。状态序列化和字段完整性由 `tests/test_state.py` 验证。

### 7.3 项目级初始化状态

`ProjectState` 单独保存 `project_design_initialized`，因为它要跨工作流保留，不能随 `state.json` 覆盖。产品修改和修 bug 都读取这个字段决定是否先建立产品与代码设计基线。

`.workflow_loop/project.json` 是“这个项目是否已经完成初始设计”。它的持久化由 `tests/test_project.py` 验证。

### 7.4 历史审计记录

`journal.append_entry()` 把启动、提示词加载、门禁结果、阶段推进、架构标记和工作流结束追加到 `.workflow_loop/journal.jsonl`。它不会改写旧记录；`workflow status` 读取最近十条供用户查看。

当前 journal 证明命令被调用过，但不能单独证明 AI 的讨论内容正确或用户理解了文档。

### 7.5 全局写作规范和阶段提示词

所有阶段共同加载 `Standardized_Repository/global/document_writing.md`。产品设计阶段和项目初始化阶段再加载各自模板与规范。这样“用直白话、不写废话、写前先查明事实”的规则只维护一处，阶段文件只写本阶段特有要求。

当前安装器会把包内资源复制到目标项目的 `.workflow_loop/`。同版本重复安装采用零修改策略，因此已经安装的其他项目不会自动获得本次提示词更新。

### 7.6 验证失效机制

`verification.py` 为实施记录和代码快照、测试计划、验收计划、测试结果保存哈希。后续门禁发现上游变化时清零相关下游门禁，防止旧测试或旧验收继续有效。

该机制服务整个工作流，但当前产品设计文档还没有把它写成正式产品功能或产品通用规则。

## 8. 产品设计与代码实现的差异

| 差异 | 产品设计要求 | 当前代码状态 | 影响 | 处理决定 | 证据状态 |
|---|---|---|---|---|---|
| 产品文档只定义了“生成产品设计文档”，代码实现了完整开发工作流 | 代码设计应当能追溯到产品功能或产品通用规则 | 穿刺、计划、验收计划、测试计划、实施、测试、验收、代码设计更新和验证失效已有代码，但没有对应产品功能文档 | 维护者可以看懂代码结构，但无法从产品设计确认这些行为是否完整、是否符合用户目标 | 后续应扩展产品总说明和功能文档，再补齐这些阶段的产品到代码映射；本次不自行编造产品设计 | 代码确认、文档确认，存在覆盖范围冲突 |
| 产品模板要求产品总说明九章、功能文档六章 | 程序应防止空文件或错误结构冒充完成 | `SpecStage.code_validate()` 只检查文件存在和 `feature_*.md` 文件名，不检查章节、链接或内容 | 不完整文档也能通过第二道门 | 当前依靠 AI 对抗性审查和用户确认；若要程序硬性保证，需要新增 Markdown 结构校验 | 代码确认、测试确认 |
| 修改已有产品时应只修改受影响内容 | 本轮必须证明 `product.md` 有变化，并且至少一个功能文档新增、修改或删除 | `SpecStage` 没有记录进入阶段时的文件哈希，也没有比较前后变化；`DESIGN.md` 对此有设计说明但代码未实现 | 旧文件不变也可能通过校验，无法证明产物属于本轮修改 | 保留为明确实现缺口，后续实施基线快照和变更校验 | 代码确认、设计文档确认，存在冲突 |
| 已有代码初始化时必须查看代码并在安全条件下运行 | 调查结论应有代码、测试和运行证据 | Python 只打印规范，不自动执行代码调查，也不保存“已运行哪些命令”的结构化证据 | AI 跳过运行时，程序无法自动拦截 | 当前由提示词、聊天记录、用户审查和测试结果约束；后续可增加调查证据清单或门禁校验 | 代码确认 |
| 产品功能清单中的链接必须真实可用 | `product.md` 中每个功能应链接到存在的文件 | 当前只检查至少一个 `feature_*.md`，不解析 `product.md` 链接 | 链接错误仍可能通过第二道门 | 后续可使用 Markdown 解析器校验功能链接和文件对应关系 | 代码确认 |
| 产品规则、边界、使用过程和异常必须与代码一致 | 初始化时三类文档应描述同一个实际产品 | `ProjectDesignInitStage.code_validate()` 只检查三类文件存在，不比较名称、规则、流程和异常 | 三类互相矛盾的文档也可能通过程序校验 | 当前靠组合提示词和用户确认；后续需要明确可机器检查的结构后再增加一致性校验 | 代码确认 |
| 同版本已安装项目应怎样获得规范更新尚未定义 | 本次更新希望当前项目和未来安装使用新提示词 | 安装器检测版本相同后直接退出，其他已安装项目不会自动同步；当前项目已手动同步运行副本 | 不同项目可能继续使用旧提示词 | 保持当前零修改策略；升级机制另行设计，不在本次范围内 | 代码确认、用户先前决定 |
