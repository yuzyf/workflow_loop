# Workflow Loop

把 AI 驱动的软件开发过程从“读 markdown 自觉遵守”变成“不过代码门禁就不能推进”的流程约束上下文。

## Language

**Workflow Run**:
一次从开工到 `done` 的完整流程实例；有当前快照与历史记录。
_Avoid_: Session, job, task, 场景实例

**Project Asset State** (项目资产状态):
开工时由代码读取的事实状态，用来和 Work Intent 一起生成 Stage Path。日常开工的主信号是 `state.json` 中是否存在 active Run，以及产品说明、架构文档等资产是否存在。项目安装是官方安装脚本负责收敛的硬前置，不再作为用户提问后的正常分流。
_Avoid_: Scenario, entry, 项目类型, maturity alone

**Workflow Loop Project Installation** (项目安装状态):
项目是否已经安装本流程运行时。代码主判定：项目根下存在 `.workflow_loop/` 目录和安装版本标记即为已安装；不存在则为未安装。未安装不是一种 Work Intent，也不是四选一 Scenario。
_Avoid_: existing-no-workflow（旧场景名）, entry, 用户自报是否接入

**Installed Project** (已安装项目):
已安装：根目录存在 `.workflow_loop/` 和安装版本标记。
_Avoid_: existing project（太泛，有代码≠已接入）

**Uninstalled Project** (未安装项目):
未安装：根目录不存在完整的 `.workflow_loop/` 安装骨架。必须先在项目根执行官方安装脚本，而不是让用户在菜单里选“存量无 workflow”，也不是在 `start --intent` 里静默安装。
_Avoid_: greenfield（那是意图，不是接入状态）


**Installation Prerequisite** (安装硬前置):
未安装项目不能初始化带意图的 Workflow Run。必须先由官方安装脚本完成当前项目安装，使项目根下存在完整 `.workflow_loop/`，然后才能 `start --intent`。项目安装不是三种工作意图之一，也不是旧四场景里的可选项。全局 CLI 内部仍须把“找不到完整 `.workflow_loop/` 与安装版本标记”作为异常保护并立即停止，但不把它画成日常开工的正常业务分支。
_Avoid_: 在 start --intent 里静默安装并直接开跑；把未安装当成与修 bug 并列的菜单项


**Official Install Command** (官方安装命令):
用户先进入目标项目根目录，只执行一条官方终端安装脚本命令（例如 `curl -fsSL <安装地址>/install.sh | bash`，发布地址待实现时确定）。该脚本在一次运行里完成两件事：电脑尚无 `workflow` 时安装全局命令；随后安装当前项目。面向用户不再提供 `workflow attach` 第二步。

安装脚本必须在任何写操作前，先打印当前目录的绝对路径，以及将检查或修改的 `AGENTS.md` 和 `.workflow_loop/`，在终端只等待用户确认项目目录。用户取消时，整个安装立即结束：不安装全局 `workflow`、不修改代理契约、不创建 `.workflow_loop/`。目录确认通过后不再询问代理契约冲突，未安装项目直接新建或覆盖 `AGENTS.md`，然后完成全局命令安装和项目文件写入。

安装时严格把当前目录当作项目根，不自动向上猜 `.git`；目录不对时用户取消、切到正确目录后重跑。安装完成后的日常 `workflow` 命令才从当前目录向上查找 `.workflow_loop/`。

**瘦骨架（仅这些）**：
1. 创建 `.workflow_loop/`
2. 复制系统默认 `Template_Repository` 与 `Standardized_Repository` 进项目 `.workflow_loop/`
3. 新建或直接覆盖最小代理契约，文件名固定为 **`AGENTS.md`**
4. 写入很小的安装版本标记
5. 创建 `.workflow_loop/project.json`，初始写入 `project_design_initialized=false`，用于记录项目级设计架构初始化状态
**明确不做**：不创建 `state.json`（那是 `start --intent`）；不预建空的项目根 `spec/`、`plan/`、`acceptance/`、`qa/`、`impl/`、`bug/`（首次写产物时再建）；不下发 role 说明文件（角色说明暂时留在代码/`role_doc`，与提示词仓库分离）。安装成功后才允许 `start --intent`。
_Avoid_: 要求目标项目里先有 workflow.py, 全局命令安装与项目安装要求用户执行两条命令, 安装时猜错项目根, start 时静默安装, 把安装做成带三道闸的正式 Stage, 安装时创建 state.json, 使用非 AGENTS.md 的契约文件名, 预建空产物目录, 下发 role 文档仓库


**Template Seeding** (模板与规范下发):
官方安装脚本安装当前项目时，将系统自带的默认 **Template_Repository**（提示词/模板仓库）与 **Standardized_Repository**（规范词仓库）复制进项目 `.workflow_loop/`。之后 `discuss` 从**项目内**这两份仓库加载提示词与规范（不在运行时直读全局安装包，便于项目定制）。
**默认内容来源（打包）**：两套仓库作为 Python 包装内资源随 `workflow-loop` 安装分发（如包内 `…/data/Template_Repository` 与 `…/data/Standardized_Repository`），用 `importlib.resources`（或等价）定位后复制。不依赖开发仓库路径，也不以 `~/.workflow_loop/templates` 为唯一源。
清场从不删除项目内两套仓库；系统升级默认不覆盖项目已改内容。
_Avoid_: 安装只建空模板目录, 运行时只读系统目录导致项目无法定制, 清场删掉模板/规范仓库, 全局 CLI 从本机 spike 源码树读模板, 仅主目录松散模板无包装内资源
**Agent Contract File** (代理契约文件):
项目根的代理契约，文件名只使用 **`AGENTS.md`**。
安装策略：
- 当前项目未安装时：无论 `AGENTS.md` 是否存在，安装程序都写入固定的最小代理契约；契约包含 workflow 入口、stdout 跟随规则和核心表达要求。文件存在时直接整份覆盖，不询问、不合并、不备份
- 当前项目已有完整骨架和有效安装版本标记时：按 Repeat Installation 直接退出，保持零修改，不覆盖项目已有 `AGENTS.md`
- 安装开始时仍须先让用户确认当前目录；直接覆盖只发生在目录已经确认正确之后
_Avoid_: 自动合并契约, 目录未确认就写入, 使用非 AGENTS.md 的契约文件名, 长期维护双份契约正文, 重复安装重写 AGENTS.md

**Repeat Installation** (重复安装):
若当前项目已有完整 `.workflow_loop/` 和有效安装版本标记，安装脚本判定该项目已经安装，直接退出且不修改任何文件：不覆盖 `AGENTS.md`，不重新复制模板和规范，不重建运行状态。安装输出只说明「当前项目已经安装，未修改任何文件」，不要求用户手动执行 `workflow start`。

用户接下来直接启动 Codex / OpenCode 并提出正常需求；智能体读取 `AGENTS.md` 后自动调用 `workflow start`。第一版不在安装脚本里做升级或修复，升级流程后置单独设计。
_Avoid_: 重复安装覆盖项目定制模板, 重复安装重写代理契约, 把 workflow start 作为用户手动操作, 安装器顺便升级或修复

**Active Run Guard** (进行中流程守卫):
仅当 `state.json` 存在且 **`run_status=active`** 时，禁止再 `start --intent`；应提示 `status` 继续原流程（或先 `done`/`abort`）。`completed` / `aborted` 不拦截。新开时覆盖写入新 state（见 State File Lifecycle）。
_Avoid_: 静默覆盖仍为 active 的 state, 并行多个 Run, completed/aborted 仍禁止 start


**State File Lifecycle** (状态文件生命周期):
项目内同时最多一份快照文件：`.workflow_loop/state.json`。用 **`run_status`** 区分生命周期：`active`（进行中）/ `completed`（`done` 收工）/ `aborted`（`abort` 作废）。
- `run_status=active` → Active Run Guard 禁止再 `start`
- `completed` 或 `aborted` 后：允许新 `start --intent`；新 Run **直接整份覆盖**写入新 `state.json`（新局 `run_status=active`），不另建 history 目录
- 历史追溯：依赖 Journal；不堆叠多份 state 文件
- `abort` 不删产物、不删 state 文件（仅改状态直至被下次 start 覆盖）
_Avoid_: 多 state 并行, start 前强制归档旧 state 到 history（当前不做）, 完成后仍拦 start, 靠手删 state 才能重开, 仅用 current_stage 表达 aborted/completed



**Abort Command** (作废命令):
全局命令 `workflow abort`：将**进行中**的 Workflow Run 正式中止。行为：把 `run_status` 标为 `aborted`、记结束时间、写 Journal；**不**删除已有 Artifact；**不**删除 `state.json`（保留作废快照直至下次 `start` 覆盖）。之后 Active Run Guard 视为无活跃 Run，允许重新 `start --intent`。对已 `completed` / 已 `aborted` / 无 state 的调用应明确报错或提示，不静默空操作装成功。
_Avoid_: 无正式作废只能手删 state, abort 默认清空产出文档, abort 删除 state.json, 用 current_stage=aborted 冒充 Run 生命周期

**Work Intent** (工作意图):
用户这次开工要达成的目标类别（例如修缺陷、改产品、从零做能力）。应在同一维度上互斥可选。
_Avoid_: Scenario, entry, use case（当它和状态混用时）

**Done Command** (收工命令):
整轮 Workflow Run 的正式结束登记，命令为 `workflow done`。用户侧的最后一次确认发生在**最后一个 Stage** 的第 3 道门（`gate <末段> --confirmed`，确认的是该阶段产出，不是另开「结束确认」环节）。末段确认后 stdout 指示 AI 调 `workflow done`：将 `run_status` 置为 `completed`、写结束时间、journal「工作流完成」、解除 Active Run Guard，允许之后重新 `start --intent`。`done` **不**再向用户二次确认「整轮结束」；**不**删除产物；**不**在 done 时改写 `bug/index.md` 等文档（bug 类产物以 reproduce 等路径上 Stage 的门禁产出为准）。前置：所有 Stage 已走完且 `current_stage` 已到可收工状态（与现实现一致：末段推进后才允许 done）。与 `abort`（中途作废）互斥。
_Avoid_: 末段 confirmed 自动整轮结束, done 再问用户确认结束, done 清产物, done 偷偷沉淀 bug 册, 无显式 done 仅靠 stage 完成判断 Run 结束

**Work Intent Set** (工作意图集合):
当前正式互斥意图仅三类：`from_scratch`（从零做）、`product_change`（改产品）、`bugfix`（修 bug）。`docs_only` 暂不作为正式意图。
_Avoid_: 把 existing-no-workflow / 项目安装流程 当作意图；greenfield（过抽象，已废弃）

**From Scratch Intent** (从零做):
几乎空着手交付新能力或新项目的工作意图。
_Avoid_: greenfield, new-project（旧场景名，易与是否接入混淆）

**Product Change Intent** (改产品):
在已有产品上修改设计或增加功能的工作意图。
_Avoid_: product-mod（旧场景名）, feature request alone

**Project Design Initialized** (项目设计架构已初始化):
项目级持久事实，记录在 `.workflow_loop/project.json` 的 `project_design_initialized` 字段中，不放进会被新 Run 覆盖的 `state.json`。安装时初始为 `false`。首次处理已有代码项目时，`product_change` / `bugfix` 共享前置 `project_design_init` Stage；它根据代码建立 `spec/product.md`、多个 `spec/feature_<english-name>.md`、`spec/architecture_code_design.md` 与 `spec/project_design_init_evidence.md`。设计文档和调查证据通过门禁并由用户确认后才写为 `true`。若在该 Stage 完成前作废，字段保持 `false`。`from_scratch` 不走该前置 Stage，但在 `spec` 与初步 `code_design` 均确认完成后同样写为 `true`。
_Avoid_: 用架构文件是否存在代替初始化状态, 把字段放进单轮 state.json, 只生成架构文档就视为项目设计已初始化, 安装时直接写 true

**Bugfix Intent** (修 bug):
定位并修复一个具体缺陷的工作意图。
_Avoid_: bugfix scenario（旧四选一场景）

**Stage Path** (阶段路径):
本次 Workflow Run 将顺序经过的 stage 列表。项目安装是开工硬前置；安装完成后，路径由「工作意图」与 `project_design_initialized`（项目设计已初始化）等项目事实组合生成，而不是从固定四场景枚举取出。
_Avoid_: Scenario stages, pipeline template（若暗示四条平行流水线）

**Stage Path Composition** (路径拼法):
- 未安装：必须先在项目根执行官方安装脚本；日常 CLI 只做异常保护，不在 `start` 状态检查中提供安装分支
- **from_scratch（从零做）**：先清场（删除旧设计/过程产物；保留规范与模板仓库）→ `spec`（产品设计 + 功能拆分）→ `code_design`（初步，不可因旧文件跳过）→ `spike`（可选）→ `acceptance_plan`（确定主题和完成标准）→ `test_plan`（确定测试覆盖）→ `plan`（制定实施计划）→ `topic_execution`（各主题分别实施、测试和验收）→ `regression_test`（最终全量回归）→ `overall_acceptance`（整体验收）→ `update_code_design`（详细落地，强制）
- **product_change（改产品）**：若 `project_design_initialized=false`，先走 `project_design_init`；之后统一走 `spec` → `revise_code_design` → `spike`（可选）→ `acceptance_plan` → `test_plan` → `plan` → `topic_execution` → `regression_test` → `overall_acceptance` → `update_code_design`
- **bugfix（修 bug）**：若 `project_design_initialized=false`，先走 `project_design_init`；之后走 `reproduce` → `spike`（可选）→ `acceptance_plan` → `test_plan` → `fix_plan` → `topic_execution` → `regression_test` → `overall_acceptance` → `update_code_design`。`reproduce` 负责复现缺陷并确认根因；`spike` 只验证修复 bug 时仍未确认、并且必须用真实运行证据才能确认的具体事项。修复所需事实都已经确定时，由用户确认后跳过穿刺。
- `project_design_initialized=true`：改产品/修 bug 跳过共享初始化阶段；文件是否存在不能单独决定跳过。任何意图不得跳过末段详细架构 Stage
- 共享后半截：`acceptance_plan` → `test_plan` → `plan` / `fix_plan` → `topic_execution` → `regression_test` → `overall_acceptance` → `update_code_design`
_Avoid_: 修 bug 可无设计基线, 写完测试计划就视为测试通过, 写完验收计划就视为验收通过, impl 后直接更新架构而不执行测试和验收, 旧四场景平行流水线, 改产品保留 requirement/product_update/feature_split 三段式流程

**Architecture Document** (架构文档):
固定产物 `spec/architecture_code_design.md`（code_design）。已经安装 Workflow Loop 并进入正式开发路径的项目，必须有该文档；不是可有可无的附件。
_Avoid_: 可长期缺失的架构说明, 仅口头架构

**Architecture Doc Phases** (架构文档双阶段):
同一份架构文档的两种完成度，不是两个无关文件：
1. **初步架构**（前期设计）：路径前段产出或补齐，服务计划与实施前的共同理解。从零做时顺序固定为**先产品设计与功能拆分、后初步架构**（先定做什么，再定怎么搭）；首次接入已有代码项目时由 `project_design_init` 与产品、功能基线一起从代码反推建立。
2. **详细架构**（代码通过最终全量回归和整体验收后）：`overall_acceptance` 之后强制更新/写全，反映最终被验证和接受的真实结构
Stage 命名：从零做的前段初步架构为 `code_design`；存量项目首次初始化为 `project_design_init`；改产品设计期为 `revise_code_design`；**所有意图** 在 `overall_acceptance` 后一律进入 `update_code_design`。废弃 `generate_code_design`。
_Avoid_: 只在 impl 后才第一次写架构, 未测试验收就写最终详细架构, 有初步无详细收尾, 有详细却声称前期不需要图

**Project Design Init Skip** (项目设计架构初始化跳过):
仅对 `product_change` / `bugfix`：读取 `.workflow_loop/project.json` 的 `project_design_initialized`。为 `true` 时跳过共享前置 `project_design_init`；为 `false` 时必须执行。不得再用 `spec/architecture_code_design.md` 或其它单个文件是否存在决定跳过。这不表示本轮可以不改架构图：改产品在 `spec` 后必须有 `revise_code_design`，任何意图在测试与最终验收后必须有详细 `update_code_design`。不适用于 `from_scratch`。
_Avoid_: 用架构文件存在代替项目初始化标记, 从零做进入存量初始化, 跳过初始化被理解成整轮不改架构, 因已有架构而跳过末尾详细更新


**Architecture Gate Marks** (架构门禁标记):
State Snapshot 中记录架构完成度，至少区分 `architecture.preliminary_done`（初步架构完成）与 `architecture.detailed_done`（详细架构完成）。前段架构 Stage 用户确认后置 preliminary；`overall_acceptance`（整体验收）之后的 `update_code_design` 经用户确认后置 detailed。文件存在只是必要条件；**不得**因 `spec/architecture_code_design.md` 已存在而自动跳过详细架构收尾。
_Avoid_: 仅用文件存在判定详细完成, 初步与详细共用一个模糊 done 位



**Scenario** (场景，旧模型):
历史上把资产状态与工作意图捏成四个互斥入口（new-project / existing-no-workflow / bugfix / product-mod）的错误模型。新模型中不再作为主入口概念。
_Avoid_: 继续用 scenario 指“本次要做什么”

**Entry** (入口，旧模型):
旧 CLI 里 `start --entry` 的四选一键。新模型中不应再表示互斥场景；若保留命令形态，语义需重定义为“意图 + 状态”的启动参数，而不是场景 ID。
_Avoid_: 把 entry 当场景主键

**Stage**:
路径上的一个具名环节（如 `spec`、`spike`、`acceptance_plan`、`topic_execution`、`regression_test`）；内部走讨论与门禁循环。
_Avoid_: Step（易与 stage 内 7 步混淆）, phase（除非明确同义）

**Gate** (门禁):
阻止进入下一 Stage 的代码关卡（讨论完毕 / 产出校验 / 用户确认）。强制力放在门禁，不在每轮唠叨。
_Avoid_: Checkpoint（若不含强制）, validation alone

**Gate Policy** (门禁策略，第一版):
每个正式 Stage 仍保留**三道门、顺序硬性**（与现实现一致）：
1. 讨论完毕：`gate <stage> --discuss-done`
2. 代码/产物校验：`gate <stage>`
3. 用户确认：`gate <stage> --confirmed`
三类门禁都只能操作 `state.current_stage` 指向的当前阶段，不能提前操作后续阶段或重复操作已经完成的阶段。门3不能只相信之前保存的 `code_validated=true`；推进前必须重新执行当前阶段的产物校验，门2后文件被改坏时清除旧通过标记并停留在当前阶段。
入口与路径模型重做时**不砍门禁协议**。可选 spike 的 `gate spike --skip` 是额外跳过动作，不取消其它 stage 的三道门，也不把三道门合并或改成“校验过即当用户确认”。`topic_execution`（按主题实施、测试和验收）、`regression_test`（最终全量回归）与 `overall_acceptance`（整体验收）都是三种意图的强制 Stage，不提供 `--skip`；自动测试不可用时可执行人工测试并记录证据，环境阻塞或用户未验收不得按通过处理。
_Avoid_: 第一版砍掉讨论完毕闸, 合并校验与用户确认, 因入口重做而弱化用户确认, 跳过测试或最终验收, AI 自动替用户验收

**Core Diagram MECE Rule** (核心流程图完整展开规则):
核心 Draw.io 大画布必须分别完整展开 `from_scratch`、`product_change`、`bugfix` 三种互斥工作意图，并覆盖从 `start --intent`、全部 Stage、正常 `done`、中途 `abort` 到允许下一次开工的全部结果。

每一个 Stage 在每一条路径中的出现都按独立流程节点展示。即使当前若干 Stage 的讨论与三道门禁步骤相同，也不能用一个共享的“通用 Stage 循环”框代替其它 Stage；这些流程现在相同，不代表以后不会产生差异。每个 Stage 都要展示自己的进入条件、`discuss` 材料、智能体与用户动作、Artifact 路径、三道门禁命令与失败分支、state 修改、Journal 事件和下一步。

架构补齐、设计期架构修订、详细架构更新、清场确认、架构文件判断、spike 执行或跳过、topic 写入等规则必须放在实际发生的 Stage 或分支旁边，不另做无法对应主流程的规则页。
_Avoid_: 三条路径合并后丢失差异, 共享通用循环代替逐 Stage 细节, 只列 Stage 名不画内部流程, 把架构或状态规则拆成脱离主线的说明页

**Draw.io Page Architecture** (流程图页面结构):
最终流程图按四张大画布组织。页面按真实流程的大环节拆分，不按“架构规则”“状态文件”等知识主题拆分：
1. `00 用户从安装到一次工作结束，完整经过什么`：画真实端到端主流程，不做只有页面标题的目录。入口直接经过 `01` 官方安装脚本，由安装脚本处理重复安装并收敛到已安装状态；总览不再预先判断项目是否安装。之后串起启动 Codex / OpenCode、用户提问、智能体读取 `AGENTS.md`、`workflow start`、继续旧 Run 或选择新 intent、逐 Stage 执行、`done` / `abort`、等待下一次需求。
2. `01 安装脚本怎样把 workflow 和当前项目一次装好`：放大目录确认、重复安装判断、全局命令安装和项目文件写入。未安装项目直接新建或覆盖 `AGENTS.md`，不画契约冲突确认分支。
3. `02 用户提问后怎样继续旧工作或新开工作`：放大智能体读取最小代理契约、自动调用 `workflow start`、读取 `state.json`、active Run 分支和三种工作意图选择。不再展开 Shell / PATH 查找命令、项目根定位或项目安装判断。
4. `03 三种工作意图怎样走完所有阶段并结束`：同一张核心大画布中完整展开三种意图、每个独立 Stage 的全部细节、所有门禁与失败返回、`done`、`abort` 和下一次开工条件。

`03` 核心页采用同页上下两层：页面顶部用三条完整路线缩略带分别列出从零做、改产品、修缺陷从 `start --intent` 到 `done` / `abort` 的全部 Stage 顺序；下方再按从零做、改产品、修缺陷分成三块超大详细区，分别展开每一个 Stage。缩略带只用于在缩小视图时看清整体位置，不代替任何详细节点。

顶部缩略带与下方详细节点使用相同的稳定编号和名称，例如 `FS-03 初步架构`、`PC-03 设计期架构修订`。缩小时可看三条完整路线，放大时可读每个 Stage 的全部流程；画布初始可按约 22000×13000 规划，不够时继续扩展，不能为固定尺寸压缩节点。

`01`–`03` 都是 `00` 中某一段的原位放大，不是另起话题。每张放大图顶部保留同一条端到端路线缩略条并高亮本页位置；跨页入口和出口使用与 `00` 相同的编号和状态名称，使四页可以重新组成一个整体。

画布不限制为 800×600。主流程统一从左向右；失败返回只在当前节点内部或专用回路线中走；`abort` 使用独立的下方通道；Artifact、`state.json`、Journal 和架构规则贴在实际读写它们的流程节点旁边。禁止为了塞进一页而缩短间距、让连线穿过节点或让“是/否”共用线路。
_Avoid_: 总图只做页面目录, 详情页脱离总图位置, 固定幻灯片尺寸, 跨页编号不一致, 规则和数据单独漂浮, 线穿节点, 是非分支重叠

**Draw.io Branch Numbering** (流程图分支编号):
复杂分支使用全局唯一的层级编号，编号必须包含路线或页面前缀、所属 Stage，以及分支字母，不能只写会在大图中重复的局部 `A.0`。例如 `PC-00.D1` 表示改产品开工环节的第 1 个判断，判断后的两条分支分别从 `PC-00.A.0`、`PC-00.B.0` 开始，分支内按 `PC-00.A.1`、`PC-00.A.2` 依次编号；分支出口使用 `PC-00.A.OUT`，对应入口使用明确的 `IN` 编号。主干节点仍按 `PC-00.0`、`PC-00.1` 顺序编号。

编号本身必须足以回答“属于哪条路线、哪个 Stage、哪个分支、分支内第几步”。连线只表达相邻节点之间的方向，不能再让读者依赖追踪一条跨越半张图的长线来判断执行顺序。
_Avoid_: 只写 A.0 导致全图重复, 分支节点没有所属 Stage, 靠颜色代替编号, 靠长线猜执行顺序

**Draw.io Stage Ports** (流程图 Stage 出入口):
核心详细区不使用跨越多个 Stage 模块的长连线。每个 Stage 以全局唯一的命名出口结束，下一个 Stage 以配对入口开始，例如 `FS-04.A.OUT` 对应 `FS-05.IN-A`、`FS-04.B.OUT` 对应 `FS-05.IN-B`。两个模块相邻且连线能保持短、直、独占线槽时，可在配对端口之间画短线；距离较远或中间存在节点时，只显示完全一致的出口/入口编号，不画穿越其它模块的长线。

页面顶部的路线缩略带继续用连续箭头表达全局先后；下方详细区用 `OUT` / `IN` 配对表达精确衔接。二者职责分离：缩略带回答“整局先后顺序”，详细区回答“当前分支从哪里来、到哪里去”。
_Avoid_: 详细区用长线贯穿多个模块, 为了视觉连续而穿越节点, 出口入口编号不配对, 只画端口却不在顶部给整体路线

**Draw.io Explicit Join** (流程图显式汇合):
同一模块内的多个分支只有在业务状态已经收敛、下一步完全相同时才允许汇合，并且必须进入单独编号的显式汇合节点，例如 `PC-00.J.0`。每条分支从不同方向、不同端口独立进入 `J.0`，任何两条入线不得共享线段；`J.0` 之后才允许产生一条新的主干线。

若多个分支结束时仍保留不同状态、不同产物要求或不同下一步，则不得用汇合节点掩盖差异，必须各自保留独立的命名出口。显式汇合节点需要写清“哪些状态已一致”，不能只是没有业务含义的装饰圆点。
_Avoid_: 多条分支直接叠成一根线, 没有汇合节点却突然变成单线, 状态未收敛就强行汇合, 汇合节点不说明收敛结果

**Draw.io Branch Coverage** (流程图分支编号覆盖范围):
分支编号覆盖所有产生两个或更多结果的判断，不只覆盖三种 Work Intent（工作意图）。安装时的目录正确/不正确、重复安装/首次安装，状态检查时的 active/无 active，`project_design_initialized` 为 true/false、spike 执行/跳过、门禁校验通过/失败、修缺陷时有结构变化/无结构变化等，都必须为每个结果建立自己的 `…A.0`、`…B.0` 分支入口，并在分支内继续顺序编号。

分支含义写在 `.0` 入口节点内；判断节点到分支入口的短线上可重复写简短条件，但禁止只在线上悬挂“是/否”而没有可定位的分支节点。新增第三种结果时继续使用 `C.0`，不能把它塞进已有分支的说明文字。
_Avoid_: 只给三种意图编号, 门禁失败没有独立分支, 只在线上写是或否, 多个结果共用一个分支入口

**Draw.io Retry Ports** (流程图重试出入口):
门禁失败等返回重试路径也必须作为具名分支展开。失败分支按 `…B.0`、`…B.1` 顺序展示错误输出和修正动作，最后通过 `…B.RETRY.OUT` 指向同一模块内的 `…RETRY.IN`。当返回线能够在当前模块外侧独占一条短线槽，且不重叠、不交叉、不穿节点时，可以画实体回线；否则只保留完全配对的 `RETRY.OUT` / `RETRY.IN`，不画回头长线。

重试入口需要明确写出重新执行的节点，例如“重新执行门禁二”，不能只写“重试”。不同失败原因若需要不同修正流程，分别建立独立失败分支，不共用一条无法辨认的返回线。
_Avoid_: 回路线穿过主流程, 多条失败线共用线段, 失败后没有明确重试目标, 用一条长线跨越多个节点返回

**Draw.io Local Abort Branch** (流程图本地作废分支):
核心详细区不把多个 Stage 的 `abort`（中途作废）出口连接到一条共享红色总线。每个 Stage 都独立展开自己的短作废分支，例如 `FS-02.AB.0` 调用 `workflow abort`、`FS-02.AB.1` 写 `run_status=aborted`/结束时间/Journal、`FS-02.AB.2` 保留产物与 state、`FS-02.AB.OUT` 表示允许重新开工。宁可重复这些 Run 级规则，也不能用十几条线汇聚到同一通道。

页面顶部的路线缩略带可以保留一个“任一 active Stage 可作废”的总体出口，用于表达全局可能性；该总体出口不代替下方每个 Stage 的完整作废分支，也不从下方拉线连接到每一个 Stage。
_Avoid_: 多个 Stage 共用 abort 总线, 十几条垂线汇聚, 只在顶部写 abort 而详细 Stage 没有作废动作, 本地作废分支省略状态与保留规则

**Draw.io Reading Directions** (流程图阅读方向):
页面顶部的三条完整路线统一从左到右，表达 Stage 的全局先后。下方每个详细 Stage 模块内部统一从上到下，表达该 Stage 的材料、讨论、门禁、产物和状态变化；判断产生的兄弟分支从左到右各占一整列，分支之后不交换左右位置，显式汇合节点放在所有待汇合分支的下方。

新增分支时扩展新的分支列和画布宽度，不压缩已有列。详细模块的纵向主线与横向分支列是两个不同层级，不能在同一模块里交替改成蛇形阅读。
_Avoid_: Stage 内主线左右来回折返, 分支共用一列, 分开后交换左右位置, 为新增分支压缩节点和线槽

判断继续使用传统判断节点；不采用横向“判断条”作为多分支的统一替代形状。分支清晰度通过独立编号、独立结果入口、独立锚点、独立分支列和扩大画布解决，不能靠更换成判断条掩盖线路问题。
_Avoid_: 用判断条替代判断节点

**Draw.io Decision Anchors** (流程图判断节点锚点):
传统菱形判断节点的每个结果使用不同的固定锚点和不同的短连线。两结果判断分别从左下、右下出线；三结果判断分别从左侧、底部、右侧出线。每条线只连接紧邻的 `…A.0` / `…B.0` / `…C.0` 分支入口，之后分支只在自己的列内向下推进。多条结果线不得先共用一段再分开。
_Avoid_: 菱形多个结果共用出口, 结果线先重叠再散开, 直接从判断节点拉长线到远处动作

**Draw.io Connector Geometry** (流程图连线几何硬规则):
每条连线只表达一个明确的源节点到目标节点。除共同的源/目标节点或显式 `J.0` 汇合节点外，任意两条线不得重叠、交叉或接触；连线不得穿过任何非源/目标节点。只使用直角折线，不使用曲线、斜线或跨线桥掩盖交叉。

节点、分支列和空白线槽先布局，连线后添加。节点之间至少保留可独立布线的空白；平行线使用不同线槽。若一条连接必须绕过两个以上无关节点，改用编号配对的 `OUT` / `IN` 端口。任何冲突都通过扩大画布、增加分支列或复制局部说明解决，不能通过压缩间距、共用线段或缩小文字解决。

最终验图必须检查：线段之间无相交和共线重叠；线段不进入非端点节点矩形；每个判断结果都有独立 `.0` 入口；每个分支最终到终止节点、显式汇合节点或配对出口。
_Avoid_: 自动布线后不检查, 共用线槽, 线穿节点, 用颜色或跨线桥掩盖交叉, 固定画布导致压缩

**Topic** (主题):
验收计划根据已确认需求拆出的一个可独立验收结果名称。主题使用中文，名称直接写清验收对象和完成后的结果，不使用“功能优化”“流程完善”等模糊名称，也不使用“开发模块”“修改代码”“增加接口”等实施任务名称。主题文字本身就是唯一标识，不再另加 `PL-001` 一类编号；主题在整个项目历史中永久唯一，后续 Workflow Run 不得重复使用已有主题名称。一个 Workflow Run 可以有多个主题，每个主题分别制定验收计划和测试计划，并分别测试和验收。`acceptance/<topic>_plan.md`、`qa/<topic>_plan.md`、`qa/<topic>_result.md` 和 `acceptance/<topic>_result.md` 使用同一个主题名称。实施计划和实施记录必须写清关联哪些主题，但不强制与主题一一对应，也不强制使用主题作为文件名。

主题之间可以存在实施依赖。存在依赖时，实施计划产物必须写清前置主题和执行顺序，让实施阶段能够直接判断先实施哪个主题、后实施哪个主题。主题之间不得形成互相等待的循环依赖。没有依赖关系的主题不强制规定先后顺序。执行顺序由实施计划内容确定；`plan/index.md` 只负责索引实施计划文档，可以展示已经确定的顺序，但不单独制定另一套顺序规则。

主题在 `acceptance_plan` Stage 由用户确认，不在 `start`、`plan` 或 `fix_plan` 时临时确定。测试计划和实施计划不能自行改名、拆分或合并主题；发现主题过大、无法独立测试或无法独立实施时，必须返回验收计划重新调整，再重做受影响的后续产物。
_Avoid_: 一个 Workflow Run 强制只能有一个主题, 使用抽象主题名, 用开发任务充当验收主题, 为主题重复增加独立编号, 只要求单次 Run 内不重名, 后续 Run 复用旧主题名称, 测试计划或实施计划自行改名拆分合并主题, 测试验收实施无法一一对应, 只写存在依赖却不写执行顺序, 让索引单独制定一套执行顺序, 主题互相等待, start 或 plan 时才临时确定主题


**Artifact** (产出):
某 Stage 要求落盘的文档或文件集合；门禁会检查其是否就绪。落盘位置在**项目根下的产物目录**（如 `spec/product.md`、`plan/<主题>.md`），**不是** `.workflow_loop/Template_Repository/` 里的同名子目录。
_Avoid_: Output, deliverable（可作同义，但正式词用 Artifact）, 把 Template_Repository 下的提示词当成产物

**Process Artifact Roots** (过程产物根目录):
项目根下由 workflow 管理、清场可能删除的目录/文件约定位置，与模板仓库分离：
- 产物侧（可清场）：**固定落在项目根**（不是 `.workflow_loop/` 内）：`spec/`、`plan/`、`acceptance/`、`qa/`、`impl/`、`bug/` 等实际写出的文档
- 模板/规范侧（永不因清场删除）：`.workflow_loop/Template_Repository/`（含其中的 `spec/` 等**阶段提示词**子目录）、`.workflow_loop/Standardized_Repository/`
同名 `spec` 出现两次时含义不同：`Template_Repository/spec/` = 写产品说明时用的提示词；项目根 `spec/` = 写出来的 product.md / 架构文档等。
不把产物收到 `.workflow_loop/artifacts/`，也不统一改到 `docs/spec/` 等前缀（避免无收益大改路径）。
_Avoid_: 清场扫 Template_Repository, 认为产物写在 Template_Repository/spec 下, 混用两套 spec 路径, 产物迁入 .workflow_loop 或 docs/ 统一前缀

**Journal**:
Workflow Run 的只追加历史（发生过什么）。
_Avoid_: Log（太泛）, audit trail alone

**State Snapshot** (状态快照):
Workflow Run 的当前可写快照（现在在哪、各 gate 是否通过、topic 等）。
_Avoid_: State  alone without distinguishing journal


**State Intent Fields** (状态中的意图字段):
State Snapshot 以 `intent` 记录本次工作意图（`from_scratch` / `product_change` / `bugfix`），以 **`run_status`** 记录 Run 生命周期（`active` / `completed` / `aborted`），并展开本次 Stage Path 上的各 stage 状态、架构门禁标记（如 `architecture.preliminary_done` / `detailed_done`）以及验证绑定信息（当前代码/实施记录、测试计划、验收计划、测试结果的内容哈希）。`workflow_id` 可含时间与 intent，不再使用旧主模型字段 `scenario` / `entry` 表示四选一场景（穿刺允许直接删除，不做双写兼容）。
项目级字段 `project_design_initialized` 不属于 State Snapshot，固定存放在 `.workflow_loop/project.json`，不能随新 Run 覆盖。
_Avoid_: scenario/entry 作为场景主键, 双写旧四场景字段, 无 run_status 仅靠猜测 completed_at, 把项目级初始化字段放进 state.json

**Stdout Drive** (stdout 驱动):
智能体调用的每条 CLI 命令都在输出末尾用“下一步”指令驱动智能体继续调用或询问用户；流程真相在代码与 stdout，不在长篇 agent 契约。用户不手动执行 `workflow start` 来启动一局。
_Avoid_: Prompt injection, hook nagging

**Start Command** (开工命令):
项目安装完成后，用户启动 Codex / OpenCode 并直接提出需求；智能体读取最小代理契约 `AGENTS.md`，通过 Shell 工具自动调用全局 CLI `workflow …`，不是让用户手动输入命令，也不是调用目标项目内的 `python3 workflow.py`。项目首次安装由官方安装脚本完成，不属于 `workflow` 日常子命令。
**不带 `--intent`（只读状态检查）**：只读取工作状态并指路，不初始化 Run、不清场。正常流程已由官方安装脚本保证项目安装完成，stdout 按序回答：
1. **有进行中 Run** → 说明须 `status` 继续原流程（或先 `done`/`abort`）；禁止提示开新 Run
2. **无进行中 Run** → 列出三种意图及一句话说明；下一步：`workflow start --intent from_scratch|product_change|bugfix`
全局 CLI 仍须在内部解析项目根并校验完整 `.workflow_loop/` 与安装版本标记；校验失败时立即报错，禁止读取或创建 `state.json`。这是异常保护，不作为第 `00`、`02` 页的正常分支。清场清单仅在选定 `from_scratch` 且检查到过程产物时出现，不在状态检查总览里删除。
**带 `--intent`**：PathComposer 生成 Stage Path 并初始化 Workflow Run（`from_scratch` 另循 Clean Confirm）。`AGENTS.md` 只保留 workflow 入口、stdout 跟随规则和核心表达要求，不展开 stage 序列与门禁细节；`discuss` 负责加载详细写作规范和当前阶段材料。
_Avoid_: start --entry 旧四场景菜单, start 内补做项目安装, 状态检查初始化 Run 或清场, 把异常安装校验画成正常业务分支, 目标项目内 python3 workflow.py 作为唯一入口, 在 AGENTS.md 背诵完整 stage 列表

**Start Success Output** (带意图开工成功时的 stdout):
`workflow start --intent …` 真正初始化 Run 成功后，stdout 先打印**路径向开工摘要**（这局怎么走），不是提示词正文：
- `workflow_id`、`intent`、本局 Stage 路线图、当前 stage、清场/项目设计初始化跳过等标记
**下一步**：`workflow discuss` —— 由 discuss **完整打印**当前 stage 的提示词与规范（见 Prompt Full Print）。
「精简开工摘要」**仅**指 start 不倾倒文档百科、不代替 discuss；**绝不**表示提示词可以摘要、截断或不打印。
_Avoid_: 把开工摘要理解成精简提示词, start 不打印路线图, 用摘要替代 discuss 的完整提示词加载

**Discuss Command** (讨论加载命令):
`workflow discuss`：给**当前 AI**加载本 stage 工作材料。从项目内 `.workflow_loop/Template_Repository` 与 `Standardized_Repository` 读取后，在命令 stdout 中**完整输出**（AI 跑 CLI 时从工具结果读到全文，不是编一本给终端用户看的说明书）。固定拼装：
1. 当前 stage 名与角色说明全文（没有角色定义时明示无）
2. **全局写作规范全文**：固定读取 `Standardized_Repository/global/document_writing.md`
3. **提示词全文**（给 AI 的工作指令，不是给用户读的产品文案）
4. **阶段规范全文**（给 AI 的约束；该 stage 无规范则明示无）
5. 当前 stage 的附加材料、指令和约定产出路径
6. 下一步：AI 按提示词与**用户**讨论业务/方案；用户说讨论完毕后，AI 调 `workflow gate <stage> --discuss-done`
用户参与的是「业务讨论」；用户不负责阅读或批准提示词模板本身。无活跃 Run 或已 completed/aborted 则报错。不在每次 discuss 倾倒整份文档结构百科。
**可重复加载**：同一 stage 在 Run 仍为 active 且该 stage 尚未整轮结束前，允许多次 `discuss`，每次完整下发提示词/规范（AI 重载指令用）。重复 discuss **不**自动清零已通过的门禁（discussion_complete / code_validated / user_confirmed 不因 discuss 回滚）。

**Prompt Full Print** (提示词完整下发):
提示词/规范的消费者是 **AI**。`discuss` 必须在 stdout 给出**完整正文**，以便 AI 当轮上下文拿到全文；不得改成摘要版、截断版，也不得只打印文件路径让 AI「自己去读」却不给正文（路径可作附注）。不因 start 的路径摘要而缩短 discuss 输出。
_Avoid_: 把提示词当成写给用户的说明书, discuss 只打印路径不给正文, 提示词/规范摘要截断, 要求用户阅读/确认提示词模板, 每次 discuss 倾倒完整文档百科, 每 stage 只允许 discuss 一次, 重复 discuss 自动回滚门禁

**Plain-Language Output Standard**（直白输出规范）:
所有工作流正式文档和 AI 对用户的回复共同遵守的表达规则。输出前先弄清读者实际想知道或完成什么、已经确认哪些事实、受什么限制、读完后应知道或能做什么，再只写完成这个目的所需的内容。能用普通人听得懂的话就不用抽象词；确实必须使用专业词时，当场说明它具体指什么。句子要说清谁在什么情况下做什么、会得到什么结果；不规定固定表达顺序，不写删除后不影响事实、决定、行动或理由的废话。正式文档使用直白、准确、简洁的语气；AI 聊天使用直白、自然、像同事交流的语气。核心规则直接写入安装生成的 `AGENTS.md`，保证聊天从第一条回复开始受约束；详细规则、反例、改写例子和输出前检查放在 `.workflow_loop/Standardized_Repository/global/document_writing.md`。每次 `workflow discuss` 在角色说明之后、阶段模板之前完整加载该文件，使后续阶段材料和产物共同受约束。当前仓库立即使用，未来新安装项目随安装包获得；其他已安装项目不自动覆盖，升级机制另行设计。`workflow` 命令行 stdout 不受此规范约束。
_Avoid_: 为显得专业而使用抽象词, 名词连续堆叠, 优化提升赋能闭环等词代替实际动作, 固定套用先结论后细节, 只写正确方向不写具体内容, 重复同一意思, 空泛开场和收尾, 输出内部推理过程, 把命令行输出纳入文案改造

**First-Principles Writing Check**（第一性原理写作检查）:
输出前在内部确认：用户真正要解决什么、哪些事实已确认或未知、有哪些限制、读者看完需要知道或完成什么、哪些内容与目的无关可删除。写完后检查抽象词是否替代具体动作、专业词能否换成普通话、是否重复、是否有删掉也不影响意思的句子、是否写清对象、条件、动作和结果；不向用户输出完整内部推理过程。
_Avoid_: 只写“请第一性原理思考”却不给检查问题, 把内部推理过程写进回复, 用长篇思考代替清楚结论

**Adversarial Clarity Review**（对抗性清晰审查）:
写完后站在不了解背景且会主动挑错的读者角度，逐项追问“具体是什么、谁负责、什么条件、做什么、结果是什么、依据是什么”，尝试找出另一种解释，并删除不增加信息的句子。正式文档执行完整审查；AI 聊天发送前快速检查抽象词、歧义、重复和废话。不使用关键词封禁假装自动判断写作质量；代码只检查全局规范已安装并在每个阶段加载，AI 必须自查，用户确认门禁负责最后判断。
_Avoid_: 把对抗性审查写成一句口号, 只查错别字不查意思, 为挑错而增加更多空话, 用禁词列表代替内容判断, 声称代码能自动判断文章是否直白


**Optional Spike** (可选穿刺):
从零做、改产品和修 bug 路径上的不确定性验证 Stage。修 bug 时位于 `reproduce` 和 `fix_plan` 之间；它不重新复现已经确认的缺陷，也不要求先有完整修复方案，只验证修复所需但当前仍不知道的真实行为、返回内容、兼容性、性能或其他具体事实。spike 默认在路径中。AI 调查并与用户讨论后，只有用户明确决定本次没有需要实际验证的不确定性，才通过 `workflow gate spike --skip` 跳过：state 记 skipped、journal 记跳过并推进下一 Stage；不要求临时代码、穿刺清单或结论文档。AI 认为没有值得穿刺的不确定性时只能说明调查结果并建议跳过，最终决定仍由用户作出。不能靠 AI 自觉删 stage；不在 start 时默认从路径抹掉 spike。
_Avoid_: 固定必做无法跳过, start --no-spike 作为唯一跳过方式, AI 认为不需要就自行跳过, 未与用户讨论就调用 skip

**Bug Reproduction Gate**（缺陷复现门禁）:
`bugfix` 在进入穿刺前必须先用真实环境和真实输入复现缺陷并确认根因。用户确认讨论完成时记录 `bug/index.md` 和已有缺陷记录的内容哈希；门2要求索引和至少一份本次缺陷记录发生变化，并检查当前工作流编号、索引链接、真实复现条件、实际与期望结果、根因说明、根因位置和根因证据。固定状态必须是“已复现”和“已确认”。程序只能检查结构与文件变化，用户在门3核对证据真实性。
_Avoid_: 任意 Markdown 文件冒充缺陷记录, 只写错误现象不确认根因, 用自造数据代替真实场景, 不更新 bug/index.md, 程序声称能够判断证据真伪

**Spike Risk Scope**（穿刺风险范围）:
`spike` 不限于逻辑原型和 UI 原型。凡是必须通过临时代码、实际运行或测量才能确认的技术不确定性都可进入穿刺，例如逻辑与状态模型、UI 方案、第三方库或 API 可用性、性能、构建与部署、平台兼容、文件格式、协议和关键算法。一次穿刺只处理一个明确不确定性；为了确认同一个不确定性，可以使用多个相关请求、样本、场景或观察项。若没有需要用实际证据确认的不确定性，则走 `workflow gate spike --skip`。
_Avoid_: 把 spike 限制成逻辑/UI 两类, 按功能名称笼统穿刺, 一个穿刺混入多个互不相关的不确定性, 已能从代码或文档确认仍写原型

**Spike Uncertainty**（穿刺不确定性）:
产品真实场景中当前缺少事实证据、无法直接确定，并且不同结果会改变代码设计、技术选择、实施计划或验收方式的事项。穿刺的目的不是证明预先选定的方案正确，而是通过真实场景中的可观察结果，把不确定性变成已确认事实、明确限制或仍无法确认的结论。执行时可以把一个不确定性拆成多个可验证问句，但这些问句必须共同服务同一个后续决定。
_Avoid_: 把普通待办称为不确定性, 结论不会影响任何决定仍做穿刺, 只验证支持预设答案的样本

**Spike Candidate Selection**（穿刺候选识别与选择）:
AI 先读取已经确认的产品设计、代码设计、相关代码、现有测试、日志、依赖文档与已有运行结果，主动找出缺少实际证据的技术不确定性，不要求用户凭空列出“哪些功能要穿刺”。改产品和修 bug 时必须查看相关代码；项目具备运行条件时，必须先运行与当前问题有关的现有功能。现有代码或实际运行已经能回答的事项不是穿刺不确定性；无法运行时必须说明缺少什么条件，以及因此仍无法确认什么。从零开发且代码尚不存在时不强制运行。每个候选必须先用直白话说明它来自哪个真实场景，再说明已知事实、仍不确定什么、验证结果用于决定什么、准备取得什么证据、预计成本或风险，并给出建议；随后可附产品设计、代码设计或明确系统约束的链接作为依据。无法对应真实场景的内容不能进入穿刺清单。AI 必须在门1前比较候选的真实场景、不确定内容、所需证据和结果用途：这些内容实质相同或一个只是另一个的验证问句时，合并成一个穿刺项；后一项必须等前一项结果出来才知道是否需要时，只先讨论和选择当前可执行项。多个候选可以先概览，但每次只让用户决定一项。AI 认为没有值得穿刺的不确定性时，也必须说明检查了什么、为什么这样判断，并和用户讨论；用户决定执行哪些候选，或者决定本次全部跳过。
_Avoid_: 把没有调查误当成不确定性, 有代码不查看, 具备条件却不运行现有功能, 让用户先列技术风险, 按功能名代替不确定性, 不说明真实场景, 把重复问句拆成多个穿刺项, 把有条件的后续验证提前列为必做项, 一次要求用户决定多个候选, 把 AI 建议当成最终决定, AI 未经用户决定自行执行或跳过

**Spike Candidate Explanation**（穿刺候选说明）:
门1前，AI 对每个候选使用同一组直白问题说明：候选名称；真实场景；已经确认的事实；当前不确定的具体行为、内容或限制；为什么现有事实不能回答、必须实际验证；准备使用什么真实请求、文件、平台、数据规模或操作路径验证；验证结果用于决定什么；执行是否会修改外部数据、产生费用或带来其他实际影响；AI 是否建议执行。候选尚未被用户选择时不分配 `SP-001` 这类正式穿刺项编号，用户确认执行后才写入清单并编号。
_Avoid_: 候选只写一个技术名词, 用“验证可行性”代替具体未知内容, 不说明为什么必须运行, 未经用户选择就当成正式穿刺项, 不说明真实调用的实际影响

**Spike Validation Method**（穿刺验证方法）:
每次穿刺选择能确认当前不确定性的最小方法，不强制编写临时代码。现有命令、项目现有程序、第三方工具或受控接口调用能够取得证据时直接使用；只有现有手段不能暴露所需结果时，才编写最小脚本、原型、性能测量程序或其他临时验证代码。穿刺产生的临时代码、真实场景样本和原始输出统一放在 `.workflow_loop/spike_tmp/`。无论使用哪种方法，都必须记录实际命令、输入或样本、环境与版本、观察结果和失败信息；没有实际证据不能下结论。
_Avoid_: 每次穿刺都机械写代码, 已有命令能验证仍造脚本, 临时文件散落到正式源码, 只写预期结果不实际运行, 没有证据直接下结论

**Spike Real Scenario Evidence**（穿刺真实场景证据）:
`spike` 只穿刺真实场景中的不确定性。验证必须使用产品实际会遇到的接口、输入文件、运行平台、数据规模、操作路径或故障条件。可以编写最小驱动程序观察真实场景，但不能用自己编造的接口响应、模拟数据、手工构造的理想文件或脱离目标环境的玩具案例证明真实行为。真实场景暂时无法取得时，结论只能是 `仍未确认`；不能为了完成 Stage 用假数据替代。对真实数据做脱敏或裁剪时，必须确认没有改变本次要验证的格式、规模、结构或故障特征。穿刺定义不按生产环境或测试环境分类，环境安全属于另外的执行约束，不用它冲淡“真实场景”要求。
_Avoid_: mock 响应冒充真实接口, 自造 PDF 冒充实际文档, 小数据结果推断真实规模性能, 无真实场景仍写已确认, 脱敏后破坏关键特征却继续使用, 用生产或测试环境争论代替判断场景是否真实

**Spike External Side Effects**（穿刺外部副作用）:
用户选择执行某个穿刺项，只表示同意验证该不确定性，不自动表示同意扣费、发送内容、创建或修改外部数据、删除数据等实际操作。只读验证可以在穿刺项确认后执行；存在外部副作用的步骤必须在执行前再次说明操作对象、实际影响、预计费用和能否撤销，并取得用户明确确认。密钥、令牌、密码和会话信息不得写入穿刺文档、临时文件或保留的命令输出。用户不同意执行且没有其他真实验证方法时，结论只能是“仍未确认”。
_Avoid_: 把选择穿刺项当成授权真实扣费或删除, 不说明副作用直接调用接口, 把凭据写入结论文档, 用户拒绝后用假响应代替真实验证

**Spike Validation Preparation**（穿刺执行前准备）:
执行前只要求写清当前不确定性、它影响的后续决定、准备验证的范围、来自真实场景的输入或样本、观察方法，以及取得哪些类型的证据后可以停止。因为穿刺正是为了发现未知结果，不要求预先枚举接口字段、解析内容或所有可能结果。只有产品设计已经给出明确指标时，才提前写判断线，例如处理时间上限或内存上限。真实观察结果、限制和最终设计决定必须在实际运行后填写。
_Avoid_: 未运行就预测真实输出, 强制枚举未知结果, 没有验证范围就随意试验, 结果出来后隐去原始观察只写结论

**Spike Evidence Retention**（穿刺证据保留）:
用户确认穿刺结论并通过 `workflow gate spike --confirmed` 后，删除 `.workflow_loop/spike_tmp/` 中的临时代码、样本和原始输出，保留 `spec/spike_index.md`、`spec/spike_<english-name>.md` 以及按穿刺结论更新后的产品设计和代码设计文档。结论文档必须记录实际命令、工具与依赖版本、输入或样本说明（不能保留原文件时记录类型、大小或哈希）、关键原始输出或测量数据、失败信息、限制、结论及其对产品设计、代码设计、实施计划或验收方式的影响。某个样本或验证逻辑需要成为正式测试资产时，只在后续 `impl` 阶段经确认后放入正式测试目录，不从 `spike_tmp` 直接混入生产代码。
_Avoid_: 删除临时内容后只剩无证据结论, 把大段无法检查的原始输出全部塞进结论文档, spike 阶段直接提交正式测试资产, 未经确认把原型代码留在 main

**Spike Completion Result**（穿刺完成结果）:
穿刺完成不要求原方案验证成功，而要求证据已经足以支持后续决定，或者剩余风险、后续处理阶段和检查内容已经写清并等待用户决定。结论分为三类：`已确认`，证据足以直接作出决定；`限制已确认`，确认原方案不可行或只能部分满足要求，但可以据此换方案或收缩范围；`仍未确认`，证据不足。结果状态只说明证据确认到了什么，“是否阻塞后续”单独说明当前能否进入计划阶段。无论结果状态是哪一类，只要仍然阻塞后续，门2都不能通过；必须继续验证，或者由用户决定怎样调整产品、技术方案或范围并更新相关文档。`仍未确认`但不阻塞时，必须记录具体剩余风险和后续检查阶段；用户是否接受由门3确认，不在文档中提前代替用户决定。
_Avoid_: 只有正面结果才算完成, 原方案失败就不记录, 已确认限制仍阻塞却直接推进, 用“以后再看”代替具体风险承担决定, 把证据状态误当成是否可以继续

**Spike Document Granularity**（穿刺文档粒度）:
一个会影响后续决定的不确定性对应一份 `spec/spike_<english-name>.md`，文件名使用小写英文和下划线，正文使用中文。为了确认同一个不确定性而使用的多个请求、样本、场景和验证问句写在同一份文档中；多个互不相关的不确定性分别建文档。需要临时代码或文件时，放入对应的 `.workflow_loop/spike_tmp/<english-name>/` 子目录，便于单独重做和清理。
_Avoid_: 一份文档混写多个无关不确定性, 按每个样本拆文档, 多项穿刺共用无边界临时目录, 中文或含糊临时文件名

**Spike Index Document**（穿刺清单）:
正常执行 spike 时生成 `spec/spike_index.md`，同时作为用户确认后的执行清单和最终结果总表。清单不用包含长句的十列表格，改为一个穿刺项一个固定段落：二级标题写编号和名称，下面依次写真实场景、要验证的不确定性、验证结果用于决定什么、结论文档、穿刺状态、是否阻塞后续、产品设计影响、代码设计影响和后续处理阶段。文件名使用的英文标识不单独展示，由 AI 根据不确定性名称生成，并通过结论文档链接体现。清单中的“穿刺状态”表示项目进度，允许“待验证｜已确认｜限制已确认｜仍未确认”；结论文档中的“结果状态”只表示实际结论，允许“已确认｜限制已确认｜仍未确认”，不包含“待验证”。门1后先把全部已选项目的穿刺状态写成“待验证”，完成后再按结论文档回填结果状态；不增加“已取消”。AI 提出但用户没有选择的候选不写入清单，也不要求结论文档。`SpikeStage.code_validate()` 不能再以“存在任意一份 spike 文档”作为通过条件，必须检查清单中的每一项都有真实结论文档和明确状态，清单中不存在“待验证”，并拒绝任何仍然阻塞后续的项目。用户一项都不选择并明确确认跳过时，执行 `workflow gate spike --skip`，不生成清单和结论文档。
_Avoid_: 把 AI 候选自动写入清单, 记录用户未选择的候选, 只完成一项就冒充全部完成, 清单链接不存在, 结果状态为空, skip 路径仍要求空清单

**Spike Run Binding**（穿刺文档绑定当前工作流）:
`spec/spike_index.md` 必须记录当前工作流编号，每份穿刺结论文档必须同时记录相同的工作流编号和清单中的穿刺项编号（如 `SP-001`）。门2只接受工作流编号与当前 Run 一致、穿刺项编号能在当前清单中找到的文档；旧工作流留下的穿刺文件不计入本次完成结果。
_Avoid_: 用旧穿刺文档通过当前门禁, 清单和详情属于不同工作流, 结论文档没有对应清单项, 仅凭文件名前缀判断归属

**Spike Gate Meaning**（穿刺门禁含义）:
门1前，AI 完成事实调查、候选说明、语义重复审查和依赖关系梳理，用户逐项决定是否执行；AI 汇总最终选择，用户确认清单完整后才调用 `workflow gate spike --discuss-done`。语义重复审查是 AI 的讨论责任，程序门禁只能检查编号、链接、必填字段和结果完整性，不能声称自动判断两个候选是否在验证同一件事。门1后生成 `spike_index.md` 并执行清单中的验证。执行中发现新的不确定性，或前置结果表明原先未选择的后续候选现在需要执行时，AI 必须先说明真实场景、结果用途和验证方法，由用户决定是否加入，不能自动扩展范围。门2检查清单中每项都有对应结论文档和可接受结果；门3由用户统一检查全部穿刺结果并确认，随后清理 `spike_tmp`。
_Avoid_: 声称代码能判断语义重复, 门1前未确认清单, AI 执行中自动增加穿刺项, 门2只检查任意文件, 门3只确认部分结果, 用户确认前清理临时证据

**Spike Execution Order**（多个穿刺项目的执行顺序）:
门1前发现两个候选存在先后依赖时，依赖前置结果才能判断是否需要的候选不提前加入执行清单；先执行前置穿刺，结果出来后再由用户决定是否新增后续穿刺项。已经确认进入清单的项目应当互不重复，并且当前都确实需要执行；互不影响的项目可以一起执行。每完成一项立即填写对应结论文档，但不要求用户逐项确认。全部项目完成后，用户在门3统一确认穿刺结果和更新后的设计文档。
_Avoid_: 把重复内容拆成多个项目, 把有条件的后续候选提前列为必做项, 每做一步都让用户重复确认, AI 自行增加穿刺项目

**Spike Document Template**（穿刺文档模板）:
`spec/spike_index.md` 使用一个穿刺项一个固定段落的方式记录当前清单和结果，不使用承载长句的大型横向表格。每份 `spec/spike_<english-name>.md` 固定包含八部分：真实场景与不确定性；验证结果用于决定什么；已知事实与验证范围；验证方法；实际执行记录；实际观察结果；结论；对后续工作的影响。前四部分在实际运行前确定，但不预测未知结果；后四部分只能根据真实执行填写。结论不能只写状态名，必须说明确认了什么、限制是什么或为什么仍未确认。
_Avoid_: 用过宽表格挤压长句, 清单没有真实场景和结果用途, 执行前编造实际结果, 只写最终结论不写命令和证据, 结论状态没有具体内容, 不说明后续设计怎样变化

**Spike Decision Fields**（穿刺决定字段）:
穿刺文档正文可以按真实情况自由说明，但决定工作流能否继续的内容必须使用固定字段。第七部分“结论”固定填写“结果状态：已确认｜限制已确认｜仍未确认”“是否阻塞后续：是｜否”“已确认内容”“仍未确认内容”；第八部分“对后续工作的影响”固定填写“产品设计影响：需要修改｜无需修改”“产品设计更新位置”“代码设计影响：需要修改｜无需修改”“代码设计更新位置”“剩余风险”“后续处理阶段：无｜acceptance_plan｜test_plan｜plan｜fix_plan｜topic_execution｜regression_test｜overall_acceptance｜update_code_design”“后续需要检查什么”。其中 `plan` 用于从零开发和修改产品，`fix_plan` 用于修 bug。门2必须拒绝非法状态和任何“是否阻塞后续：是”的项目；结果为“仍未确认”时，剩余风险、后续处理阶段和后续需要检查什么都不能为空；所有标记为“需要修改”的产品设计和代码设计文档必须已经变化。固定字段只用于程序判断，不能代替对真实证据和具体结论的说明，门3由用户最终确认是否接受所记录的剩余风险。
_Avoid_: 让门禁猜测自由文本含义, 用“基本完成”等自定义状态, 未确认事项不写剩余风险和后续检查内容, 穿刺推翻产品要求却只改代码设计, 只填固定字段而不解释实际结论

**Bugfix Spike Product Boundary Gate**（修 bug 穿刺的产品边界门禁）:
当前工作意图为 `bugfix` 时，门2必须拒绝任何写有“产品设计影响：需要修改”的穿刺项，并明确提示当前结果不能继续按修 bug 流程推进，应结束当前 Run 后启动 `product_change`。如果用户选择保持原产品行为的其他修复方案，必须重新写清方案与证据，并把产品设计影响写为“无需修改”后才能继续。程序只检查明确字段，不自行判断某段自由文字是否暗中改变产品行为，门3仍由用户审查实际内容。
_Avoid_: bugfix 门禁允许修改产品行为, AI 只改字段不改实际方案, 程序声称能从自由文字判断产品语义, 需要改产品仍推进 fix_plan

**Spike Prompt Split**（穿刺模板与规范职责）:
`Template_Repository/spike/spike.md` 只定义最终产物结构和内容质量，包括 `spec/spike_index.md`、每份 `spec/spike_<english-name>.md`、结果状态、代码设计影响字段和完成前文档检查；不写 AI 的调查与执行顺序。`Standardized_Repository/spike/spike.md` 定义 AI 怎样读取产品与代码设计、识别真实场景不确定性、逐项让用户选择、选择最小验证方法、按需使用 prototype 方法、执行并记录真实证据、形成结论、更新代码设计、经过门禁和清理临时内容。prototype 内容改写后进入流程规范，不直接作为运行时外部依赖，也不放进文档模板。
_Avoid_: 模板写成访谈脚本, 规范只列文档目录, 直接引用开发者本机 prototype 路径, 两份文件重复整套规则

**Prototype Validation Method**（原型验证方法）:
用最小的抛弃式代码确认一个明确不确定性，是 `spike` 可选择的验证方法之一，不等于整个 `spike` 流程。Workflow Loop 可以吸收 prototype 技能中“目标明确、使用现有技术栈、暴露关键状态”等方法，但不能吸收“默认不接真实数据”的规则：原型代码可以是临时和最小的，验证对象仍必须来自真实场景，包括真实接口、真实文件、真实数据特征、目标平台或实际数据规模；敏感数据可以脱敏，但不能改变本次要验证的结构和特征。临时代码统一放在 `.workflow_loop/spike_tmp/`，不修改生产代码，不在运行时依赖本机 prototype 技能目录。执行方式不强制压成一条命令，必须记录最少且可以重复执行的完整命令步骤。拿不到真实场景证据时，结论只能是“仍未确认”。
_Avoid_: 原样复用外部 skill 代替 spike 提示词, 用自造数据验证真实行为, 为满足一条命令省略必要步骤, 把原型代码放进正式模块, 验证完立即改生产代码, 让已安装项目依赖开发者本机绝对路径

**Spike Method Selection**（穿刺方法选择）:
穿刺不强制先把不确定性分类。逻辑原型、UI 原型、真实接口调用、格式解析、构建运行、平台验证、性能测量和第三方能力探测都只是可选方法示例。AI 根据真实场景中的不确定性选择最小且能取得真实证据的方法；可以组合多个紧密相关的方法确认同一个不确定性，但不能为了套分类增加无关验证。prototype 技能中的 LOGIC/UI 方法只在对应场景下使用，不成为所有穿刺的固定分支。
_Avoid_: 所有穿刺先强制贴类型标签, 每类都执行一遍, 为迁就 prototype 只支持逻辑和 UI, 方法比不确定性本身更复杂

**Spike Code Boundary**（穿刺代码边界）:
spike 只验证真实场景中的不确定性，不修改正式源代码、正式页面、正式配置或数据库迁移。临时代码可以读取、导入和运行现有代码，也可以在 `spike_tmp` 的隔离副本中试验，但不能直接接入当前正式工作区。穿刺结果必须作为后续代码设计和实施计划的事实依据；后续正式代码可以参考已经验证的接口形状、状态逻辑、算法约束和失败条件，但不能把没有生产级错误处理、测试和边界设计的临时验证代码直接照搬进生产。
_Avoid_: spike 阶段顺手实施正式功能, 原型可运行就直接复制进生产, 穿刺结论不进入代码设计和计划, 正式代码忽略已确认限制重新猜测

**Spike Architecture Feedback**（穿刺结果回写代码设计）:
正常执行 spike 时，全部真实场景验证完成后、进入 `plan` 或 `fix_plan` 前，必须让 `spec/architecture_code_design.md` 吸收穿刺结论。穿刺本身只负责取得真实证据；证据确认后，由用户决定采用什么实现或修复办法。穿刺确认了接口形状、数据结构、模块边界、算法约束、性能限制、平台限制或异常行为，并因此改变代码设计时，按真实证据写清受影响的模块、文件、函数、调用过程、数据转换和异常处理；修 bug 时也不能把这一步推迟到已经开始实施之后。实现或修复办法仍未决定时视为阻塞，不能进入计划；某项结论不影响代码设计时，在结论文档中明确写“代码设计无需修改”。门3由用户一起确认穿刺结论和更新后的代码设计。`workflow gate spike --skip` 跳过时不修改代码设计。
_Avoid_: 穿刺后仍保留验证前猜测, 把结论只放 spike 文档不更新架构, 未决定怎样实现或修复就进入计划, 没有影响也不明确说明, spike 阶段直接修改生产代码

**Spike Product Design Feedback**（穿刺结果回写产品设计）:
从零做或改产品时，穿刺结果可能证明原有产品行为、功能范围或产品规则在真实场景中无法成立。此时 AI 不能只修改代码设计，也不能自行改变产品要求；必须说明真实证据、冲突位置和可选处理方式，由用户决定是否调整产品设计。用户确认调整后，先更新 `spec/product.md` 或对应功能产品文档，再让 `spec/architecture_code_design.md` 与更新后的产品设计保持一致。产品设计仍与穿刺结论冲突时，门2不能通过；仅影响技术实现而不改变用户可见行为和产品规则时，产品设计可以标记为“无需修改”。

修 bug 时，`bugfix` 的前提是原产品行为不变：穿刺只影响修复方法或代码结构时可以更新代码设计并继续；当前方案不可行但仍有保持原产品行为的其他方案时，继续讨论其他修复方案；只有改变产品行为、功能范围或产品规则才能继续时，停止当前修 bug 流程，由用户决定是否改产品。用户决定改产品后，执行 `workflow abort` 结束当前 Run，再以 `workflow start --intent product_change` 启动修改产品流程。AI 不得在修 bug 流程中直接修改产品规则，也不得静默改变工作意图。
_Avoid_: 技术限制出现后静默缩减产品能力, 产品文档和代码设计互相冲突, AI 未经用户确认修改产品规则, 在 bugfix 中偷偷改产品行为, 不影响产品设计却为过门禁随意改文档

**Spike Unified Confirmation**（穿刺结果统一确认）:
穿刺导致产品设计变化时，不退回并重走已经完成的产品设计阶段。用户先根据穿刺证据决定产品行为或范围怎样调整，AI 随后依次更新产品设计和代码设计；门2检查穿刺结论、产品设计和代码设计已经一致，门3由用户一起确认这三部分后再进入计划阶段。用户尚未决定产品调整方式，或者文档之间仍有冲突时，穿刺阶段不能结束。
_Avoid_: 为一次穿刺反馈机械重跑整个产品设计阶段, 只确认穿刺文档不确认被修改的产品与代码设计, 产品调整未决定就进入计划

**Spike Architecture Gate Validation**（穿刺回写架构门禁）:
真正进入 spike 阶段时记录产品设计和代码设计的内容哈希。产品设计范围以 `spec/product.md` 及其功能清单实际链接的功能产品文档为准，不扫描目录中所有 `feature_*.md`，避免把废弃或不属于当前产品的文件算进去；代码设计范围为 `spec/architecture_code_design.md`。旧工作流已经进入 spike 但没有保存入场哈希时，标记基线无法还原，不使用当前文件冒充穿刺开始前的设计；这类旧流程只有全部设计影响为“无需修改”时才能继续，需要证明设计变化时门2失败。`spike_index.md` 和每份结论文档都必须明确产品设计影响和代码设计影响为“需要修改”或“无需修改”，需要修改时写清受影响内容。门2检查全部结论文档和影响字段；只要某类设计有一项需要修改，对应文档的当前哈希必须与进入阶段时不同；全部无需修改时允许对应文件不变。哈希只能证明文件发生变化，不能证明修改语义正确，门3仍由用户检查穿刺结论和更新后的设计文档。
_Avoid_: 需要修改但对应设计文件未变化, 扫描全部功能文件导致旧文档干扰判断, 无影响却为过门禁随意改文件, 用哈希变化声称内容正确, 用户只看 spike 文档不看更新后的设计

**System Location** (系统位置):
workflow_loop 是独立系统（含 CLI），代码安装在全局或固定系统路径；目标项目是被管理仓库，项目内通常没有 `workflow.py`。用户在目标项目根执行一次官方安装脚本，脚本先安装或复用全局命令，再把运行骨架安装进当前项目；之后日常命令由全局 CLI 对该项目操作。
_Avoid_: 要求用户在项目里先放 workflow.py, 让用户分别执行全局命令安装和项目接入两步

**Global CLI** (全局命令行):
workflow_loop 安装后提供的机器级命令，用户命令名 `workflow`（发行包名 `workflow-loop`）。`start` / `discuss` / `gate` / `status` / `done` / `abort` 均通过全局 CLI 作用于当前目标项目。项目安装不是 `workflow attach` 子命令，而是由官方安装脚本在首次使用时完成。
_Avoid_: 仅项目内 python3 workflow.py, 保留面向用户的 attach 子命令, 安装后改用另一套完全不同的入口


**Bootstrap Installer** (一条命令完成安装):
workflow_loop 为 Python 系统。用户在目标项目根只运行一条官方安装脚本命令；脚本内部可用 pipx / uv tool 或等价方式安装全局入口，然后调用包装内的项目安装逻辑完成当前项目安装。**发行包名** `workflow-loop`，**用户命令名** `workflow`，**导入包名** `workflow_loop`。不使用 npx。

同一台电脑给后续项目安装时仍运行同一条官方脚本；所有路径与契约确认通过后，脚本检查 `workflow` 全局命令是否存在，存在则复用，不存在才安装。当前项目已安装时按 Repeat Installation 直接退出，不修改项目文件。
_Avoid_: npx 作为安装/调用方式, 要求用户手动串两条安装命令, 安装前要求项目内已有 workflow, 以目标项目内 python3 workflow.py 为唯一入口

**Package Layout** (安装包布局):
采用标准可安装布局（非仓库根扁平长期形态）：
- 代码与 CLI：`src/workflow_loop/`（引擎、PathComposer、各 Stage、CLI `main`）
- 默认模板/规范资源：`src/workflow_loop/data/Template_Repository/`、`…/data/Standardized_Repository/`（随包装分发，安装当前项目时复制）
- 根目录 `pyproject.toml` 声明 console script：`workflow = "workflow_loop.cli:main"`（模块路径以实现为准，须指向统一入口）
- 官方安装脚本负责引导全局命令安装，并调用包装内的项目安装函数；项目安装函数不是面向用户的 `attach` 命令
- 仓库可仍名 spike；实现入口重做时收进包内，避免全局 CLI 长期绑根目录 `workflow.py`
_Avoid_: 全局安装仍依赖仓库根 workflow.py, 模板只放开发树不进包, 无 console_scripts 仅靠 python -m 临时代替正式入口

**Project Root Resolution** (项目根解析):
安装阶段：官方安装脚本严格把当前终端所在目录作为项目根，先打印绝对路径和待修改对象并等待用户确认，不自动向上猜 `.git`。日常阶段：项目已经安装后，全局 CLI 以当前工作目录为起点向上查找 `.workflow_loop/`，因此可以在项目子目录调用。
_Avoid_: 安装时静默猜项目根, 安装前不展示目标路径, 日常每次必须传绝对项目路径, 仅靠环境变量定位项目根
**Bootstrap Paradox** (首次安装悖论，已消除方向):
安装前还没有 `workflow` 命令，因此不能要求用户先执行 `workflow install` 或项目内 `workflow.py`。官方安装脚本作为唯一首次入口：先完成项目路径确认；用户未取消时，再安装或复用全局命令，并在同一次运行中直接写入项目最小代理契约和安装骨架。
_Avoid_: 项目内本地 workflow.py 作为首次入口, 安装前调用尚不存在的 workflow 命令

**Minimal Agent Contract** (最小代理契约):
`AGENTS.md`（唯一代理契约文件名）只保留两类必须从第一条回复开始生效的规则：一是 workflow 入口，要求用户提出需求后由智能体调用全局 `workflow start`，之后严格跟随 stdout 的下一步；二是核心表达要求，要求先弄清实际问题、事实、限制和目标，用直白话写清对象、条件、动作和结果，并删除空泛与重复内容。用户不需要知道或手动执行 `workflow start`。契约不展开 stage 序列、门禁细节、写作反例和完整审查清单；这些内容由 `discuss` 在对应 Stage 加载。
_Avoid_: 把完整流程写进 AGENTS.md, 因改全局 CLI 而取消提示词加载

**From Scratch Clean Start** (从零做清场):
选择 `from_scratch` 表示真的重新做，不能沿用旧设计产物凑合。初始化 `from_scratch` Run 时，无论是否发现并删除旧设计产物，都把 `.workflow_loop/project.json` 的 `project_design_initialized` 置为 `false`；之后固定走：`spec` → `code_design`（初步，不可跳过）→ … → 末段详细架构。`spec` 与 `code_design` 均经用户确认后再写回 `true`。从零做不进入存量项目的 `project_design_init`。

**Clean Scope** (清场范围):
- **整目录删除**：项目根下 `spec/`、`plan/`、`acceptance/`、`qa/`、`impl/`、`bug/` 只要含有文件，就删除命中的整个目录及全部内容。这些目录中即使放了非 workflow 文件，也会一起删除。
- **不删除目录外内容**：`.workflow_loop/Template_Repository/` 与 `.workflow_loop/Standardized_Repository/` 全部内容（含其中的 `spec/`、`plan/` 等提示词与规范子目录）；`.workflow_loop/project.json` 文件本身（只更新初始化字段）；上述六个目录之外的源代码、`.git` 和项目文件；`.workflow_loop/` 运行时骨架本身。
- **确认**：有可删过程产物时才走清场确认；无则跳过（见 Clean Confirm）。
_Avoid_: 从零做复用旧架构并跳过初步, 删除 Template/Standardized 仓库或其下 stage 子目录, 把模板 spec 当产物删, 默认删除源代码, 静默清场不确认, 无过程产物仍强制 --confirm-clean

**Clean Detect List** (清场监测清单):
`from_scratch` 开工前用**固定路径表**探测「是否有过程产物」，与删除范围同一份约定（方案 A）：
- 监测对象：项目根下 `spec/`、`plan/`、`acceptance/`、`qa/`、`impl/`、`bug/` 中**已存在且含文件**的路径（非空才算有产物；空目录可不触发确认）
- **不监测、不删除**：`.workflow_loop/Template_Repository/**`、`.workflow_loop/Standardized_Repository/**`
- 有命中 → 打印将删清单，需 `--confirm-clean`；全无命中 → 直接开工
清单在代码中集中维护，stdout 与删除共用，避免两套规则。
_Avoid_: 宽扫全仓库 md, 只认 state/journal 漏掉手写 spec, 监测 Template_Repository 下的 spec

**Clean Confirm** (清场确认，两段式):
仅 `from_scratch`。开工前先探测是否存在 Clean Scope 内的过程/设计产物：
1. **无过程产物**：不进入删除流程；`workflow start --intent from_scratch` 直接初始化 Run 并走固定路径（仍受 Active Run Guard 约束）。
2. **有过程产物**：`workflow start --intent from_scratch` 只打印将删清单与说明，**不删、不开 Run**；下一步指示用户同意后执行 `workflow start --intent from_scratch --confirm-clean` 才删除并开工。
清场发生在智能体驱动的日常流程里，不同于用户亲自运行的安装脚本：`start` 不阻塞读 stdin 做 y/n，而是由 stdout 指示智能体询问用户，再用 `--confirm-clean` 表达确认。该参数不能绕过 Active Run Guard（有未完成 Run 仍须先 `done` / `abort`）。不设独立日常 `workflow clean` 作为从零做的主路径。
_Avoid_: 无过程产物仍强制确认, start 内阻塞 y/n, 静默删, --confirm-clean 绕过活跃 Run, 独立 clean 作为 from_scratch 必经主命令

**Design-Time Architecture Update** (设计期改架构):
`product_change` 在 `spec`（产品设计与功能拆分）之后、`acceptance_plan` 之前必须经过 `revise_code_design`：按变更后的产品设计改架构图。主题执行、最终全量回归和整体验收完成后另走 `update_code_design` 做详细落地。两次强制，名称分开以免 state 主键冲突。
_Avoid_: 改产品只在末尾改一次架构, 路径上两个同名 update_code_design, 改设计却不改架构图

**Bugfix Architecture Update** (修 bug 时的架构):
`bugfix` 在 `topic_execution`、`regression_test` 与 `overall_acceptance` 通过之后必须经过 `update_code_design`。若 fix_plan/实施判定不涉及结构变更，仍须走该 Stage，并在门禁中显式确认「无结构变化」；涉及结构则必须改架构图。不可因“只是小 bug”省略测试、验收或架构 Stage。
_Avoid_: 修 bug 默认跳过架构收尾, 无结构变化就不跑 stage

**Code Design Stage** (`code_design`):
只用于 `from_scratch`（从零创建项目）的前段初步架构设计。它读取已经确认的产品总说明和功能文档，设计准备采用的模块、职责、接口、依赖、主要调用过程、数据处理位置和测试位置，并写入 `spec/architecture_code_design.md`。它描述“准备怎样实现”，不承担查看已有代码和运行项目反推当前架构的任务。架构文档结构可以与存量项目共用，但流程规范必须按实际情况分支：从零设计以已确认的产品设计和用户决定为依据，不强制运行尚不存在的项目；存量项目反推必须查看代码，具备安全运行条件时必须运行，并用实际表现校准代码理解。
_Avoid_: 把 code_design 写成已有代码反推流程, 用“场景B”等未定义名称代替实际适用条件, 产品设计未确认就开始搭架构

**Code Design Document Template**（代码设计文档模板）:
规定 `spec/architecture_code_design.md` 的内容结构。文档面向项目维护者，固定从产品设计出发，依次说明产品概览、产品怎样决定架构、代码分层、架构关键节点、每个产品功能的完整代码过程、多个功能共用的代码，以及产品设计与代码实现的差异。已有实现使用真实代码位置；从零设计使用明确标记为“计划”的代码位置。每个程序处理节点必须落到文件、类、函数、类型或接口，并说明具体判断、调用、状态或数据结果、失败结果和验证位置。
_Avoid_: 把架构文档写成目录清单, 只列模块或函数名不写逻辑, 产品功能与代码设计互不对应, 把计划代码写成已有实现

**Architecture Layer**（代码架构层）:
一组承担同类代码职责、具有明确调用边界和依赖方向的代码。每层必须说明它承接的产品职责、负责与不负责的内容、关键代码位置、对外约定、上下层依赖和验证位置。架构图只表达分层和依赖，不表达某个功能的执行顺序。
_Avoid_: 按目录机械分层, 用“表现层/业务层/数据层”等名称代替实际职责, 在架构图中混画执行顺序

**Architecture Key Node**（架构关键节点）:
多个功能共同经过，或者行为改变会影响产品规则、阶段推进、状态一致性或外部交互的代码位置。它必须写清产品责任、代码位置、上游触发、关键处理、下游调用、状态和数据、失败结果及验证位置。普通工具函数不属于关键节点。
_Avoid_: 把所有函数都列成关键节点, 只写节点名称不写实际代码和逻辑

**Feature Code Flow**（功能代码过程）:
一个产品功能中某个明确场景的完整实现过程，从用户动作或系统事件开始，到用户或调用方得到明确结果结束。流程图中的每个程序节点直接标出文件、函数或类型和关键处理；图后逐步说明输入、判断、调用、状态或数据结果、失败结果和验证。一个场景可以多次进入程序，不预设只有一个代码入口。
_Avoid_: 只有角色交互没有代码映射, 把多个场景和函数内部流程混在同一张图, 用孤立的“状态变化”字段代替发生步骤

**Code Evidence Status**（代码证据状态）:
已有项目的关键结论区分为运行确认、测试确认、代码确认、文档或用户确认、未确认和冲突。代码确认表示已经阅读真实调用链和关键逻辑，但不等于已经实际运行。无法运行时必须说明原因和未验证范围。
_Avoid_: 读过代码就写成运行验证, 隐藏或不可达代码直接写成正式产品功能, 证据冲突仍选一个写成事实

**Code Design Process Standard**（代码设计流程规范）:
规定 AI 怎样从已确认产品设计形成代码覆盖清单，推导架构层和关键节点，逐个功能设计完整代码过程，落实产品规则与异常，设计共享代码和验证方式，并在用户确认后生成正式文档。`code_design` 形成计划设计；`project_design_init` 还必须遵守存量项目调查和运行规范。
_Avoid_: 从代码目录开始拼架构, 产品设计未确认就生成文档, 只设计成功路径不落实规则和异常, 不经用户确认直接写正式产物

**Revise Code Design Stage** (`revise_code_design`):
改产品路径上、`spec` 产品设计与功能拆分之后的设计期改架构 Stage。用户确认讨论完成时记录 `spec/architecture_code_design.md` 的内容哈希，门2要求文件相对该基线发生变化。与末段 `update_code_design`（详细落地）名称分离，避免同一 Run 内 stage 名冲突。
_Avoid_: 与 update_code_design 共用同一 stage 名当主键

**Project Design Init Stage** (`project_design_init`):
首次处理已有代码项目时，为 `product_change` / `bugfix` 共享的前置 Stage，中文名“项目设计架构初始化”。角色为“存量产品与架构分析师”。它必须查看现有代码；具备安全运行条件时必须运行项目，用真实表现校准代码理解；无法运行时写清原因和未确认内容。根据现有代码及可运行行为一次建立 `spec/product.md`、多个 `spec/feature_<english-name>.md`、`spec/architecture_code_design.md`，并生成 `spec/project_design_init_evidence.md` 记录实际检查的代码路径、运行条件、命令、结果和文档校准结论。门2要求产品设计、代码设计和调查证据都相对讨论完成时的基线发生变化，并检查证据中的代码路径真实存在。门3确认后写 `project_design_initialized=true` 与 `architecture.preliminary_done=true`。程序不能证明证据没有伪造，用户必须在门3核对。该 Stage 完成前作废不得写 true。
_Avoid_: 只生成 architecture_code_design.md, 拆成彼此可能不一致的产品反推和架构反推两轮, 用旧文档存在冒充本次初始化完成, 把从零设计提示词当成代码反推提示词

**Product Spec Stage** (`spec`):
统一负责“产品设计 + 功能拆分”。角色为产品设计师；加载 `.workflow_loop/Template_Repository/spec/spec.md` 与 `.workflow_loop/Standardized_Repository/spec/spec.md`；产物为 `spec/product.md` 与多个 `spec/feature_<english-name>.md`。`from_scratch` 中负责从零建立；`product_change` 中负责基于现状重新设计，可新增、修改或删除功能文档。用户确认讨论完成时记录相关文件路径与内容哈希，门2比较前后变化。`from_scratch` 要求新建 product.md 且至少新建一个功能文档；`product_change` 要求 product.md 有变化且至少一个功能文档新增、修改或删除。
_Avoid_: 只校验 product.md, 独立生成 requirement_<临时名>.md, 把产品更新与功能拆分拆成两个后续 Stage, 旧功能文件冒充本 Run 产物

**Product Spec Template Prompt**（产品设计模板提示词）:
`.workflow_loop/Template_Repository/spec/spec.md`，是适用于所有产品类型的通用模板，提供可直接生成文件的 `spec/product.md` 完整九章骨架和 `spec/feature_<english-name>.md` 完整六章骨架，并说明每章应该写什么、不写什么、表格字段及无内容时如何标记；它说明“最终文档应是什么”，不承担逐题访谈流程，也不强制所有产品套用数据进入、整理、计算、输出等固定分类。没有相关内容时明确写“暂无”，不得为填满模板编造内容。
_Avoid_: 把模板提示词写成访谈脚本, 只给目录不定义内容质量, 把某类数据产品的处理环节规定成所有产品必用维度

**Product Spec Process Prompt**（产品设计流程提示词）:
`.workflow_loop/Standardized_Repository/spec/spec.md`，定义产品设计阶段如何根据当前产品灵活地逐题讨论需求、检查讨论结果并取得用户确认；它说明“怎样形成最终文档”，不规定固定的需求讨论顺序，也不重复定义模板正文。流程区分四种情况：从零设计从用户需求建立产品；修改已有产品先读取现有文档和代码，只讨论本次新增、修改、删除以及需要保留的旧规则；已有代码但没有产品文档时，必须先查看代码并在安全条件下实际运行，用真实表现校准当前产品；修 bug 时，项目设计未初始化则先建立产品设计，已经初始化则使用现有产品设计，需要改变产品行为时改走修改产品。产品背景和功能设计原因必须来自用户确认或可核实事实，不能从提示词、文件名或代码结构推断历史。任何情况都不让用户重复说明可从环境查明的事实。讨论结束时先总结产品背景、目标、用户、场景、边界、组成、产品通用规则、功能拆分和未决问题，用户明确确认后才生成或修改产品文档。
_Avoid_: 与模板提示词重复抄写全部定义, 强制所有需求按固定步骤讨论, 未总结共识就要求确认, 未确认共识就写产物

**Product Design Phase Scope**（产品设计阶段范围）:
产品设计阶段从调查已知事实和讨论需求开始，经过共同理解确认，最后生成或修改产品设计文档。`spec/product.md` 描述整个产品设计阶段，不只描述最后的文档生成动作。需求讨论属于阶段内的工作过程，不单独生成一份功能文档。
_Avoid_: 把 product.md 缩成文档生成器说明, 把需求讨论单独拆成产品功能, 只写产物不写确认前的产品行为

**Product Design Phase Components**（产品设计阶段组成）:
产品设计阶段由三个用户可理解的部分组成：需求讨论负责查明事实并逐个讨论需要用户决定的问题；共同理解确认负责总结目标、边界、规则和功能拆分并等待用户确认；产品设计文档负责保存产品总说明和各功能文档。提示词文件、全局写作规范和代码模块不作为产品组成列出。
_Avoid_: 把提示词文件当成用户产品组成, 把全局写作规范当成产品部件, 用代码模块代替用户可理解的产品部分

**Product Background**（产品背景）:
产品总说明中的“产品背景”解释这个产品为什么会诞生：在什么现实背景下，谁产生了什么需求，因此需要设计这个产品。只有事实明确时，才说明原有做法为什么不能满足需求。产品背景不要求机械编造“目前存在的问题”，也不写提示词缺陷、模板修改历史、技术方案或开发过程。
_Avoid_: 为填背景虚构问题, 用原有提示词不完整代替产品诞生原因, 在产品背景写修改历史或技术实现

**Background Evidence Rule**（背景依据规则）:
产品背景、产品目标、功能背景和设计原因只能来自用户已经确认的内容，或者能从现有文档、代码和运行结果核实的事实。代码和运行结果可以证明产品现在怎样工作，但不能单独证明产品当初为什么诞生。无法确认的产品历史和设计原因必须继续询问用户或明确标记未确认，不能根据旧提示词、文件名、程序类名或代码结构自行推断。
_Avoid_: 根据实现反推产品诞生原因, 为填章节补写没有依据的历史, 把推测写成已确认事实

**Product Goals**（产品目标）:
产品目标说明产品完成后应达到什么结果，每个目标都必须对应产品背景中的实际需求。AI 怎样提问、调查、运行项目或整理文档属于工作方法，不写成产品目标；“优化体验”“提升效率”“完善能力”等无法判断的概括也不能单独作为目标。
_Avoid_: 把讨论步骤当产品目标, 把调查方法当产品结果, 只写无法判断的方向性口号

**Workflow Loop Product Design Goals**（Workflow Loop 产品设计阶段目标）:
产品设计阶段完成后必须达到三个结果：进入代码设计前，产品背景、目标、用户、场景、边界、规则和功能拆分已经得到用户确认；从零设计、修改已有产品、已有代码但缺少产品文档、修复产品缺陷四种情况都正确使用或形成符合当前实际情况和用户决定的产品设计；产品总说明与功能文档内容完整、互相链接且没有冲突，后续代码设计、开发、测试和验收使用同一份产品依据。
_Avoid_: 用讨论方法代替阶段结果, 只完成聊天不形成确认, 后续阶段各自解释产品要求

**Product Design Actors**（产品设计参与者）:
产品设计阶段的用户角色只有产品提出者和已有项目维护者。AI 产品设计师是负责查明事实、组织讨论、总结确认和生成文档的系统执行角色，不列入用户清单；它只在场景和使用过程中作为执行者出现。
_Avoid_: 把 AI 和人类用户混在同一用户清单, 把系统执行角色写成产品使用者

**Product Design Scenarios**（产品设计场景）:
产品设计阶段覆盖四种使用场景：从零设计产品；修改已有产品；已有代码但缺少产品文档时建立产品设计；修复产品缺陷。修复缺陷时，如果项目设计尚未初始化，先根据现有代码和可运行行为建立产品设计；已经初始化时直接使用已有产品设计，不重新进入产品设计阶段。若修复需要改变产品规则、功能边界或用户可见行为，应改为“修改已有产品”，不能继续按单纯修 bug 处理。“根据共识生成产品文档”是前述场景共同的最后一步，不单独列为场景。
_Avoid_: 遗漏修 bug 场景, 每次修 bug 都重做产品设计, 用 bugfix 绕过产品变化流程, 把共同的文档生成步骤重复列成独立场景

**Workflow Loop Product Design Boundary**（Workflow Loop 产品设计阶段边界）:
支持从零讨论并确认产品设计；根据已有产品文档和代码修改产品设计；已有代码但没有产品文档时，通过查看代码和安全运行建立产品设计；用户确认后生成或修改产品总说明和功能文档；修 bug 时，项目设计未初始化则先建立现有产品设计。不负责代码架构、接口、数据库、实施步骤、测试和验收文档；不在用户确认共同理解前生成产品设计文档；不在未经同意时使用生产账号、真实数据、付费服务或修改外部数据；修 bug 需要改变产品行为或规则时，必须改为修改产品。
_Avoid_: 用模板改造历史充当产品边界, 未确认就生成文档, 未授权运行高风险环境, 用修 bug 绕过产品变更

**Product Design Document Generation Feature**（生成产品设计文档功能）:
Workflow Loop 的产品设计阶段完成后，需要形成统一的产品总说明和功能说明，供后续代码设计、开发、测试和验收使用。用户确认共同理解后，AI 新建或修改 `spec/product.md` 和对应的 `spec/feature_<english-name>.md`。该功能只负责把已确认内容写成产品设计文档，不包含确认前的事实调查和需求讨论。全局写作规范是所有阶段共同遵守的 AI 工作规则，不是本功能的组成部分，也不写入产品通用规则。
_Avoid_: 把需求讨论写进文档生成功能, 把全局写作规范当成产品功能, 在产品通用规则中重复 AI 工作规范

**Product Overview Document**（产品总说明）:
项目根下的 `spec/product.md`，固定包含九章：产品背景与目标、术语、用户与场景、产品边界、产品组成与主要流程、产品通用规则、产品功能、相关文档、修改记录。其中“产品组成与主要流程”只说明产品各部分的关系和用户在功能间怎样流转，不写代码模块、接口或数据库结构；“产品功能”只放功能名称、一句话说明、对应场景和详细功能文档链接。“产品边界”单独说明整个产品支持和不支持什么，不代替各功能文档中的“功能边界”。每个功能的全部规则和细节放在独立功能文档中。“相关文档”可链接代码设计文档，不链接尚未生成或持续变化的开发计划。“修改记录”按 Workflow Run 记录本次用户需求、修改类型、整体设计变化和受影响功能，用于识别本次需求改变了什么，不重复功能文档中的具体规则全文。
_Avoid_: 把所有功能细节都堆进 product.md, 只有功能名没有功能文档链接, 把产品组成写成技术架构, 链接活跃开发计划, 把施工步骤写进产品总说明

**Product Terminology**（产品术语）:
产品总说明中的独立章节，只解释容易歧义或在本产品中有特定含义的词；产品背景与目标不夹带术语定义，普通常用词不收入术语表。提示词文件名、规范文件名和代码标识属于内部实现名称，不作为产品术语。当前 Workflow Loop 产品设计阶段保留“产品总说明”“功能说明文档”“产品通用规则”“运行校准”，并增加“共同理解”。
_Avoid_: 与产品背景混成一章, 收录无需解释的普通词, 把内部提示词名称当产品术语, 同一词给出多个冲突含义

**Shared Product Understanding**（共同理解）:
用户已经明确确认的产品背景、目标、用户、场景、边界、规则和功能拆分。AI 的临时总结、尚未回答的问题和只从代码推测出的内容不属于共同理解；只有形成共同理解后，才能生成或修改产品设计文档。
_Avoid_: 把 AI 单方面总结当用户确认, 未决问题仍存在就生成文档, 把推测当共同理解

**Product Common Rules**（产品通用规则）:
产品总说明中记录对整个产品或多个功能共同生效的用户可见行为，例如统一权限、删除确认、时间显示或共同状态规则；具体内容由各项目决定。AI 怎样提问、调查和组织需求讨论属于产品设计流程规范；AI 怎样使用直白话和执行对抗性审查属于全局写作规范，这两类工作方法都不写成产品通用规则。当前 Workflow Loop 产品设计阶段保留“用户确认后才能生成文档”“高风险运行前取得用户同意”“无法确认的内容不得编造”等产品行为；“一次只讨论一个决定”“事实先查明”留在流程规范；“使用直白话”“对抗性审查”留在全局写作规范。
_Avoid_: 称为全局规则导致与 AI 工作规范混淆, 把讨论方法或写作要求当产品规则, 把某个项目的产品规则写成所有项目强制规范, 在每份功能文档重复同一规则

**Feature Specification Document**（功能说明文档）:
项目根下的 `spec/feature_<english-name>.md`，其中 `<english-name>` 使用小写英文单词并以下划线连接，文件正文继续使用中文，文档一级标题固定为 `# 【功能】<功能名称>`，`spec/product.md` 中的功能名称和链接文字也使用中文。代码校验只接受 `feature_*.md`，不兼容旧的 `功能*.md` 命名；已有中文文件必须删除或重命名。每个文件只说明一个功能的用户可见设计，固定包含“背景、场景、功能边界、规则、使用过程、异常情况、修改记录”七部分；由 `spec/product.md` 链接进入，不写程序类、接口、数据库、模块划分等技术实现。“使用过程”若没有用户操作，则写系统在什么条件下自动执行以及产生什么结果。“修改记录”只写当前 Workflow Run 对本功能新增、修改或删除的具体产品行为，不重复产品总说明中的整体摘要。
_Avoid_: 继续接受 功能*.md, 两套功能文件命名并存, 多个无关功能写在同一文件, 重复整份产品总说明, 缺少 product.md 入口, 混入代码设计或施工步骤, 产品总说明与功能文档的修改记录重复同一段内容

**Product Design Change Record**（产品设计修改记录）:
用户提出新需求或产品变更并确认设计后，`spec/product.md` 和本次受影响的 `spec/feature_<english-name>.md` 都必须追加修改记录。记录至少包含日期、Workflow Run 编号、用户需求、修改类型、修改内容和验收入口。产品总说明记录本次需求的整体变化及受影响功能；功能文档记录该功能具体新增、修改或删除了哪些用户行为、规则、边界或异常处理。“验收入口”预先链接到 `acceptance/index.md` 中当前 Workflow Run 对应的位置，不在验收计划阶段回头修改已经确认的产品设计正文。验收计划使用当前 Workflow Run 的修改记录确定本次验收范围，再以修改后的正文确认最终应有行为；修改记录不能代替完整产品设计。单纯修复 bug 且不改变产品行为时不修改产品设计文档，验收依据为现有产品设计和缺陷复现结果。
_Avoid_: 只有日期和模糊摘要, 无法区分本次与历史需求, 每份文档重复完整需求, 只看修改记录不看最终设计, 验收阶段为补主题链接反复改产品设计正文, 修 bug 恢复原设计却伪造产品变更

**Acceptance Plan Index**（验收计划索引）:
项目根下的 `acceptance/index.md`，按当前 Workflow Run 汇总本次需求涉及的产品设计修改，并说明每条修改由哪些验收主题覆盖。固定包含“本次需求、设计修改与验收主题映射、覆盖检查”三部分。映射表至少写明设计修改来源、本次修改内容、对应验收主题和主题验收目标；设计来源链接产品总说明或功能文档，主题名称链接 `acceptance/<topic>_plan.md`。每份主题验收计划反向链接到对应的产品设计章节。一个修改可以对应多个主题，一个主题也可以覆盖共同产生同一用户结果的多条修改，但本次每条修改都必须至少被一个主题覆盖；存在未覆盖修改时不能完成验收计划阶段。索引不记录测试项、实施顺序或执行状态，也不重复详细验收条件。
_Avoid_: 产品修改无法找到验收主题, 只在主题文档单向引用设计, 验收索引重复完整验收条件, 本次修改存在未被任何主题覆盖的空项, 在索引制定实施顺序, 在索引记录测试结果

**Acceptance Criterion**（验收条件）:
验收主题中一条可以明确判断通过或不通过的预期结果。每条验收条件必须写清发生条件和用户可见或可核实的结果，并引用对应的产品设计依据。每个主题内使用 `AC-01`、`AC-02` 等稳定编号；`AC` 是 Acceptance Criterion，中文含义为“验收条件”。编号只用于当前主题内的引用，不是新的验收主题编号。后续测试计划引用验收条件时，必须同时提供主题验收计划链接和验收条件的具体内容，不能只写编号。一条验收条件可以对应多个测试项，但每条验收条件都必须有测试项覆盖。验收条件说明产品最终必须怎样工作，不规定测试环境、测试数据、执行命令、测试代码或具体检查步骤；这些内容由后续测试计划决定。不能使用“正确处理”“符合预期”“功能正常”等无法单独判断的表达。
_Avoid_: 把验收条件写成测试步骤, 只写正确或正常但没有具体结果, 只用 AC 编号代替具体内容, 根据代码实现补造产品要求, 无法判断通过与不通过, 存在没有测试项覆盖的验收条件

**Acceptance Scope**（验收范围）:
主题验收计划只覆盖当前 Workflow Run 中新增、修改或删除的产品行为，以及被这些变化直接影响的原有行为。用户明确要求必须保持不变的行为也属于本次验收范围。与本次需求没有直接关系的旧功能不重复写入主题验收计划，由所有主题完成后的最终全量回归测试统一检查。验收范围必须能追溯到当前 Workflow Run 的产品设计修改记录或修 bug 的现有产品设计与缺陷复现结果。
_Avoid_: 修改一个规则却重新验收整个产品, 漏掉被修改直接影响的旧行为, 把无关旧功能塞入当前主题, 用最终回归代替本次需求验收

**Acceptance Coverage Check**（验收覆盖检查）:
制定主题验收计划时，按本次修改后的场景、规则、使用过程和异常情况逐项检查是否需要验收。内容可以归纳为预期结果、边界条件和异常情况，但不强制每个主题机械凑齐三类；没有相关设计时不编造验收条件。正式用词使用“预期结果”，不使用“正常情况”。
_Avoid_: 把正常情况作为固定分类, 每个主题强制凑齐三类, 修改了异常处理却只验收成功结果, 为填模板编造边界条件

**Acceptance Topic Plan Document**（主题验收计划文档）:
项目根下的 `acceptance/<topic>_plan.md`，每个验收主题一份，固定包含“本次需求与验收目标、产品设计依据、验收范围、验收条件、完成判定”五部分。“产品设计依据”必须链接当前 Workflow Run 的修改记录和修改后的具体设计章节；“验收条件”逐条写清条件与触发、预期结果和产品设计依据；“完成判定”说明哪些条件全部通过后主题才算完成。文档不写测试环境、测试数据、执行步骤和测试代码。
_Avoid_: 只写主题名称没有需求来源, 只链接修改记录不看最终设计, 验收计划提前写测试步骤, 完成判定使用符合预期等模糊表达

**Acceptance Source By Intent**（不同工作类型的验收依据）:
从零开发依据当前 Workflow Run 中用户确认的全部产品设计和初次建立记录；修改产品依据当前 Workflow Run 的产品设计修改记录及修改后的最终设计；修 bug 依据用户报告的缺陷、现有产品设计和缺陷复现结果，单纯恢复原有行为时不增加产品设计修改记录。修 bug 过程中如果确认必须改变产品行为、规则或边界，停止修 bug 并转为修改产品，完成产品设计修改后再制定验收计划。三种情况都只能验收用户本次提出并确认的实际需求，不能从模板或代码实现中新增验收要求。
_Avoid_: 从零开发只验收部分初始需求, 修改产品时把全部旧功能纳入主题验收, 修 bug 时为恢复原行为伪造产品变更, 根据当前代码自行增加验收目标

**Acceptance Planning Boundary**（验收计划阶段边界）:
验收计划阶段负责根据已确认需求确定验收主题、验收范围和完成条件。主题怎样拆分不清楚时可以在本阶段继续讨论；产品在某个条件下应该怎样处理尚未定义时，不能由验收计划补充产品规则，必须返回产品设计阶段确认并修改产品文档。产品设计修改后，重新检查受影响的代码设计和穿刺结论，再继续验收计划。验收计划不能借“可验收”之名增加用户未确认的产品行为。
_Avoid_: 在验收计划中偷偷决定产品行为, 用验收条件代替产品规则, 产品设计变化后不检查代码设计和穿刺结论, 为了让条件好写而改变用户需求

**Acceptance Planning Investigation**（验收计划阶段调查）:
从零开发且还没有代码时，根据已确认的产品设计制定验收计划。已有项目必须查看本次需求相关的代码和现有测试，确认哪些旧行为会被直接影响；当前 Workflow Run 已经有可信的运行、缺陷复现或穿刺结果时直接复用，不机械重复运行。缺少当前行为证据并且项目具备安全运行条件时，必须实际运行相关使用路径进行校准。代码、测试和运行结果只用于确认当前行为与影响范围，不能代替用户需求决定修改后的预期结果。
_Avoid_: 已有项目不看代码直接写验收范围, 已有可信证据仍重复运行, 可以安全运行却把猜测当当前事实, 按当前代码限制降低用户确认的验收目标

**Acceptance Planning Discussion Order**（验收计划讨论顺序）:
AI 先读取本次需求、产品设计修改记录和修改后的设计，提出完整验收主题清单，并逐项说明每个主题覆盖哪些设计修改。用户先确认主题是否完整、是否重复、拆分是否合适，再逐个主题讨论验收条件。讨论验收条件时如果发现主题需要新增、拆分、合并或改名，必须返回主题清单重新确认，并同步更新 `acceptance/index.md`；不能只改某份主题文档而留下错误映射。
_Avoid_: 边讨论条件边临时增加未确认主题, 主题清单未确认就生成全部文档, 主题变化后不更新索引, 用户只确认部分主题却继续推进

**Feature Background**（功能背景）:
功能说明文档中的“背景”说明产品中出现了什么具体需求，因此设计这个功能。它交代功能的需求来源和设计原因，不机械要求先写“目前存在什么问题”，不重复整份产品背景，也不写技术实现或开发过程。
_Avoid_: 为功能虚构问题, 用技术缺陷代替产品需求, 重复整份产品背景, 在背景写实现方案

**Requirement Discussion Process**（需求讨论过程）:
产品设计规范提示词规定的 AI 工作过程，不是用户可独立使用的产品功能，也不生成 `spec/feature_*.md` 功能文档。它负责调查事实、逐个确认决定、总结共同理解，并在用户确认后触发生成产品设计文档。
_Avoid_: 把需求讨论过程当成产品功能, 为提示词内部流程生成独立功能文档

**Feature Boundary Rule**（功能拆分标准）:
一份功能文档对应一件可以独立完成的用户事情；为了完成同一件事而共同使用的搜索、筛选、翻页等操作可留在同一功能中，目的、规则或异常处理明显不同的事情应拆开。功能不按按钮数量、页面数量或程序模块划分。
_Avoid_: 一个按钮一份功能文档, 整个产品只有一份巨型功能文档, 按代码模块拆产品功能

**Planning Stage Scope**（计划制定阶段的处理范围）:
同一个 Workflow Run 中，`acceptance_plan`、`test_plan` 和 `plan` / `fix_plan` 各进入一次，每个阶段一次处理本次需求的全部主题，而不是为每个主题重复进入一遍阶段。三个阶段分别只走一次三道门禁，但可以产出多份文档。验收计划、测试计划和实施计划的具体字段与拆分方式由各自提示词和规范单独定义，不在路径规则里提前写死。
_Avoid_: 每个主题重复走一遍 acceptance_plan/test_plan/plan, 把一次处理全部主题误解成只能生成一份文档, 计划制定阶段与实际执行状态混为一谈

**Per-Topic Execution**（按主题分别执行）:
计划制定完成后，不要求全部实施任务都完成才开始测试。某个验收主题关联的全部实施任务已经完成并合并后，该主题即可执行自己的测试；测试通过后即可执行自己的验收。其它独立主题可以继续实施，不必等待。存在依赖时，后置主题仍须等待前置主题满足实施计划确定的条件。某个主题被新不确定性、测试失败或验收失败阻塞时，只阻塞它和实际依赖它的主题，不自动阻塞无关主题。
_Avoid_: 一个主题完成仍等待所有实施任务, 一个主题失败让全部主题停工, 关联实施任务未完成就开始测试, 忽略主题依赖提前执行

**Final Regression Test**（最终全量回归测试）:
所有主题分别完成实施、测试和验收后，必须基于全部已合并代码运行一次最终全量回归测试，检查各主题组合后的完整行为以及原有功能是否受到影响。各主题先前的独立测试和验收不能替代最终全量回归。最终全量回归通过后，才能执行整个需求的最终确认和详细代码设计更新。
最终全量回归失败时不能进入整体验收，修复后必须重新运行最终全量回归。失败后怎样确定受影响主题、保留哪些主题状态以及如何退回，由后续 `regression_test` 和 `topic_execution` 详细规范决定，本轮流程框架不提前写死。
_Avoid_: 各主题单独通过后直接结束, 只测试新增功能不检查原有功能, 未合并全部代码就声称完成全量回归, 回归失败仍进入最终确认, 修复后不重跑全量回归, 在详细规范讨论前声称已经能自动判断受影响主题

**Acceptance Plan Stage** (`acceptance_plan`):
根据已经确认的需求确定本次全部验收主题，并为每个主题制定“什么算完成”的验收计划。主题在此阶段由用户确认；不执行测试、实施或验收。
_Avoid_: 写完验收计划就视为已验收, 在 plan 阶段才确定主题, 主题只在当前 Run 内唯一

**Test Plan Stage** (`test_plan`):
根据已经确认的验收主题和验收计划制定测试计划，不实际执行测试，也不得自行改变主题。
_Avoid_: 测试计划自行新增删除主题, 写测试计划冒充已经测试

**Implementation Plan Stage** (`plan` / `fix_plan`):
根据已经确认的验收计划和测试计划制定实施或修复计划。实施计划可以按实施任务拆分，不要求与验收主题一一对应，但每项实施工作必须能说明关联哪些主题。该阶段不得重新确定主题，也不得执行正式实施。
_Avoid_: 在 plan 阶段重新拆主题, 把计划制定和实际实施混在一起, 强制实施任务与主题一一对应

**Topic Execution Stage** (`topic_execution`):
在一个顶层阶段内，分别推进各主题的实施、测试和验收。独立主题可以处于不同进度；存在依赖时按实施计划确定的顺序推进。全部主题完成后，`topic_execution` 才能结束。主题内部使用什么状态字段、命令和文档结构由该阶段的提示词与规范单独定义。
_Avoid_: 顶层固定成所有 impl 完成后才允许任何 test, 一个主题失败就清零全部主题, 把主题执行细节塞进路径编排规则

**Regression Test Stage** (`regression_test`):
全部主题完成后，对全部已合并代码运行最终全量回归，产出 `qa/final_regression_result.md`。该阶段通过前不能进入整体验收。

**Overall Acceptance Stage** (`overall_acceptance`):
最终全量回归通过后，由用户确认整个需求是否完成，产出 `acceptance/overall_result.md`。该阶段完成后才能更新详细代码设计。

**Verification Invalidation** (验证结果自动失效):
当前流程骨架先实现顶层失效：验收计划变化时退回 `acceptance_plan`；测试计划变化时退回 `test_plan`；实施代码、实施记录或主题测试结果变化时退回 `topic_execution`；最终全量回归结果变化时退回 `regression_test`。程序同时清零该阶段及其后续顶层阶段的门禁和旧哈希，并把 `current_stage` 移到最早需要重做的阶段，stdout 打印对应的下一条命令。主题内部怎样只让受影响主题失效，留到 `topic_execution` 的状态和规范讨论中实现，当前代码不声称已经具备该能力。
_Avoid_: 只清门禁但 current_stage 仍停在后面导致无法重做, 上游变化后沿用旧哈希, 失效后仍提示操作原阶段, 在主题状态尚未设计前声称能精确判断受影响主题

**Update Code Design Stage** (`update_code_design`):
所有工作意图在 `regression_test` 通过且 `overall_acceptance` 经用户确认之后进入详细架构收尾 Stage。写入/更新同一文件 `spec/architecture_code_design.md`，用户确认后置 `architecture.detailed_done`。从零做、改产品、修 bug 末环同名；不再使用 `generate_code_design`。
_Avoid_: generate_code_design 作为从零做末环, 三种意图末环不同名, 因文件已存在而跳过本 stage, 未通过测试验收就写最终架构

**Installer Agent Contract Write** (安装时写入代理契约):
项目目录确认正确且当前项目尚未安装后，安装脚本把最小代理契约直接写入 **`AGENTS.md`**：文件不存在则新建，文件存在则整份覆盖。契约包含 workflow 入口、stdout 跟随规则和核心表达要求。这里不再提供契约冲突选择、不自动合并、不生成备份。项目已有完整安装标记时按重复安装规则直接退出，不改现有契约。

不再提供 `--overwrite-agent` 或 `workflow attach`。安装程序唯一需要阻塞等待的是项目目录确认。
_Avoid_: 自动合并, 同时维护双份契约, 目录未确认就覆盖, 重复安装重写契约, 保留 attach 或 overwrite-agent 兼容入口

**Path Composer** (路径编排):
根据 `intent` 与项目事实（`project_design_initialized`、是否从零做清场等）生成本次 Stage 列表的机制。正式形态：`build_stage_path(intent, project_root) -> list[Stage]`（函数或专用模块均可，不强制类层次）。取代旧的四个 Scenario 类并行流水线与 `SCENARIO_REGISTRY`。Stage 策略类（各 Stage 的产出与门禁行为）仍保留；被删除的是「场景枚举 = 路径」的旧模型。
_Avoid_: NewProject/Existing/Bugfix/ProductMod 四场景类作为主模型, 用 scenario registry 四选一取路径, 把路径硬编码进 CLI 命令分支而不经统一编排
**Legacy CLI Removal** (旧 CLI 删除):
第一版实现**直接删除**旧入口，不做双写兼容：
- 删除 `start --entry` 四场景及 `SCENARIO_REGISTRY` / 四 Scenario 类主模型
- 不保留 `align` 式场景菜单；不把旧 entry 名映射到新 intent
- 删除面向用户的 `workflow attach` 与 `--overwrite-agent`；项目首次安装只走官方安装脚本
- `overview` 第一版**可不做**（文档百科非开工阻塞；需要时后置）
误用旧参数时：明确报错并用说人话提示正确入口（未安装项目先在项目根执行官方安装脚本；已安装项目由智能体调用 `workflow start` 检查状态或 `start --intent …` 开工）。
正式日常命令面：`start`、`discuss`、`gate`、`status`、`done`、`abort`（及已定参数：`--confirm-clean`、`gate spike --skip` 等）。安装脚本是日常 CLI 之外的首次入口。
_Avoid_: entry 映射兼容层, 保留四场景菜单, 第一版强制实现 overview
