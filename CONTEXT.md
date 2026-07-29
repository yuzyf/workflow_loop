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
**明确不做**：不创建 `state.json`（那是 `start --intent`）；不预建空的项目根 `spec/`、`acceptance/`、`qa/`、`impl/`、`bug/`（首次写产物时再建）；不下发 role 说明文件（角色说明暂时留在代码/`role_doc`，与提示词仓库分离）。安装成功后才允许 `start --intent`。
_Avoid_: 要求目标项目里先有 workflow.py, 全局命令安装与项目安装要求用户执行两条命令, 安装时猜错项目根, start 时静默安装, 把安装做成带三道闸的正式 Stage, 安装时创建 state.json, 使用非 AGENTS.md 的契约文件名, 预建空产物目录, 下发 role 文档仓库


**Template Seeding** (产物文档模板与阶段工作规范下发):
官方安装脚本安装当前项目时，将系统自带的默认 **Template_Repository**（产物文档模板仓库）与 **Standardized_Repository**（阶段工作规范仓库）复制进项目 `.workflow_loop/`。之后 `discuss` 从**项目内**这两份仓库加载当前阶段的产物文档模板和阶段工作规范（不在运行时直读全局安装包，便于项目定制）。
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
- **from_scratch（从零做）**：先清场（删除旧设计/过程产物；保留规范与模板仓库）→ `spec`（产品设计 + 功能拆分）→ `code_design`（初步，不可因旧文件跳过）→ `spike`（可选）→ `acceptance_plan`（确定主题、主题关系和完成标准）→ `test_plan`（确定测试覆盖）→ `impl`（先确认全部实施前计划，再修改真实代码并记录实施结果）→ `test_code`（编写测试代码）→ `test_execution`（执行测试并记录结果）→ `topic_acceptance`（按验收条件核对用户结果）→ `regression_test`（最终全量回归）→ `overall_acceptance`（整体验收）→ `update_code_design`（详细落地，强制）
- **product_change（改产品）**：若 `project_design_initialized=false`，先走 `project_design_init`；之后统一走 `spec` → `revise_code_design` → `spike`（可选）→ `acceptance_plan` → `test_plan` → `impl` → `test_code` → `test_execution` → `topic_acceptance` → `regression_test` → `overall_acceptance` → `update_code_design`
- **bugfix（修 bug）**：若 `project_design_initialized=false`，先走 `project_design_init`；之后走 `reproduce` → `spike`（可选）→ `acceptance_plan` → `test_plan` → `impl` → `test_code` → `test_execution` → `topic_acceptance` → `regression_test` → `overall_acceptance` → `update_code_design`。`reproduce` 负责复现缺陷并确认根因；`spike` 只验证修复 bug 时仍未确认、并且必须用真实运行证据才能确认的具体事项。修复所需事实都已经确定时，由用户确认后跳过穿刺。
- `project_design_initialized=true`：改产品/修 bug 跳过共享初始化阶段；文件是否存在不能单独决定跳过。任何意图不得跳过末段详细架构 Stage
- 共享后半截：`acceptance_plan` → `test_plan` → `impl` → `test_code` → `test_execution` → `topic_acceptance` → `regression_test` → `overall_acceptance` → `update_code_design`
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
路径上的一个具名环节（如 `spec`、`spike`、`acceptance_plan`、`test_code`、`test_execution`、`topic_acceptance`、`regression_test`）；内部走讨论与门禁循环。
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
入口与路径模型重做时**不砍门禁协议**。可选 spike 的 `gate spike --skip` 是额外跳过动作，不取消其它 stage 的三道门，也不把三道门合并或改成“校验过即当用户确认”。`test_code`（编写测试代码）、`test_execution`（执行测试）、`topic_acceptance`（主题验收）、`regression_test`（最终全量回归）与 `overall_acceptance`（整体验收）都是三种意图的强制 Stage，不提供 `--skip`；环境阻塞或用户未验收不得按通过处理。
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
验收计划根据已确认需求拆出的一个可独立验收结果名称。主题使用中文，名称直接写清验收对象和完成后的结果，不使用“功能优化”“流程完善”等模糊名称，也不使用“开发模块”“修改代码”“增加接口”等实施任务名称。主题文字本身就是唯一标识，不再另加 `PL-001` 一类编号；主题在整个项目历史中永久唯一，后续 Workflow Run 不得重复使用已有主题名称。一个 Workflow Run 可以有多个主题，每个主题分别制定验收计划、测试计划和实施文档，并分别测试和验收。`acceptance/<topic>_plan.md`、`qa/<topic>_plan.md`、`qa/<topic>_result.md`、`acceptance/<topic>_result.md` 和 `impl/<topic>.md` 使用同一个主题名称。

主题之间可以存在产品或验收依赖。`acceptance_plan` 阶段首次确认主题关系，并在 `acceptance/index.md` 中保存“展示顺序、验收主题、前置主题”关系表；`qa/index.md` 和 `impl/index.md` 只能继承并展示这份关系，不能重新制定或修改另一套主题顺序。没有依赖关系的主题不强制互相等待；展示顺序只帮助读者阅读，真正的等待关系由“前置主题”字段表达。主题之间不得形成互相等待的循环依赖。测试项内部的执行顺序写在各主题测试计划中，代码修改步骤内部的执行顺序写在各主题实施文档中。

从零开发和修改产品在 `acceptance_plan` Stage 由用户确认主题；修 bug 时，一份缺陷复现记录对应一个验收主题，主题名称根据该缺陷修复后必须恢复的用户结果确定，并在 `reproduce` Stage 用户确认缺陷记录时写入当前 Workflow Run 的主题列表和项目主题历史。修 bug 的验收计划只能使用缺陷记录中已经确认的主题，不能重新改名、拆分或合并。不论哪种工作类型，都不在 `start` 或 `impl` 时临时确定主题。测试计划和实施计划不能自行改名、拆分或合并主题；发现从零开发或修改产品的主题过大时返回验收计划重新调整，发现修 bug 的缺陷记录实际混入多个无关缺陷时返回缺陷复现阶段拆成多份记录。
_Avoid_: 一个 Workflow Run 强制只能有一个主题, 使用抽象主题名, 用开发任务充当验收主题, 为主题重复增加独立编号, 只要求单次 Run 内不重名, 后续 Run 复用旧主题名称, 修 bug 到验收计划才临时发明主题, 一份缺陷记录塞入多个无关缺陷, 测试计划或实施计划自行改名拆分合并主题, 测试验收实施无法一一对应, 只写存在依赖却不写前置主题, 让后续索引重新制定主题顺序, 主题互相等待, start 或实施阶段才临时确定主题


**Artifact** (产出):
某 Stage 要求落盘的文档或文件集合；门禁会检查其是否就绪。落盘位置在**项目根下的产物目录**（如 `spec/product.md`、`impl/<主题>.md`），**不是** `.workflow_loop/Template_Repository/` 里的同名子目录。
_Avoid_: Output, deliverable（可作同义，但正式词用 Artifact）, 把 Template_Repository 下的产物文档模板当成项目根产物

**Process Artifact Roots** (过程产物根目录):
项目根下由 workflow 管理、清场可能删除的目录/文件约定位置，与模板仓库分离：
- 产物侧（可清场）：**固定落在项目根**（不是 `.workflow_loop/` 内）：`spec/`、`acceptance/`、`qa/`、`impl/`、`bug/` 等实际写出的文档
- 模板/规范侧（永不因清场删除）：`.workflow_loop/Template_Repository/`（含其中的 `spec/` 等**产物文档模板**子目录）、`.workflow_loop/Standardized_Repository/`
同名 `spec` 出现两次时含义不同：`Template_Repository/spec/` = 写产品说明时用的产物文档模板；项目根 `spec/` = 写出来的 product.md / 架构文档等。
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
**下一步**：`workflow discuss` —— 由 discuss **完整打印**当前 stage 的产物文档模板与阶段工作规范（见 Prompt Full Print）。
「精简开工摘要」**仅**指 start 不倾倒文档百科、不代替 discuss；**绝不**表示阶段材料可以摘要、截断或不打印。
_Avoid_: 把开工摘要理解成精简阶段材料, start 不打印路线图, 用摘要替代 discuss 的完整材料加载

**Discuss Command** (讨论加载命令):
`workflow discuss`：给**当前 AI**加载本 stage 工作材料。从项目内 `.workflow_loop/Template_Repository` 与 `Standardized_Repository` 读取后，在命令 stdout 中**完整输出**（AI 跑 CLI 时从工具结果读到全文，不是编一本给终端用户看的说明书）。固定拼装：
1. 当前 stage 名与角色说明全文（没有角色定义时明示无）
2. **全局写作规范全文**：固定读取 `Standardized_Repository/global/document_writing.md`
3. **产物文档模板全文**（规定最终要写出的文档结构和内容）
4. **阶段工作规范全文**（规定怎样调查、讨论、执行和检查；该 stage 无独立规范则明示无）
5. 当前 stage 的附加材料、指令和约定产出路径
6. 下一步：AI 按阶段工作规范调查和讨论，并使用产物文档模板整理文件；用户说讨论完毕后，AI 调 `workflow gate <stage> --discuss-done`
用户参与的是「业务讨论」；用户不负责阅读或批准内部工作材料本身。无活跃 Run 或已 completed/aborted 则报错。不在每次 discuss 倾倒整份文档结构百科。
**可重复加载**：同一 stage 在 Run 仍为 active 且该 stage 尚未整轮结束前，允许多次 `discuss`，每次完整下发提示词/规范（AI 重载指令用）。重复 discuss **不**自动清零已通过的门禁（discussion_complete / code_validated / user_confirmed 不因 discuss 回滚）。

`workflow discuss` 还必须计算当前阶段模板、规范、全局写作规范和附加材料的内容指纹；`gate <stage> --discuss-done` 保存用户确认时的材料指纹。材料内容之后发生变化时，程序自动清除该阶段的讨论完成和后续门禁状态，要求重新执行 `workflow discuss` 和第一道门；只重复加载相同内容时不回滚状态。该规则适用于所有阶段，不能手工修改 `state.json` 继续使用旧提示词确认。
_Avoid_: 模板已变化仍复用旧讨论状态, 每次重复 discuss 都无条件清零, 只比较文件路径不比较内容, 要求用户手工编辑状态修复

**Prompt Full Print** (阶段材料完整下发):
产物文档模板和阶段工作规范的消费者是 **AI**。`discuss` 必须在 stdout 给出**完整正文**，以便 AI 当轮上下文拿到全文；不得改成摘要版、截断版，也不得只打印文件路径让 AI「自己去读」却不给正文（路径可作附注）。不因 start 的路径摘要而缩短 discuss 输出。
_Avoid_: 把阶段材料当成写给用户的说明书, discuss 只打印路径不给正文, 阶段材料摘要截断, 要求用户阅读或批准内部材料, 每次 discuss 倾倒完整文档百科, 每 stage 只允许 discuss 一次, 重复 discuss 自动回滚门禁

**Stage Material Responsibility Split**（阶段材料职责划分）:
确定不变的阶段顺序、三道门、允许状态、固定字段、产物路径、主题登记时机、哈希和文件结构校验由程序执行，不能依靠 Markdown 提醒 AI 自觉遵守。`Template_Repository` 保存产物文档模板，主要规定最终文档要写哪些章节、字段、表格和内容边界；`Standardized_Repository` 保存阶段工作规范，主要规定 AI 怎样调查、讨论、执行和检查，并说明怎样使用产物文档模板。能够明确判断的固定规则同时由代码门禁校验。产物文档模板、阶段工作规范和代码不得重复维护同一套确定规则。现有阶段材料若与此职责相反，后续按该全局规则调整。

只有阶段确实生成需要长期保存、并会被后续人员或阶段读取的独立文档时，才为该产物建立 `Template_Repository` 模板。每份模板必须能明确对应一个或一组真实 Artifact 路径；只负责协调其它工作、执行代码门禁或记录状态的 Stage 不为凑齐材料而创建模板。一个 Stage 可以没有产物模板，也可以只加载它实际生成的下层产物模板。是否进入下一阶段、是否通过、是否已经得到用户确认等状态，优先记录在 State Snapshot、Journal 和追踪表中，不再为同一状态额外生成重复汇总文档。
_Avoid_: 把产物文档模板写成访谈脚本, 没有独立产物仍创建模板, 为每个 Stage 强行配一份模板, 用汇总文档重复已有状态和证据, 阶段工作规范只列目录, Markdown 重复阶段顺序和门禁代码, 固定规则只写文档不写代码, 同一规则在模板和规范各写一遍, 不同 stage 对 Template_Repository 使用不同含义

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
从零做、改产品和修 bug 路径上的不确定性验证 Stage。修 bug 时位于 `reproduce` 和 `acceptance_plan` 之间；它不重新复现已经确认的缺陷，也不要求先有完整修复方案，只验证修复所需但当前仍不知道的真实行为、返回内容、兼容性、性能或其他具体事实。spike 默认在路径中。AI 调查并与用户讨论后，只有用户明确决定本次没有需要实际验证的不确定性，才通过 `workflow gate spike --skip` 跳过：state 记 skipped、journal 记跳过并推进下一 Stage；不要求临时代码、穿刺清单或结论文档。AI 认为没有值得穿刺的不确定性时只能说明调查结果并建议跳过，最终决定仍由用户作出。不能靠 AI 自觉删 stage；不在 start 时默认从路径抹掉 spike。
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
穿刺完成不要求原方案验证成功，而要求证据已经足以支持后续决定，或者剩余风险、后续处理阶段和检查内容已经写清并等待用户决定。结论分为三类：`已确认`，证据足以直接作出决定；`限制已确认`，确认原方案不可行或只能部分满足要求，但可以据此换方案或收缩范围；`仍未确认`，证据不足。结果状态只说明证据确认到了什么，“是否阻塞后续”单独说明当前能否进入验收计划。无论结果状态是哪一类，只要仍然阻塞后续，门2都不能通过；必须继续验证，或者由用户决定怎样调整产品、技术方案或范围并更新相关文档。`仍未确认`但不阻塞时，必须记录具体剩余风险和后续检查阶段；用户是否接受由门3确认，不在文档中提前代替用户决定。
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
穿刺文档正文可以按真实情况自由说明，但决定工作流能否继续的内容必须使用固定字段。第七部分“结论”固定填写“结果状态：已确认｜限制已确认｜仍未确认”“是否阻塞后续：是｜否”“已确认内容”“仍未确认内容”；第八部分“对后续工作的影响”固定填写“产品设计影响：需要修改｜无需修改”“产品设计更新位置”“代码设计影响：需要修改｜无需修改”“代码设计更新位置”“剩余风险”“后续处理阶段：无｜acceptance_plan｜test_plan｜impl｜test_code｜test_execution｜topic_acceptance｜regression_test｜overall_acceptance｜update_code_design”“后续需要检查什么”。门2必须拒绝非法状态和任何“是否阻塞后续：是”的项目；结果为“仍未确认”时，剩余风险、后续处理阶段和后续需要检查什么都不能为空；所有标记为“需要修改”的产品设计和代码设计文档必须已经变化。固定字段只用于程序判断，不能代替对真实证据和具体结论的说明，门3由用户最终确认是否接受所记录的剩余风险。
_Avoid_: 让门禁猜测自由文本含义, 用“基本完成”等自定义状态, 未确认事项不写剩余风险和后续检查内容, 穿刺推翻产品要求却只改代码设计, 只填固定字段而不解释实际结论

**Bugfix Spike Product Boundary Gate**（修 bug 穿刺的产品边界门禁）:
当前工作意图为 `bugfix` 时，门2必须拒绝任何写有“产品设计影响：需要修改”的穿刺项，并明确提示当前结果不能继续按修 bug 流程推进，应结束当前 Run 后启动 `product_change`。如果用户选择保持原产品行为的其他修复方案，必须重新写清方案与证据，并把产品设计影响写为“无需修改”后才能继续。程序只检查明确字段，不自行判断某段自由文字是否暗中改变产品行为，门3仍由用户审查实际内容。
_Avoid_: bugfix 门禁允许修改产品行为, AI 只改字段不改实际方案, 程序声称能从自由文字判断产品语义, 需要改产品仍继续当前修 bug 流程

**Spike Material Split**（穿刺产物模板与阶段工作规范职责）:
`Template_Repository/spike/spike.md` 负责规定最终保留的穿刺清单和结论文档结构、字段和内容边界；`Standardized_Repository/spike/spike.md` 负责规定 AI 怎样读取已有事实、识别真实场景中的不确定性、让用户决定执行项、选择最小验证方法、执行真实验证、形成结论和同步设计。允许状态、阻塞判断、设计哈希比较、临时目录清理和阶段推进由代码执行。prototype 方法可以改写后进入阶段工作规范，不直接作为运行时外部依赖。
_Avoid_: 产物模板写成访谈脚本, 阶段工作规范只列文档目录, 直接引用开发者本机 prototype 路径, 两份文件重复整套规则, 用 Markdown 代替程序门禁

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
正常执行 spike 时，全部真实场景验证完成后、进入 `acceptance_plan` 前，必须让 `spec/architecture_code_design.md` 吸收穿刺结论。穿刺本身只负责取得真实证据；证据确认后，由用户决定采用什么实现或修复办法。穿刺确认了接口形状、数据结构、模块边界、算法约束、性能限制、平台限制或异常行为，并因此改变代码设计时，按真实证据写清受影响的模块、文件、函数、调用过程、数据转换和异常处理；修 bug 时也不能把这一步推迟到已经开始实施之后。实现或修复办法仍未决定时视为阻塞，不能进入验收计划；某项结论不影响代码设计时，在结论文档中明确写“代码设计无需修改”。门3由用户一起确认穿刺结论和更新后的代码设计。`workflow gate spike --skip` 跳过时不修改代码设计。
_Avoid_: 穿刺后仍保留验证前猜测, 把结论只放 spike 文档不更新架构, 未决定怎样实现或修复就进入验收计划, 没有影响也不明确说明, spike 阶段直接修改生产代码

**Spike Product Design Feedback**（穿刺结果回写产品设计）:
从零做或改产品时，穿刺结果可能证明原有产品行为、功能范围或产品规则在真实场景中无法成立。此时 AI 不能只修改代码设计，也不能自行改变产品要求；必须说明真实证据、冲突位置和可选处理方式，由用户决定是否调整产品设计。用户确认调整后，先更新 `spec/product.md` 或对应功能产品文档，再让 `spec/architecture_code_design.md` 与更新后的产品设计保持一致。产品设计仍与穿刺结论冲突时，门2不能通过；仅影响技术实现而不改变用户可见行为和产品规则时，产品设计可以标记为“无需修改”。

修 bug 时，`bugfix` 的前提是原产品行为不变：穿刺只影响修复方法或代码结构时可以更新代码设计并继续；当前方案不可行但仍有保持原产品行为的其他方案时，继续讨论其他修复方案；只有改变产品行为、功能范围或产品规则才能继续时，停止当前修 bug 流程，由用户决定是否改产品。用户决定改产品后，执行 `workflow abort` 结束当前 Run，再以 `workflow start --intent product_change` 启动修改产品流程。AI 不得在修 bug 流程中直接修改产品规则，也不得静默改变工作意图。
_Avoid_: 技术限制出现后静默缩减产品能力, 产品文档和代码设计互相冲突, AI 未经用户确认修改产品规则, 在 bugfix 中偷偷改产品行为, 不影响产品设计却为过门禁随意改文档

**Spike Unified Confirmation**（穿刺结果统一确认）:
穿刺导致产品设计变化时，不退回并重走已经完成的产品设计阶段。用户先根据穿刺证据决定产品行为或范围怎样调整，AI 随后依次更新产品设计和代码设计；门2检查穿刺结论、产品设计和代码设计已经一致，门3由用户一起确认这三部分后再进入验收计划阶段。用户尚未决定产品调整方式，或者文档之间仍有冲突时，穿刺阶段不能结束。
_Avoid_: 为一次穿刺反馈机械重跑整个产品设计阶段, 只确认穿刺文档不确认被修改的产品与代码设计, 产品调整未决定就进入验收计划

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
- **整目录删除**：项目根下 `spec/`、`acceptance/`、`qa/`、`impl/`、`bug/` 只要含有文件，就删除命中的整个目录及全部内容。这些目录中即使放了非 workflow 文件，也会一起删除。
- **不删除目录外内容**：`.workflow_loop/Template_Repository/` 与 `.workflow_loop/Standardized_Repository/` 全部内容；`.workflow_loop/project.json` 文件本身（只更新初始化字段）；上述五个目录之外的源代码、`.git` 和项目文件；`.workflow_loop/` 运行时骨架本身。
- **确认**：有可删过程产物时才走清场确认；无则跳过（见 Clean Confirm）。
_Avoid_: 从零做复用旧架构并跳过初步, 删除 Template/Standardized 仓库或其下 stage 子目录, 把模板 spec 当产物删, 默认删除源代码, 静默清场不确认, 无过程产物仍强制 --confirm-clean

**Clean Detect List** (清场监测清单):
`from_scratch` 开工前用**固定路径表**探测「是否有过程产物」，与删除范围同一份约定（方案 A）：
- 监测对象：项目根下 `spec/`、`acceptance/`、`qa/`、`impl/`、`bug/` 中**已存在且含文件**的路径（非空才算有产物；空目录可不触发确认）
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
`bugfix` 在 `test_execution`、`topic_acceptance`、`regression_test` 与 `overall_acceptance` 通过之后必须经过 `update_code_design`。若实施阶段判定不涉及结构变更，仍须走该 Stage，并在门禁中显式确认「无结构变化」；涉及结构则必须改架构图。不可因“只是小 bug”省略测试、验收或架构 Stage。
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
规定 AI 怎样从已确认产品设计形成代码覆盖清单，推导架构层和关键节点，逐个功能设计完整代码过程，落实产品规则与异常，设计共享代码和验证方式，并在用户确认后使用共同的 `Template_Repository/code_design/code_design.md` 生成正式架构文档。`code_design` 形成计划设计；`project_design_init` 还必须遵守存量项目调查和运行规范；`revise_code_design` 和 `update_code_design` 只改变工作规范，不另建同结构的模板。
_Avoid_: 从代码目录开始拼架构, 产品设计未确认就生成文档, 只设计成功路径不落实规则和异常, 不经用户确认直接写正式产物

**Revise Code Design Stage** (`revise_code_design`):
改产品路径上、`spec` 产品设计与功能拆分之后的设计期改架构 Stage。用户确认讨论完成时记录 `spec/architecture_code_design.md` 的内容哈希，门2要求文件相对该基线发生变化。与末段 `update_code_design`（详细落地）名称分离，避免同一 Run 内 stage 名冲突。
_Avoid_: 与 update_code_design 共用同一 stage 名当主键

**Project Design Init Stage** (`project_design_init`):
首次处理已有代码项目时，为 `product_change` / `bugfix` 共享的前置 Stage，中文名“项目设计架构初始化”。角色为“存量产品与架构分析师”。它必须查看现有代码；具备安全运行条件时必须运行项目，用真实表现校准代码理解；无法运行时写清原因和未确认内容。根据现有代码及可运行行为一次建立 `spec/product.md`、多个 `spec/feature_<english-name>.md`、`spec/architecture_code_design.md`，并生成 `spec/project_design_init_evidence.md`。产品文档使用产品文档模板，代码架构使用共同的代码架构文档模板，调查证据使用独立的调查证据模板；阶段工作规范只规定怎样调查和校准。门2要求产品设计、代码设计和调查证据都相对讨论完成时的基线发生变化，并检查证据中的代码路径真实存在。门3确认后写 `project_design_initialized=true` 与 `architecture.preliminary_done=true`。程序不能证明证据没有伪造，用户必须在门3核对。该 Stage 完成前作废不得写 true。
_Avoid_: 只生成 architecture_code_design.md, 拆成彼此可能不一致的产品反推和架构反推两轮, 用旧文档存在冒充本次初始化完成, 为项目初始化另建一份代码架构模板

**Product Spec Stage** (`spec`):
统一负责“产品设计 + 功能拆分”。角色为产品设计师；加载 `.workflow_loop/Template_Repository/spec/spec.md` 与 `.workflow_loop/Standardized_Repository/spec/spec.md`；产物为 `spec/product.md` 与多个 `spec/feature_<english-name>.md`。`from_scratch` 中负责从零建立；`product_change` 中负责基于现状重新设计，可新增、修改或删除功能文档。用户确认讨论完成时记录相关文件路径与内容哈希，门2比较前后变化。`from_scratch` 要求新建 product.md 且至少新建一个功能文档；`product_change` 要求 product.md 有变化且至少一个功能文档新增、修改或删除。
_Avoid_: 只校验 product.md, 独立生成 requirement_<临时名>.md, 把产品更新与功能拆分拆成两个后续 Stage, 旧功能文件冒充本 Run 产物

**Product Spec Document Template**（产品设计产物文档模板）:
`.workflow_loop/Template_Repository/spec/spec.md` 是适用于所有产品类型的产品文档模板，提供 `spec/product.md` 和 `spec/feature_<english-name>.md` 的章节骨架、字段、内容边界和完成前检查；它说明“最终文档应是什么”，不承担逐题访谈流程，也不强制所有产品套用数据进入、整理、计算、输出等固定分类。
_Avoid_: 把产物模板写成访谈脚本, 只给目录不定义内容质量, 把某类数据产品的处理环节规定成所有产品必用维度

**Product Spec Work Standard**（产品设计阶段工作规范）:
`.workflow_loop/Standardized_Repository/spec/spec.md` 规定产品设计阶段怎样调查事实、和用户讨论、检查共同理解以及使用产品文档模板生成或修改文档。产品背景和功能设计原因必须来自用户确认或可核实事实，不能从文件名、提示词或代码结构推断历史；没有相关内容时写“暂无”，不得为了填满模板编造内容。
_Avoid_: 阶段工作规范只列文档目录, 产物模板承担整套访谈, 强制所有需求按固定顺序讨论, 为填满模板编造产品内容

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
用户提出新需求或产品变更并确认设计后，`spec/product.md` 和本次受影响的 `spec/feature_<english-name>.md` 都必须追加修改记录。记录至少包含日期、Workflow Run 编号、用户需求、修改类型、修改内容和追踪入口。产品总说明记录本次需求的整体变化及受影响功能；功能文档记录该功能具体新增、修改或删除了哪些用户行为、规则、边界或异常处理。“追踪入口”预先链接到项目根 `traceability.md` 中当前 Workflow Run 对应的位置，不在后续阶段回头修改已经确认的产品设计正文。验收计划使用当前 Workflow Run 的修改记录确定本次验收范围，再以修改后的正文确认最终应有行为；修改记录不能代替完整产品设计。单纯修复 bug 且不改变产品行为时不修改产品设计文档，验收依据为现有产品设计和缺陷复现结果。
_Avoid_: 只有日期和模糊摘要, 无法区分本次与历史需求, 每份文档重复完整需求, 只看修改记录不看最终设计, 验收阶段为补主题链接反复改产品设计正文, 修 bug 恢复原设计却伪造产品变更

**Traceability Matrix**（需求交付追踪表）:
项目根下的 `traceability.md`，按 Workflow Run 分段保存整个项目的需求交付历史，是从产品设计或缺陷复现开始，到最终代码设计更新结束的完整链路和唯一总入口。每个工作流章节记录用户需求从产品设计或缺陷复现到最终代码设计更新的完整关系；从零开发清场时删除旧文件，修改产品和修 bug 时追加当前工作流章节，不覆盖历史。每条验收条件占一行，至少包含需求来源与设计依据、验收主题、验收条件、测试项、实施计划与任务、实施记录与代码、测试结果、验收结果、更新后的代码设计。验收计划阶段先填写需求来源、设计依据、验收主题和验收条件；测试计划和实施计划列初始写“待制定”，实施记录、测试结果和验收结果列初始写“待执行”，最终代码设计列初始写“待更新”，不能留空。后续阶段只补充自己负责的列，把初始状态替换成实际状态和真实文档或证据链接；出现阻塞时必须写清阻塞原因。表格只写简短内容、状态和链接，详细规则、步骤和结果留在对应阶段文档中。从零开发和修改产品使用产品设计记录与最终设计作为来源；修 bug 使用用户报告、缺陷复现记录和现有产品设计中的预期行为作为来源，不伪造产品设计修改记录。一个设计修改或缺陷可以对应多个主题，一个主题可以覆盖多条共同产生同一用户结果的来源，但本次每项需求或缺陷必须至少被一个主题覆盖。当前验收计划哈希包含 `acceptance/index.md` 和本次各主题的 `acceptance/<topic>_plan.md`，因此主题关系、展示顺序或验收计划变化都会使后续阶段重新检查；后续阶段更新追踪表不会使已经确认的验收计划失效。

`traceability.md` 是完整链路，不再另建一份独立的 `AC → TC → 测试结果` 映射表。测试项、测试结果和主题验收结果都沿用追踪表中同一条验收条件记录；各阶段文档只补充本阶段的详细内容，并标注自己的直接上游和直接下游，不能各自维护一套相互独立的全局关系。

**Global And Local Traceability**（整体链路与局部双向链路）:
整体链路由项目根 `traceability.md` 保存，按每条验收条件横向连接需求来源、验收主题、测试项、实施计划、实施记录与代码、测试结果、主题验收结果和最终代码设计。局部双向链路由各阶段文档保存：当前文档直接链接自己的上游依据和下游承接文档，让读者可以从当前文档回到来源并继续往后查看。局部链接是导航和当前文档关系说明，不是另一份独立的全局映射；局部文档不得改写或替代 `traceability.md` 中的整体关系。
_Avoid_: 用局部链接替代整体追踪表, 用整体追踪表替代当前文档的直接上下游链接, 为 AC、TC 和结果另外创建第二份关系表, 只保存上游链接而没有下游链接
_Avoid_: 只能从需求向后查不能从结果返回需求, 每个阶段建立互不关联的索引, 在追踪表复制整份文档内容, 后续阶段覆盖前面阶段的关系, 本次修改存在未覆盖项, 后续阶段列留空无法区分未开始和漏写, 只写阻塞不写原因, 用口头状态代替真实结果链接

**Local Upstream And Downstream Links**（局部上下游链接）:
产品设计、验收计划、测试计划、实施计划、实施记录、测试结果、验收结果和最终代码设计文档都必须提供局部上下游链接。每份文档只直接链接当前内容的上游依据和下一阶段文档，不复制整条链路和执行状态。上游链接让读者返回当前内容的直接来源；下游链接让读者继续查看下一阶段怎样承接；完整状态和跨阶段跳转由 `traceability.md` 统一保存，不要求每份局部文档重复链接追踪表。局部文档使用可预先确定的稳定路径，后续文件生成后链接自动可用，不通过修改已确认的上游正文补链接。
_Avoid_: 只能从全局表打开局部文档, 局部文档没有来源和去向, 把全局追踪表复制到每份局部文档, 每份文档复制一套状态造成不一致, 后续阶段为补链接改动已确认内容并触发哈希失效

**Acceptance Criterion**（验收条件）:
验收主题中一条可以明确判断通过或不通过的预期结果。每条验收条件必须写清发生条件和用户可见或可核实的结果，并引用对应的产品设计依据。每个主题内使用 `AC-01`、`AC-02` 等稳定编号；`AC` 是 Acceptance Criterion，中文含义为“验收条件”。编号只用于当前主题内的引用，不是新的验收主题编号。后续测试计划引用验收条件时，必须同时提供主题验收计划链接和验收条件的具体内容，不能只写编号。一条验收条件可以对应多个测试项，但每条验收条件都必须有测试项覆盖。验收条件说明产品最终必须怎样工作，不规定测试环境、测试数据、执行命令、测试代码或具体检查步骤；这些内容由后续测试计划决定。不能使用“正确处理”“符合预期”“功能正常”等无法单独判断的表达。
_Avoid_: 把验收条件写成测试步骤, 只写正确或正常但没有具体结果, 只用 AC 编号代替具体内容, 根据代码实现补造产品要求, 无法判断通过与不通过, 存在没有测试项覆盖的验收条件

测试计划引用验收条件时，直接链接主题验收计划和对应的验收条件位置即可，不复制整段验收条件。`traceability.md` 保存验收条件与测试项、测试结果和验收结果的整体对应关系，局部测试文档不另建映射表。

测试计划文档的局部上下游只连接直接关系：`qa/<topic>_plan.md` 的上游是 `acceptance/<topic>_plan.md`，下游是 `impl/index.md` 和 `qa/<topic>_result.md`。测试计划不直接链接更后面的主题验收、最终全量回归或最终代码设计；这些关系由后续文档和 `traceability.md` 保存。
`qa/index.md` 保存继承自 `acceptance/index.md` 的主题关系，以及主题验收计划、测试计划和测试结果的链接；它不重新制定主题依赖，不重复验收条件、`AC → TC` 映射、测试覆盖范围、测试执行状态或测试项顺序。
每份 `qa/<topic>_plan.md` 固定保存五部分：验收条件覆盖、针对性回归范围、测试条件要求、未决测试条件、直接上下游文档。它不复制验收计划的产品背景、验收目标、验收条件正文或产品规则，不提前写测试通过或失败。

**Acceptance Index**（验收索引）:
项目根 `acceptance/index.md` 是本次工作流主题关系的首次确认入口。它由 `acceptance_plan` 阶段生成或更新，至少列出展示顺序、验收主题、前置主题、验收计划和主题验收结果链接。验收计划门禁必须检查它存在、覆盖当前工作流全部主题、前置关系无循环。它不重复验收条件、产品规则、测试内容或实施细节；全局交付关系和跨工作流历史仍由 `traceability.md` 保存。`qa/index.md` 和 `impl/index.md` 必须继承这份主题关系，不能自行改名、拆分、合并或重排依赖。

`acceptance_plan` 阶段的固定产物是 `traceability.md`、`acceptance/index.md` 和每个主题的 `acceptance/<topic>_plan.md`；`test_plan` 阶段的固定产物是 `qa/index.md` 和每个主题的 `qa/<topic>_plan.md`；`impl` 阶段的固定产物是 `impl/index.md` 和每个主题的 `impl/<topic>.md`。三个索引都属于局部入口，`acceptance/index.md` 首次确认主题关系，后两个索引只继承并展示，不代替 `traceability.md` 的整体链路。
`test_plan` 阶段生成 `qa/index.md` 和各主题测试计划；后续测试执行只在同一索引中补充 `qa/<topic>_result.md` 链接，不把测试状态、测试正文或执行顺序写入索引。
`test_plan` 阶段只更新 `traceability.md` 的“测试项”列，写入指向各主题测试计划具体测试项的链接；“测试结果”“验收结果”“实施计划与任务”“实施记录与代码”等列继续保持“待执行”或相应初始状态，之后进入 `impl` 阶段。该阶段不生成本次需求的测试结果文件，也不执行本次需求的正式测试；但必须执行一次修改前全量测试，用于建立基线门禁。
测试计划中的“建议验证方式”是测试项的可选属性：已知时可以写自动测试、人工验证、真实环境验证或组合验证；未知时写“实施后确认”，不把这些方式变成所有产品都必须使用的固定分类。

**Acceptance Scope**（验收范围）:
主题验收计划只覆盖当前 Workflow Run 中新增、修改或删除的产品行为，以及被这些变化直接影响的原有行为。用户明确要求必须保持不变的行为也属于本次验收范围。与本次需求没有直接关系的旧功能不重复写入主题验收计划，由所有主题完成后的最终全量回归测试统一检查。验收范围必须能追溯到当前 Workflow Run 的产品设计修改记录或修 bug 的现有产品设计与缺陷复现结果。
_Avoid_: 修改一个规则却重新验收整个产品, 漏掉被修改直接影响的旧行为, 把无关旧功能塞入当前主题, 用最终回归代替本次需求验收

**Acceptance Coverage Check**（验收覆盖检查）:
制定主题验收计划时，按本次修改后的场景、规则、使用过程和异常情况逐项检查是否需要验收。内容可以归纳为预期结果、边界条件和异常情况，但不强制每个主题机械凑齐三类；没有相关设计时不编造验收条件。正式用词使用“预期结果”，不使用“正常情况”。
_Avoid_: 把正常情况作为固定分类, 每个主题强制凑齐三类, 修改了异常处理却只验收成功结果, 为填模板编造边界条件

**Acceptance Topic Plan Document**（主题验收计划文档）:
项目根下的 `acceptance/<topic>_plan.md`，每个验收主题一份，固定包含“本次需求与验收目标、产品设计依据、验收范围、验收条件、完成判定、上下游文档”六部分。从零开发和修改产品时，“产品设计依据”必须链接当前 Workflow Run 的产品设计记录和修改后的具体设计章节；修 bug 时必须链接用户报告、缺陷复现记录和现有产品设计中的预期行为。“验收条件”逐条写清条件与触发、预期结果和产品设计依据；“完成判定”说明哪些条件全部通过后主题才算完成；“上下游文档”链接项目根 `traceability.md`、上游依据和下游 `qa/<topic>_plan.md` 测试计划。文档不写测试环境、测试数据、执行步骤和测试代码。
_Avoid_: 只写主题名称没有需求来源, 只链接修改记录不看最终设计, 看验收计划时无法直接打开上下游文档, 验收计划提前写测试步骤, 完成判定使用符合预期等模糊表达

**Acceptance Source By Intent**（不同工作类型的验收依据）:
从零开发依据当前 Workflow Run 中用户确认的全部产品设计和初次建立记录；修改产品依据当前 Workflow Run 的产品设计修改记录及修改后的最终设计；修 bug 依据用户报告的缺陷、缺陷复现记录和现有产品设计中的预期行为，单纯恢复原有行为时不增加产品设计修改记录。修 bug 的验收条件必须覆盖：原复现条件下错误结果不再出现、现有产品设计规定的预期结果能够得到、修复直接影响的原有行为没有被破坏。修 bug 过程中如果确认必须改变产品行为、规则或边界，或者现有产品设计没有定义预期结果，停止修 bug 并转为修改产品，完成产品设计修改后再制定验收计划。三种情况都只能验收用户本次提出并确认的实际需求，不能从模板或代码实现中新增验收要求。
_Avoid_: 从零开发只验收部分初始需求, 修改产品时把全部旧功能纳入主题验收, 修 bug 时为恢复原行为伪造产品变更, 根据当前代码自行增加验收目标

**Acceptance Plan Code Validation By Intent**（验收计划按工作类型校验）:
验收计划门禁必须读取当前 Workflow Run 的工作类型。from_scratch（从零开发）检查初次产品设计记录和最终设计依据；product_change（修改产品）检查本次产品设计修改记录和修改后的设计依据；bugfix（修 bug）检查缺陷复现记录、现有产品设计中的预期行为，以及验收计划文件名与缺陷记录中已确认主题完全一致，不要求产品设计修改记录，也不允许验收计划新增、改名、拆分或合并主题。bugfix 的验收计划如果要求改变产品行为、规则或边界，门禁必须拒绝继续并提示转为 product_change。
_Avoid_: 三种工作类型强制检查同一种来源, 修 bug 没有修改记录就无法验收, 修 bug 到验收计划重新创造主题, 修 bug 借验收计划改变产品行为, 缺少缺陷复现记录仍通过门禁

**Bug Resolution And Closure**（缺陷修复结果与关闭）:
缺陷复现阶段生成的 `bug/<缺陷记录>.md` 不预先链接尚未生成的验收文档。验收计划和验收结果生成时必须链接回缺陷记录；项目根 `traceability.md` 在中间阶段持续显示缺陷与后续产物的关系。主题验收通过后，缺陷记录追加“修复与验收结果”，链接实施记录、测试结果和主题验收结果，状态写“主题验收通过，待全量回归”。最终全量回归失败时，状态改为“回归失败，重新处理中”，命令、退出码和输出摘要保存在当前工作流的 `state.json` 和 `journal.jsonl`。只有最终全量回归和整体验收都通过后，缺陷记录及 `bug/index.md` 才改为“已修复并验收”。追加处理结果不能改写原来的复现条件、实际结果、期望结果和根因。
_Avoid_: 缺陷复现时预写不存在的验收链接, 主题验收通过就提前关闭 bug, 回归失败仍保留已修复状态, 为补结果改写原始复现事实, done 命令才偷偷更新 bug 册

**Acceptance Planning Boundary**（验收计划阶段边界）:
验收计划阶段负责根据已确认需求确定验收主题、验收范围和完成条件。主题怎样拆分不清楚时可以在本阶段继续讨论；产品在某个条件下应该怎样处理尚未定义时，不能由验收计划补充产品规则，必须返回产品设计阶段确认并修改产品文档。产品设计修改后，重新检查受影响的代码设计和穿刺结论，再继续验收计划。验收计划不能借“可验收”之名增加用户未确认的产品行为。
_Avoid_: 在验收计划中偷偷决定产品行为, 用验收条件代替产品规则, 产品设计变化后不检查代码设计和穿刺结论, 为了让条件好写而改变用户需求

**Downstream Discovery Handling**（后续阶段发现不一致时的处理）:
实施和测试阶段没有权力改变用户需求，也不能因为实现困难、测试失败或代码现状不同而修改验收条件。发现实际代码、代码设计或实施计划与已确认产品设计不一致时，修改代码设计、实施计划或代码，产品需求和验收条件保持不变。发现新的技术不确定性时，停止受影响任务并按穿刺规则取得真实证据，再修正技术方案；这不属于需求变化。发现产品设计本身存在遗漏、矛盾或无法判断的内容，说明前面的产品设计确认有缺口，必须停止受影响工作并返回产品设计阶段补充确认；这是修正遗漏，不是实施阶段自行改变需求。只有用户明确提出新的产品要求时才属于需求变化，必须作为新的产品变更处理，不能在当前实施或测试文档中直接改写原验收条件。
_Avoid_: 测试失败就降低验收标准, 实现困难时修改用户需求, 把新技术事实说成需求变化, 产品设计缺口由实施人员自行决定, 修 bug 绕过产品变更, 在当前验收条件上增加版本号掩盖新需求

**Requirement Proposal Timing**（需求提出与正式确认的时机）:
用户可以在任何阶段提出新的想法或要求，但只有产品设计阶段负责把它确认成正式产品需求。验收计划、测试计划和实施阶段收到新想法时，先判断它是当前需求中遗漏的内容还是当前范围之外的新需求；前者返回产品设计阶段补充确认，后者不加入当前 Workflow Run，当前工作流完成后再启动 product_change（修改已有产品）工作流。新需求必须立即处理时，由用户决定中止当前 Workflow Run 后启动新的产品变更工作流。
_Avoid_: 把用户在实施阶段说的话直接写进验收条件, 用测试或实施文档确认新需求, 当前需求没完成就偷偷混入下一项需求, AI 自行决定是否中止当前工作流

**Acceptance Planning Investigation**（验收计划阶段调查）:
从零开发且还没有代码时，根据已确认的产品设计制定验收计划。已有项目必须查看本次需求相关的代码和现有测试，确认哪些旧行为会被直接影响；当前 Workflow Run 已经有可信的运行、缺陷复现或穿刺结果时直接复用，不机械重复运行。缺少当前行为证据并且项目具备安全运行条件时，必须实际运行相关使用路径进行校准。代码、测试和运行结果只用于确认当前行为与影响范围，不能代替用户需求决定修改后的预期结果。
_Avoid_: 已有项目不看代码直接写验收范围, 已有可信证据仍重复运行, 可以安全运行却把猜测当当前事实, 按当前代码限制降低用户确认的验收目标

**Acceptance Planning Discussion Order**（验收计划讨论顺序）:
AI 先读取本次需求、产品设计修改记录和修改后的设计，提出完整验收主题清单，并逐项说明每个主题覆盖哪些设计修改。用户先确认主题是否完整、是否重复、拆分是否合适，再逐个主题讨论验收条件。讨论验收条件时如果发现主题需要新增、拆分、合并或改名，必须返回主题清单重新确认，并同步更新 `traceability.md`；不能只改某份主题文档而留下错误映射。
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

**Planning And Implementation Stage Scope**（实施计划与实施阶段的处理范围）:
同一个 Workflow Run 中，`acceptance_plan`、`test_plan` 和 `impl` 各进入一次。`impl` 同时承接实施前计划确认和计划确认后的真实代码实施；同一份主题实施文档分别保存实施前计划和实施后记录，不能把计划内容和实际结果混成一句话。实施代码完成后，流程明确分为 `test_code`、`test_execution`、`topic_acceptance` 三个阶段：先写测试代码，再执行测试并记录结果，最后按验收条件核对用户结果。
_Avoid_: 没有确认实施前计划就开始改代码, 实施记录只写“已完成”不写实际文件和逻辑, 把测试代码、测试执行和主题验收塞进一个协调阶段

**Per-Topic Execution**（按主题分别执行）:
计划制定完成后，不要求全部实施任务都完成才开始测试。某个验收主题关联的全部实施任务已经完成并合并后，该主题即可执行自己的测试；测试通过后即可执行自己的验收。其它独立主题可以继续实施，不必等待。存在依赖时，后置主题仍须等待前置主题满足实施计划确定的条件。某个主题被新不确定性、测试失败或验收失败阻塞时，只阻塞它和实际依赖它的主题，不自动阻塞无关主题。
_Avoid_: 一个主题完成仍等待所有实施任务, 一个主题失败让全部主题停工, 关联实施任务未完成就开始测试, 忽略主题依赖提前执行

**Final Regression Test**（最终全量回归测试）:
所有主题分别完成实施、测试和验收后，程序必须调用项目配置的统一测试入口（当前项目是 `scripts/test_all.sh`）运行一次最终全量回归，检查各主题组合后的完整行为以及原有功能是否受到影响。各主题先前的独立测试和验收不能替代最终全量回归。最终全量回归通过后，才能执行整个需求的最终确认和详细代码设计更新。
最终回归不需要人工填写 `final_regression.md` 或 `qa/final_regression_result.md`。程序把命令、退出码、开始时间、结束时间、代码快照和输出摘要写入 `state.json` 与 `journal.jsonl`，并在 `traceability.md` 中记录“最终全量回归：通过”。
最终全量回归失败时不能进入整体验收，修复后必须重新运行最终全量回归。bugfix 中程序同时把缺陷状态更新为“回归失败，重新处理中”，但不改写原复现事实。修复产品代码后返回 `test_code`，重新编写或调整测试代码，再执行主题测试和主题验收。
_Avoid_: 各主题单独通过后直接结束, 只测试新增功能不检查原有功能, 未合并全部代码就声称完成全量回归, 回归失败仍进入最终确认, 修复后不重跑全量回归, 在详细规范讨论前声称已经能自动判断受影响主题

**Acceptance Plan Stage** (`acceptance_plan`):
根据已经确认的需求确定本次全部验收主题，并为每个主题制定“什么算完成”的验收计划。主题在此阶段由用户确认；不执行测试、实施或验收。
`Template_Repository/acceptance/acceptance_plan.md` 负责规定 `traceability.md`、`acceptance/index.md` 和 `acceptance/<topic>_plan.md` 的最终文档结构、字段和内容边界；`Standardized_Repository/acceptance/acceptance_plan.md` 负责规定 AI 怎样根据已确认需求讨论验收主题、主题关系和验收条件，并使用产物文档模板生成文件。主题登记、主题关系、固定章节、编号、追踪表列数、初始状态、链接和门禁由代码检查。`qa/` 只保存测试计划、测试执行和最终全量回归相关材料，不混放验收计划。
_Avoid_: 写完验收计划就视为已验收, 在 plan 阶段才确定主题, 主题只在当前 Run 内唯一, 产物模板重复整套用户访谈, 阶段工作规范只列文档目录, 用 Markdown 代替程序门禁

**Test Plan Stage** (`test_plan`):
对已经确认的验收条件进行测试覆盖审查，不重新描述验收条件，不执行本次需求的正式测试，也不得自行改变主题；但必须通过项目统一测试入口运行一次修改前全量测试，建立当前代码的基线。该阶段首先判断每条验收条件是否有可行的验证方向、明确的观察结果和可复核证据；验收条件无法验证时返回 `acceptance_plan`，不能在测试计划里自行补产品规则。除此之外，还要检查本次修改影响哪些已有行为、需要哪些针对性回归范围、哪些测试条件仍要等实施后才能确定，并把这些内容写入测试计划。针对性回归只检查本次修改直接影响的已有行为；所有主题完成后仍必须执行一次最终全量回归。测试计划中的未决测试条件必须区分：当前已经确定、实施后才能确定、验收条件本身无法验证；不能把“实施后才能确定”写成测试失败，也不能用它掩盖无法验证的验收条件。
_Avoid_: 只把验收条件改写成测试项, 测试计划自行新增删除主题, 写测试计划冒充已经测试, 在代码和实施方案未知时编造未来命令、接口、文件或测试数据

**Test Plan Material Split**（测试计划阶段材料职责）:
`Template_Repository/qa/test_plan.md` 是测试计划的**产物文档模板**，规定 `qa/<topic>_plan.md` 和 `qa/index.md` 最终应有哪些章节、字段、表格、链接和内容边界。`Standardized_Repository/qa/test_plan.md` 是测试计划阶段的**工作规范**，规定 AI 怎样读取验收条件、代码和已有测试，怎样和用户讨论覆盖范围，以及什么时候退回产品设计、验收计划或穿刺阶段。前者不能写成访谈流程，后者不能替代产物模板直接生成最终文档。
_Avoid_: 把测试计划阶段的调查问题、讨论顺序和退回规则写进 `Template_Repository/qa/test_plan.md`；把 `Standardized_Repository/qa/test_plan.md` 当成最终测试计划文档直接填写；因为代码字段名叫 `prompt_doc_path()` 就互换两个目录的职责

**Acceptance-to-Test Mapping**（验收条件到测试项的映射）:
测试计划仍然要以已经确认的验收条件 `AC`（Acceptance Criterion，中文为“验收条件”）为主线，但不复制验收条件正文，也不把 `TC`（Test Case，中文为“测试项”）当成已经写完具体步骤的测试用例。每条验收条件必须有明确的验证方向和覆盖结论；一条验收条件可以由多个测试项覆盖，但每个测试项只绑定一条主要验收条件。测试计划还要单独记录本次变更的已有行为回归范围、当前无法确定的测试条件和后续需要保留的证据类型。测试方式只是测试项的属性，不改变验收主题和验收条件的组织关系。具体命令、测试数据、代码文件和执行证据等到实施和测试执行时根据真实代码补充。普通已知产品行为可以使用可重复的测试数据；当真实外部行为本身是测试对象时（如真实接口返回、真实文件解析或真实设备表现），必须使用真实样本或真实环境，不能只用 mock 数据代替。
`traceability.md` 的“测试项”列不能只写 `TC-01` 这类编号，必须写测试项编号、直白名称和指向测试计划具体位置的链接；一个测试项覆盖多条验收条件时，各条追踪记录都直接链接到同一测试项。这样用户可以从验收条件直接打开对应的验证方向，不需要再次搜索测试计划。
测试结果和主题验收结果必须沿用对应追踪表行中的测试项关系；主题验收不能根据文件名或主题名称自行猜测测试结果，也不能再创建第二份 AC、TC 和结果关系表。
测试计划不强制使用“正常、异常、边界”等固定分类。覆盖范围根据验收条件、当前代码和已有测试显示的受影响行为、本次修改的实际风险决定；适用时才写对应场景，不适用时写“暂无”并说明原因。
每份 `qa/<topic>_plan.md` 只保存四类测试设计信息：验收条件覆盖表、针对性回归范围、测试条件要求、未决测试条件。它不复制验收计划的产品背景、验收目标、验收条件正文、产品规则或功能范围。`qa/index.md` 只保存主题测试计划的索引、覆盖状态和未决项入口，不复制测试计划正文。
测试计划阶段必须读取相关产品设计、代码设计、当前代码和已有测试；具备安全运行条件时先运行已有测试，建立“修改前基线”。基线只说明当前项目在本次需求修改前的状态，不能当成本次需求已经测试通过。没有代码或已有测试时记录“暂无基线”；有代码或已有测试但无法运行时写清原因和未验证范围。
修改代码前的当前项目全量测试是 `test_plan` 阶段的固定门禁条件：项目已有代码或已有测试时，具备安全运行条件却没有执行、没有结果或执行失败，不能通过测试计划门禁。项目还没有代码或已有测试时可以记录“暂无基线”；有测试执行失败时暂停，由用户决定先修已有失败、保留为已知失败继续，或调整当前需求范围，程序不能把它自动算成本次需求失败或自动放行。完成实施后仍必须重新执行最终全量回归，修改前结果不能替代最终结果。
修改前全量测试由 `test_plan` 第二道门直接执行项目已经确认的统一测试入口，命令、退出状态、执行时间和结果写入当前 State Snapshot 与 Journal，不额外生成 `qa/pre_implementation_full_test.md`。第三道门只在代码状态没有变化时复用第二道门结果；代码发生变化时，修改前全量测试状态失效并要求重新执行。
**Project Test Entry**（项目统一测试入口）:
每个具备可运行测试的项目必须提供一个明确的全量测试入口。入口配置写在项目级 `.workflow_loop/project.json` 的 `test_entry` 字段；已有稳定命令或项目脚本时优先填写已有入口，没有时填写项目补充的统一脚本，例如 `scripts/test_all.sh`。这个入口必须运行项目约定的全部单元测试，并用退出码表示结果：`0` 表示通过，非 `0` 表示失败或无法执行。工作流门禁只执行配置中的入口，不猜测测试命令，不在门禁执行时临时创建脚本，也不把脚本本身当作测试结果。当前项目的入口配置为 `scripts/test_all.sh`，它调用项目虚拟环境中的 `pytest`（pytest 是 Python 测试运行工具）。
_Avoid_: 每个阶段自行猜不同测试命令, 用局部测试代替全量测试入口, 入口失败后仍写成通过, 门禁临时生成测试脚本, 把修改前基线当成本次需求测试结果
测试计划发现问题时按问题性质退回：产品结果没有定义时返回 `spec`；产品结果已定义但验收条件无法判断时返回 `acceptance_plan`；真实接口、真实文件解析、设备表现等技术事实未知时返回 `spike`；只有具体命令、测试文件或测试数据要等代码完成后才能确定时，保留在测试计划中标记“实施后确认”。
测试计划门禁只检查可明确判断的固定条件：`qa/index.md` 存在、每个主题有对应测试计划、每条验收条件至少关联一个测试项、测试项有编号和直白名称、`traceability.md` 的“测试项”列有具体链接、主题没有被改名或拆分、测试计划没有冒充测试结果。代码不判断测试方向是否“足够好”，这由 AI 根据事实分析并由用户确认。
测试计划讨论先做全局覆盖审查：AI 读取全部验收主题、验收条件、相关代码、已有测试和修改前基线，先向用户说明主题覆盖、针对性回归范围、未决测试条件和无法验证的问题；用户确认全局范围没有遗漏后，再逐个主题讨论测试覆盖。测试计划不要求用户逐条批准未来的具体命令或代码文件。
测试计划通过用户确认时，验收条件覆盖、验证方向、预期观察结果和会影响测试设计的技术不确定性必须已经解决；具体命令、测试文件、测试数据和证据位置可以标记“实施后确认”。
测试项之间存在前置关系时，测试计划必须写清依赖的测试项和执行顺序；没有依赖的测试项不强制排序。测试项顺序只服务于测试执行，不改变验收主题和验收条件；`qa/index.md` 只做测试计划索引，不另建与主题测试计划冲突的顺序规则。
_Avoid_: 按测试工具或代码层级拆散验收条件, 只重复验收条件的触发和预期结果, 一条验收条件没有验证方向, 用一个模糊测试项声称全部覆盖, 在代码和实施方案未知时编造执行细节, 在测试计划阶段提前填写测试通过

**Test Item Dependency**（测试项依赖）:
同一主题内某个 `TC-xx` 必须在另一个测试项成功后才能执行的关系，测试计划使用“前置测试项”字段记录；无依赖写“无”，跨主题依赖改由验收主题关系表达。程序检查引用、循环和执行顺序；前置测试项的有效成功执行记录可以被多个后续测试项复用，间接依赖不重复填写或重复执行，只有执行记录失效时才重跑。
_Avoid_: 跨主题 TC 直接互相依赖, 重复列出全部间接依赖, 多个后续测试重复执行同一有效前置项, 形成循环依赖

**Implementation Stage** (`impl`):
根据已经确认的验收计划和测试计划，按验收主题和测试覆盖范围确定实施内容，再在同一 Stage 中修改真实代码并追加实施结果。实施不能从代码目录或孤立任务清单开始，也不能重新确定验收主题；一个主题内部可以有多个代码修改步骤，但这些步骤只是完成该主题的手段。计划阶段和代码实施不再拆成两个 Stage，但“实施前计划”和“实施后记录”必须分开写，不能用计划内容代替事实。`impl` 不降低验收条件；代码实施完成后，必须依次经过 `test_code`、`test_execution` 和 `topic_acceptance`。
实施计划讨论开始前，AI 必须先用第一性原理重新检查用户需求：先说明用户要解决的实际问题和最终要得到的结果，再检查使用条件、产品规则、功能边界、异常情况、主题依赖、代码约束和技术不确定性。凡是可能改变实施文件、函数、处理逻辑、数据、状态、输出或测试范围的问题，都必须逐个向用户提问，直到双方对本次实施内容达成共识；已经能从已确认文档、真实代码或运行结果确定的内容不重复提问，也不能为了“问全”提出与实施无关的问题。未达成共识前不能生成实施计划或修改代码。
全局检查结果固定先汇总七项：用户要解决的问题、最终产品结果、全部验收主题、主题之间的依赖、多个主题共用的代码、已经确认的实施依据、仍未解决的问题及需要返回的阶段。该汇总用于让用户先确认整个实施范围，不替代各主题实施文档，也不记录代码修改细节。
逐个主题讨论时固定按八步进行：先说明主题要解决的用户问题；说明完成后的用户结果；对照验收条件和测试项确认必须实现的内容；根据真实代码说明文件、类、函数和当前逻辑（从零项目说明计划新增的位置）；说明具体代码修改及数据/状态/输出变化；检查主题依赖和公共代码；逐个解决仍未确认的问题；用户确认后才写入该主题的实施文档。第 4 至第 6 步必须有代码或已确认设计依据，不能根据主题名称猜测。
`impl` 仍按三道门推进：先调 `workflow discuss` 加载实施计划模板、实施流程规范和代码开发规范，再调 `workflow gate impl --discuss-done` 确认实施前计划已经讨论完成，之后才能修改代码；代码和实施记录完成后调 `workflow gate impl` 做程序校验；用户确认实际实施结果后调 `workflow gate impl --confirmed`，再进入 `test_code`。第一道门会检查当前工作流已经加载这三份材料。
如果实施计划确认前确实发生了代码变化，不能重复调用第一道门；用户确认当前代码应作为新的实施前现状时，先调 `workflow gate impl --rebaseline` 重设代码基线，再重新调第一道门。该命令不自动执行，不修改实施结果，也不替代用户确认。
如果当前代码已经是实施结果，且不再需要计划确认后修改代码，用户在第一道门通过、实施后记录完整后调 `workflow gate impl --accept-existing-code`，明确确认当前代码。之后代码必须保持不变，才能通过 `workflow gate impl`。
`impl` 必须先为当前工作流的全部验收主题完成实施前计划，用户确认全部计划后才能开始任何代码修改。计划确认后，没有依赖的主题可以分别实施；有前置主题的主题按 `acceptance/index.md` 已确认、并由 `impl/index.md` 展示的关系等待；某个主题失败只阻塞它和实际依赖它的主题，不自动阻塞其他独立主题。
`impl` 的产物按验收主题拆分：`impl/index.md` 使用与 `acceptance/index.md` 一致的主题关系表，列出展示顺序、验收主题、前置主题、验收计划链接、测试计划链接和主题实施文档链接；它只展示已确认关系，不重新制定主题顺序，不重复实施细节，也不保存“实施中、已完成”等运行状态，运行状态由程序的 State Snapshot 和 Journal 统一保存。每个验收主题生成一份 `impl/<topic>.md`，同一份文档包含该主题的实施前计划和实施后记录。不能按代码目录、函数或孤立实施任务另建一套主文档。
`impl/<topic>.md` 的“实施依据”属于产物模板内容，使用“依据类型、具体内容、文档位置”三列记录与当前主题直接相关的产品设计、验收条件、测试项、代码设计和穿刺结论。验收条件和测试项必须同时写编号与直白名称并链接到具体位置；没有穿刺结论时写“暂无”。该章节不复制整份上游文档。AI 怎样查找、筛选和核对这些依据属于 `Standardized_Repository/impl/impl.md` 的工作规范，不能写进产物模板。
`impl/<topic>.md` 的“实施前计划”属于产物模板内容，依次包含预期产品结果、代码修改计划、开发检查计划和未决问题。代码修改计划使用“顺序、文件、类/函数/配置项、当前逻辑、计划修改的具体逻辑、数据/状态/输出变化、对应验收条件和测试项、前置步骤”字段，必须写到具体文件和代码位置；不存在的代码位置标记“新增”。开发检查计划只写实施过程中准备运行的检查及预期观察，不提前填写通过或失败。未决问题没有时写“暂无”；存在未解决问题时，不能通过 `impl --discuss-done`，也不能开始修改代码。
`impl/<topic>.md` 的“实施后记录”属于产物模板内容，依次包含实际代码修改、开发检查记录和未完成内容。实际代码修改使用“对应计划步骤、文件、类/函数/配置项、实际修改的代码逻辑、数据/状态/输出的实际变化、对应验收条件和测试项”字段，必须根据最终代码填写，不能直接复制实施前计划。开发检查记录使用“检查命令或方法、检查范围、实际反馈、是否需要继续修改”字段，只保存实施过程中的单元测试、类型检查或局部检查反馈，不得写成正式测试结果。未完成内容没有时写“暂无”。该章节不能声称主题已经验收、需求已经完成或正式测试已经通过。
`impl/<topic>.md` 不建立“计划与实际差异”章节。实施结果必须符合当前已经确认的实施前计划；发现任何不一致时立即停止当前实施，不能把差异记录下来后直接放行。只有代码实现计划需要调整、且产品行为、验收条件和测试范围不变时，返回 `impl` 的计划确认环节，更新实施前计划并由用户重新确认；产品行为变化返回 `spec`，验收条件变化返回 `acceptance_plan`，测试范围变化返回 `test_plan`，出现新的技术不确定性时由用户决定是否返回 `spike`。返回并重新确认后，实施后记录只与最新确认的实施前计划比较，退回过程由 Journal 保存。
`impl/<topic>.md` 的“上下游文档”属于产物模板内容，使用“关系、文档、说明”三列保存直接链接。上游至少包括本主题验收计划、测试计划和相关代码设计；下游包括本主题正式测试结果和主题验收结果。该章节只提供入口并说明各文档的用途，不复制上下游正文；下游文件尚未生成时保留确定的目标路径，生成后由对应阶段补全有效链接。
每份 `impl/<topic>.md` 使用标题 `# 【实施】<验收主题>`，并在标题下只保存“工作流编号”和“验收主题”两个固定字段。验收计划、测试计划等链接统一写入“实施依据”和“上下游文档”，运行状态由程序保存；模板不重复这些内容，也不增加没有直接用途的更新时间字段。
实施规范必须区分“已有代码”和“从零开始”两种情况：已有代码时必须查看真实文件、类、函数、调用关系和已有测试；从零开始且没有实现代码时，不能编造“当前逻辑”，代码位置按计划新增标记，实施依据改为已确认的产品设计、代码设计、验收计划、测试计划和穿刺结论。没有可运行的现有代码或测试时写“暂无”，具备运行条件的已有脚本或测试仍必须运行并记录事实。
一段公共代码同时服务多个验收主题时，只在一个相关主题文档中完整记录它的文件、函数和实施逻辑；其他主题文档不重复整段内容，只说明依赖的公共代码以及它怎样满足本主题的验收条件和测试项，并链接到公共代码的详细记录位置。公共代码不能只写在 `impl/index.md` 里，因为索引只负责继承主题关系和提供文档入口。
**Implementation Material Split**（实施材料职责）:
`Template_Repository/impl/impl.md` 只规定 `impl/index.md` 和 `impl/<topic>.md` 最终文档的章节、字段、表格、链接和内容边界；`Standardized_Repository/impl/impl.md` 规定 AI 怎样读取验收计划和测试计划、怎样确认实施前计划、怎样修改代码、怎样核对实际结果与已确认计划，以及发现不一致时怎样停止并返回对应阶段；`Standardized_Repository/impl/code_implementation.md` 单独规定模块、接口、依赖、接缝、状态、副作用、错误处理和测试面的代码写法。进入 `impl` 后必须先用 `workflow discuss` 加载这三份实施材料，第一道门会检查加载记录；实施过程中可以运行测试作为开发反馈，但正式测试结果只由 `test_execution` 记录，主题验收结果只由 `topic_acceptance` 记录。
提交代码和推送代码不属于 `impl` 的固定流程、产物或门禁条件。只有用户明确要求提交或推送时才执行对应仓库操作；没有收到要求时，实施完成只需要保留真实代码修改和实施记录，不能因为尚未提交而判定 `impl` 失败。
_Avoid_: 把实施流程写进 `Template_Repository/impl/impl.md`，把实施文档章节骨架写进 `Standardized_Repository/impl/impl.md`，用代码修改任务替代验收主题，提前把开发反馈写成正式测试结果
_Avoid_: 没有先确认实施计划就修改代码, 把计划与实际差异当成可以直接放行的正常结果, 把测试和主题验收继续塞回 impl

**Test Code Stage** (`test_code`):
实施代码完成后，先按照已经确认的验收条件和测试计划编写测试代码。本阶段只允许静态检查、语法检查、类型检查和 lint，不运行单元测试、集成测试、单个测试或全量测试，也不生成正式测试结果或主题验收结果。程序门禁确认测试代码相对进入本阶段时发生变化，并确认本阶段没有修改产品代码；产品代码还需要修改时返回 `impl`。

本阶段使用两份不同职责的规范，不使用产物文档模板：`Standardized_Repository/qa/test_code.md` 是测试代码阶段流程规范，规定 AI 必须先读取验收计划、测试计划、实施后记录、代码设计、当前产品代码、现有测试代码和测试配置，再把每个测试项落实到具体产品代码入口、测试文件、测试场景、断言、测试依赖和隔离清理；`Standardized_Repository/qa/test_code_implementation.md` 是测试代码开发规范，只规定测试命名、断言、测试隔离、测试接缝、模拟依赖和不得修改产品代码等代码写法。本阶段的产出是项目真实测试代码和必要的测试配置，不生成第二份测试计划或测试代码说明文档。

测试计划与测试代码的对应关系直接保存在测试代码中，不另建映射文档。每个测试函数、测试类或测试场景的名称、注释或语言支持的测试元数据必须同时写清验收主题、`TC-xx` 测试项编号和测试项名称；需要进一步说明时同时写 `AC-xx` 验收条件编号和验收条件名称。还必须写清本测试具体验证什么、测试工具实际使用的测试入口，以及从哪个产品代码入口进入。后续 `test_execution` 在 `qa/<topic>_result.md` 中记录实际测试文件、测试入口、执行命令和结果证据，使验收条件、测试计划、测试代码和测试结果可以互相找到。

测试代码的固定追踪标识使用下面的字段，不允许只写编号：

```text
Workflow-Test
主题：<验收主题名称>
测试项：TC-xx <测试项名称>
验收条件：AC-xx <验收条件名称>
测试方式：自动化测试 | 自动化测试 + 人工验收
测试层级：单元测试 | 模块测试 | 集成测试 | 命令测试 | 接口测试 | 端到端测试
测试目标：<这段测试具体要验证什么>
测试入口：<测试工具可以实际执行的测试节点、测试名称或选择器>
代码入口：<从哪个命令、类、函数或接口进入>
```

Python 等支持文档字符串的语言写在测试函数或测试类的文档字符串中；其他语言写在测试旁边的注释或测试元数据中。`test_code` 门禁按当前工作流的主题、测试项编号和测试项名称逐项查找这个标识，缺少任一测试项对应的完整标识时不能进入 `test_execution`。

测试计划中的每个 `TC-xx` 必须标明测试方式：`自动化测试`、`人工验收` 或 `自动化测试 + 人工验收`。`自动化测试`必须在 `test_code` 阶段生成测试代码；`人工验收`不强行编造测试代码，由 `topic_acceptance` 按验收条件核对；混合方式由 `test_code` 覆盖可自动判断的部分，由 `topic_acceptance` 覆盖必须由用户观察或判断的部分。能自动化判断的内容不能为了省事改成纯人工验收。`test_code` 门禁只要求自动化部分存在固定追踪标识。

测试代码不能绕过产品入口、伪造外部返回值或把当前错误实现当成预期结果。产品代码已有可用入口时直接从真实入口测试；缺少必要的测试接缝（可以替换外部依赖、控制输入或观察结果的代码位置）时返回 `impl`；测试计划的测试方式或范围不正确时返回 `test_plan`；预期结果不明确时返回 `acceptance_plan`；产品行为没有定义时返回 `spec`；必须运行真实外部场景才能确认技术事实时由用户决定是否返回 `spike`。只有测试目录或测试文件位置不明确、但现有测试框架能够支持时，才留在 `test_code` 解决。

自动化测试不统一要求写成单元测试。`test_code` 根据真实产品入口和需要证明的结果选择单元测试、模块测试、集成测试、命令或接口测试、端到端测试，并在写代码前说明选择理由；只能由用户观察或业务判断的内容使用人工验收。测试层级的选择不能为了方便而绕过用户实际使用的产品入口。

`test_code` 可以新增或修改测试专用的 fixture（测试准备工具）、测试数据工厂、mock/stub/fake（测试替代依赖）、测试辅助函数、测试专用样本和测试配置，但这些内容只能放在项目已有的测试目录或测试专用目录，不能修改产品代码。需要产品代码提供合理测试接缝时返回 `impl`，不能把测试开关、固定返回值或假数据写进生产代码。

`test_code` 门禁只检查当前工作流中测试计划标为 `自动化测试` 或 `自动化测试 + 人工验收` 的 `TC-xx`。每个这类测试项至少要在测试代码中有一个完整 `Workflow-Test` 标识；一个测试项可以对应多个测试函数。fixture、测试数据工厂、mock/stub/fake、辅助函数和测试配置不要求标识，已有且本阶段未修改的测试也不要求补标识；本阶段新增的测试函数不能脱离当前工作流的测试计划。

测试计划的“验收条件覆盖”表必须为每个 `TC-xx` 增加“测试方式”列，取值为 `自动化测试`、`人工验收` 或 `自动化测试 + 人工验收`。自动化测试项进入 `test_code` 和 `test_execution`；人工验收项由 `topic_acceptance` 核对；混合测试项由前两个阶段分别完成自己的部分。门禁根据该列判断哪些测试项必须有测试代码。

`Workflow-Test` 固定标识还必须写出“测试方式”和“测试层级”。“测试方式”必须与测试计划一致；“测试层级”由 AI 根据真实代码入口和需要证明的结果选择，例如单元测试、模块测试、集成测试、命令测试、接口测试或端到端测试。测试目标和代码入口必须使用开发者能直接理解的具体内容，不能只写编号或模块名称。

“测试入口”表示测试工具实际执行该测试的位置；“代码入口”表示被验证的产品代码位置，两者不能混用。正式执行前，AI 必须说明一条命令怎样覆盖当前测试项的全部测试入口，由用户确认后登记；程序保存登记时的全部入口和命令，并在结果门禁比较记录是否一致，但不假装能从任意测试工具命令文本中自动推断覆盖关系。缺少任一入口时不能登记，额外运行相关测试不能代替缺少的入口。
_Avoid_: 用产品代码入口冒充测试入口, 测试命令只覆盖部分标识, 只按测试文件猜所有函数都执行, 额外测试数量代替指定测试入口

测试追踪关系固定为“验收主题 → 验收条件 `AC-xx` → 测试项 `TC-xx` → 测试函数”。每个测试函数只绑定一个主要验收条件和一个主要测试项；一个验收条件可以由多个测试项覆盖，一个测试项可以由多个测试函数执行。多个测试函数需要相同准备过程时使用 fixture 或测试辅助函数共享，不把多个验收条件塞进一个测试函数来减少代码。

`traceability.md` 按每条 `AC-xx` 单独写测试项和测试结果。测试计划确认时，每一行只链接该 AC 自己的 TC，不能把同一主题的全部 TC 复制到每一行。同一主题中有自动化 AC 和纯人工 AC 时，自动化 AC 链接主题测试结果，纯人工 AC 写“无自动化测试项，转主题验收”。

`test_code` 的执行顺序固定为：先用 `workflow discuss` 加载两份测试代码规范；AI 再读取当前工作流的验收计划、测试计划、实施后记录、代码设计、当前产品代码、现有测试和测试配置；随后在聊天中逐项说明每个 `TC-xx` 对应的产品代码入口、当前逻辑、测试文件、测试场景、断言、测试依赖和隔离清理；用户确认测试代码落点后，才调 `workflow gate test_code --discuss-done`；第一道门通过后才写测试代码；写代码期间只做静态检查、语法检查、类型检查和 lint，不运行任何测试命令，也不能生成 `qa/<topic>_result.md`、更新 `traceability.md` 的正式测试结果或进入主题验收。写完后，`workflow gate test_code` 检查产品代码没有变化、每个自动化或混合 `TC-xx` 都有正确的固定追踪标识；存在自动化测试项时还必须确认测试代码确实变化，全部为人工验收时不强行要求测试代码变化。

`workflow gate test_code --confirmed` 时保存确认后的测试代码和测试配置哈希。进入 `test_execution` 后，测试代码或测试配置发生变化就返回 `test_code`；产品代码发生变化就返回 `impl`，再重新经过 `test_code`；测试代码本身有错误返回 `test_code`；产品实现不符合验收条件返回 `impl`；测试计划或预期结果不正确返回对应上游阶段。正式测试结果只对当时确认的测试代码和实施结果有效。

`test_execution` 按验收主题分别执行自动化测试，并为每个有自动化测试项的主题生成 `qa/<topic>_result.md`；所有主题的主题测试结果完成后，`regression_test` 再执行项目统一测试入口做最终全量回归。主题测试结果必须逐项对应本主题的自动化 `TC-xx`，记录测试入口、命令、实际结果和证据，不能用最终全量回归结果代替主题测试结果。

实施完成前无法确定的具体测试文件、测试函数、测试命令和证据位置，不回写已经确认的测试计划。`test_code` 讨论时根据真实代码确定测试落点并向用户说明；`test_execution` 执行后在 `qa/<topic>_result.md` 记录实际测试文件、测试入口、命令、结果和证据。只有测试范围、测试方式或预期结果本身发生变化时，才返回 `test_plan` 或更上游阶段修改计划。

`workflow discuss` 在 `test_code` 阶段加载两份阶段规范；阶段规范要求 AI 使用文件读取和代码搜索工具，读取当前工作流的验收索引、验收主题计划、测试索引、测试计划、实施索引、主题实施后记录、需求交付追踪表、代码架构文档、相关产品代码、已有测试和测试配置。项目代码不全部打印到命令行，AI 必须根据测试项读取相关代码路径和调用关系；读不到真实代码或无法确认测试入口时，不能猜测，按规则返回对应阶段。

测试代码哈希必须结构化包含测试文件、测试辅助代码、测试专用样本、独立测试配置、项目配置中的测试专用章节、统一测试入口脚本和项目级 `test_entry` 配置。混合配置文件必须使用 TOML、JSON 等结构化解析器区分测试配置和产品配置；测试专用部分允许在 `test_code` 修改，产品依赖、构建方式和其他产品配置发生变化时返回 `impl`。不能用字符串搜索猜配置章节，也不能因为整个混合配置文件发生变化就把测试配置和产品配置混为一类。

**Test Execution Stage** (`test_execution`):
只运行 `test_code` 阶段已经写好的测试代码，并按照 `qa/<topic>_plan.md` 记录真实测试结果。包含自动化或混合测试项的主题产出 `qa/<topic>_result.md`，纯人工主题不生成该文件，直接进入 `topic_acceptance`。任何应执行的自动化测试未通过或缺少有效执行记录，都不能生成正式结果或进入主题验收；阶段确认时按每条 AC 更新 `traceability.md` 的测试结果列，并记录 `test_result_hash`。

**Test Execution Material Split**（测试执行材料职责）:
`Template_Repository/qa/test.md` 只规定 `qa/<topic>_result.md` 的最终结构、字段、人工验收指引和上下游链接；`Standardized_Repository/qa/test.md` 只规定 AI 怎样调查、说明执行范围、登记命令、正式执行、分析失败、返回上游、整理结果和完成审查；代码门禁只执行其中能够明确判断的固定约束、状态和一致性检查。模板不写执行流程，规范不复制完整结果骨架，代码不声称能判断文字和业务证据质量。
_Avoid_: 模板和规范再次互换, 三处重复维护同一规则, 只写规范不做可判断门禁, 用代码假装判断人工语义

正式测试开始前，AI 必须读取当前验收主题、测试计划、测试代码标识、主题依赖和执行环境，在聊天中向用户说明每个主题准备执行的 `TC-xx`、全部测试入口、前置测试项、执行顺序、实际命令、环境条件，以及自动化完成后需要交给人工验收的内容。用户确认执行范围后才通过 `test_execution --discuss-done`；这一步不新增测试计划文档，也不提前生成测试结果。
_Avoid_: 不说明命令就直接正式执行, 把开发检查当成正式结果, 为执行前确认再建一份重复计划, 测试未执行就生成结果

用户确认执行范围后，AI 通过 `workflow test prepare` 登记每个自动化或混合 `TC-xx` 的测试入口、参数数组、依赖和“待执行”状态；程序把这些待执行任务写入 `.workflow_loop/state.json` 当前 `test_execution` 状态，并在 Journal 追加登记历史。`workflow gate test_execution --discuss-done` 只确认材料、主题、测试项、入口、命令和依赖登记完整，不执行测试；`workflow test run` 才实际运行尚无当前成功记录的命令，已经存在且没有失效的前置测试项或其他主题结果不重复执行；运行成功或失败后由程序更新当前状态和 Journal，AI 再根据成功记录生成结果文档。
_Avoid_: AI 直接编辑 state.json, discuss-done 偷偷执行测试, prepare 生成结果文档, run 使用未登记命令, 用结果文档反向代替命令登记

待执行命令必须以参数数组保存，并由程序在项目根目录直接启动，不经过 Shell 解释；登记内容禁止使用管道、命令连接、重定向、命令替换等 Shell 语法。需要多个步骤、环境准备或输出处理时，先写入项目测试脚本，再把脚本作为单一测试命令登记，使状态中的命令与实际执行完全一致。
_Avoid_: 把整段 Shell 字符串存入状态, 使用 shell=True, 在命令后拼接伪造通过输出, 执行目录随当前终端变化

每条待执行测试命令必须登记超时时间；AI 根据修改前基线、已有测试耗时或项目说明提出值，用户可在执行前调整，无依据时默认 600 秒。超时后程序终止该命令及其子进程，清除该测试项当前成功状态，不生成正式结果，并在 Journal 记录命令、实际等待时间和“执行超时”；AI 再判断是产品代码、测试代码、环境还是超时设置问题。
_Avoid_: 测试无限等待, 超时仍保留旧通过状态, 只终止父进程留下子进程, 把超时自动算成测试失败结果

`workflow gate test_execution` 必须检查当前测试代码已经确认、当前主题所需结果文档齐全、每个自动化或混合测试项在结果中唯一出现、每个测试项拥有覆盖全部当前 `Workflow-Test` 测试函数的有效成功执行记录、执行记录与文档中的主题/测试项/测试函数/命令/时间一致、结果顶部使用正确的自动化与人工状态、混合测试项包含人工验收指引、实际结果和证据具体可复核、索引链接正确，并拒绝失败、阻塞、未执行、失效执行记录和空泛结果。第三道门必须重新执行同样校验；代码检查固定事实，AI 和用户判断文字及证据质量。
_Avoid_: 只检查结果文件存在, 只检查手写通过字段, 执行记录和文档不一致仍放行, 混合测试项没有人工指引, 门二通过后文件改坏仍允许确认

门禁从当前工作流主题和测试计划计算“需要自动化结果的主题与测试项集合”，再与当前成功执行记录、`Workflow-Test` 测试入口和主题结果文档中的集合逐项比较；只有四者完全对应才通过。代码还检查前置测试项、退出码、状态失效、文档字段和索引链接；代码不能判断测试设计是否足够好、实际结果文字是否真正清楚或人工验收指引是否方便操作，这些由 AI 对抗性审查并由用户第三道门确认。
_Avoid_: 只比较文件数量, 把纯人工主题当成缺少测试结果, 让 AI 手工声明集合一致, 声称代码能判断业务证据质量

**Topic Test Result**（主题测试结果）:
一个验收主题在全部自动化测试实际执行并通过后生成的一份正式测试证据，内部逐条记录该主题的自动化或混合 `TC-xx`。一个测试项可以汇总多个测试函数；失败、阻塞或未执行时不生成正式主题测试结果，必须先返回对应阶段修正并重新执行。
_Avoid_: 每个测试函数单独生成结果文档, 只写主题总结果不写测试项, 失败或阻塞时仍生成正式结果, 部分测试失败仍把主题写成通过

主题测试结果顶部记录当前工作流编号、验收主题、总结果、实际执行时间和上游测试计划；每个 `TC-xx` 记录对应验收条件链接、实际测试文件与测试函数、实际执行命令、退出码、具体观察结果和可复核证据。测试代码和配置的确认哈希由程序状态保存，不要求 AI 手工抄入结果文档。
_Avoid_: 只写符合预期, 不记录实际命令和测试入口, 用人工填写的哈希代替程序绑定, 复制测试计划的预期结果冒充实际结果

文档顶部使用“自动化测试结果：通过”，不再使用容易误解的“测试结果：通过”；同时使用“人工验收状态：无需人工验收｜待主题验收”。全部测试项为纯自动化时写“无需人工验收”，存在任一混合测试项时写“待主题验收”。
_Avoid_: 自动化通过写成整个主题已经通过, 混合测试项遗漏人工验收状态, 用一个模糊总状态覆盖两个阶段

测试方式为“自动化测试 + 人工验收”时，主题测试结果只判定自动化部分通过，并明确把人工部分标为“待主题验收”。文档必须提供从验收计划推导出的人工验收指引，写清验收依据、验收对象、怎样检查、需要确认什么、自动化已经证明什么、仍需人工判断什么以及验收结果记录位置；不能新增验收要求，也不能声称整个测试项或主题已经验收完成。
_Avoid_: 自动化通过后代替用户验收, 只写待人工确认但不说明怎么确认, 在测试结果中发明新的验收标准, 把开发者实现完成当成用户验收通过

人工验收指引只在主题测试结果中准备问题和证据，真正的人工判断必须进入 `topic_acceptance` 后逐项等待验收人回答。没有验收人的明确回答不能生成 `acceptance/<topic>_result.md` 或通过主题验收门禁；人工发现问题时先返回对应阶段处理，不能把“待确认”改写成通过。
_Avoid_: 在 test_execution 提前替用户验收, 没有回答就生成验收结果, 把测试执行和主题验收重新合并, 人工发现问题仍继续推进

**Topic Test Execution**（主题测试执行）:
根据测试代码中的 `Workflow-Test` 标识找到当前验收主题各测试项对应的测试函数，并按主题精准执行；同一主题的测试函数可以合并为一条命令。项目统一全量测试留给 `regression_test`，不能把一次全量测试输出复制成多个主题测试结果。
_Avoid_: 用全量测试替代主题测试, 把无关测试当成当前主题证据, 没有执行当前主题测试函数就生成结果

没有前置主题且测试环境彼此隔离的主题可以并行执行；有前置主题时，必须先完成前置主题在本阶段需要执行的全部自动化测试，前置主题没有自动化测试项时本阶段无需等待；前置主题自动化测试失败时，依赖它的主题不执行。同一主题内部仍按测试项依赖顺序执行。并行由一个协调程序启动受控子进程，统一收集结果并顺序写入 State Snapshot 和 Journal，不使用多个 Subagent 同时修改状态。共享数据库、端口、设备、外部账号、固定临时目录或其他可变环境时，必须顺序执行。
_Avoid_: 用 Subagent 分头改状态和结果, 并行执行共享环境测试, 主题内部忽略依赖, 多个进程同时覆盖 state.json

主题测试默认最多同时执行两个独立主题；用户可以在执行前指定其他数量。项目级配置可用 `test_parallelism`（主题测试最大并行数量）保存默认值；没有配置时使用 2，只有一个主题或环境不隔离时使用 1。并行数量不能绕过主题依赖或共享环境限制。
_Avoid_: 不调查环境就并行, 固定并行数量无视项目资源, 用并行数量代替依赖判断, 让多个子进程直接写 State Snapshot

**Test Execution Return Rule**（测试执行退回规则）:
自动化测试失败时先判断原因：产品代码问题返回 `impl`，测试代码问题返回 `test_code`，测试范围或方式问题返回 `test_plan`，已明确产品设计对应的验收条件问题返回 `acceptance_plan`，产品规则缺失或需求变化返回 `spec`。临时环境问题留在 `test_execution` 解决后重跑；确认无法自动测试时返回 `test_plan`，由用户决定是否改为人工或混合测试。
_Avoid_: 把失败记录成可供验收使用的正式结果, 自动把失败算作通过, 不分析原因就固定返回同一个阶段

返回上游修改产品代码或测试代码后，只让当前主题和已经明确受影响的其他主题测试执行记录与结果失效；不默认重跑全部主题。统一测试入口或公共测试配置变化时全部主题失效；跨主题和已有功能影响由后续 `regression_test` 的最终全量回归统一检查。
_Avoid_: 任意代码变化都重跑全部主题, 当前主题修复后完全不管明确受影响主题, 用主题测试代替最终全量回归

主题测试结果失效时，程序删除受影响主题的 `qa/<topic>_result.md`，清除对应当前成功执行记录，并把 `traceability.md` 的测试结果列恢复为“待执行”；如果该主题已经生成验收结果，受影响主题的 `acceptance/<topic>_result.md` 也一并删除，最终回归状态恢复为未执行。`qa/index.md` 和 `acceptance/index.md` 保留预期结果文件入口，Journal 记录旧结果何时因何原因失效。不能只保留一份标记失效的旧通过文件继续放在当前产物位置。
_Avoid_: 旧通过文件留在当前目录误导后续阶段, 删除测试计划和索引, 失效后追踪表仍显示通过, 不记录失效原因

**Directly Affected Topic**（直接受影响主题）:
除当前失败主题外，本次修改与其共享同一产品行为、被修改代码位置、数据或状态约定、输入输出约定的其他验收主题。判断必须引用具体产品规则、实施记录、代码符号、`Workflow-Test` 代码入口或架构调用关系；同目录、同文件但不同逻辑、只有主题顺序关系或没有证据的“可能影响”不算直接受影响。
_Avoid_: 因为可能有关就扩大到所有主题, 只按文件名判断影响, 不调查代码和实施记录就填写, 把最终全量回归范围全部塞进主题重测

返回上游前，AI 必须调查当前修改位置和其他主题的实施记录、测试标识及共享代码，向用户说明每个直接受影响主题的具体依据；仍无法确定时由用户决定是否加入重测范围。`workflow return` 记录当前主题、直接受影响主题和返回原因，并只清除这些主题的执行记录与结果。

**Stage Return Command**（阶段返回命令）:
测试执行发现问题时，必须先用 `workflow return --to <阶段> --reason <具体原因>` 返回允许的上游阶段，再修改对应文件。命令负责切换当前阶段、记录原因、清除受影响主题的旧执行记录与结果、清零对应门禁并写入 Journal；临时环境问题不返回，留在 `test_execution` 恢复后重跑。
_Avoid_: 在错误阶段先改文件再等程序发现, 没有具体原因就返回, 手工修改 state.json, 临时环境问题错误退回产品或计划阶段

**Test Execution Record**（测试执行记录）:
由 Workflow Loop 的统一测试执行命令实际运行项目测试后写入当前 State Snapshot 的机器记录，绑定当前工作流、验收主题、测试项、测试入口、命令、执行时间、执行时长、退出码、执行环境以及当时的产品代码和测试代码版本；Journal 只追加保存执行历史。只有程序生成且退出码为零的当前有效记录才能支持正式主题测试结果，不新增独立凭证目录，AI 手写的命令或状态不能代替执行记录。
_Avoid_: 直接运行测试后手写通过, 根据 Markdown 猜测试已经执行, 测试失败仍生成有效记录, 代码变化后继续复用旧记录, 为同一事实新增独立凭证文件

State Snapshot 只保存当前仍可使用的成功执行记录，Journal 保存全部通过、失败、失效和重跑历史。同一测试入口重新成功时用新记录替换当前记录；任何失败执行都立即清除该测试项已有成功记录并标记为需要处理，防止当前状态显示通过而最新历史已经失败。修复后重新成功，才重新建立当前有效记录。
_Avoid_: State 保留旧通过而 Journal 最新是失败, 用历史成功代替当前执行, 失败后不清除正式通过依据, 把 Journal 历史当成当前状态

执行记录自动采集会影响测试结果的执行环境，包括本地或测试环境名称、操作系统、主要运行时版本、测试工具版本，以及真实外部服务、设备或样本；不记录账号、令牌、密码、个人绝对路径等敏感或不可移植信息。AI 不手工猜测环境版本。
_Avoid_: 完全不记录执行环境, 手工编造版本, 把个人目录和密钥写入结果, 记录与测试结果无关的整机信息

每条测试执行记录只绑定一个 `TC-xx`；同一测试项的多个测试函数可以放在同一条命令中，也可以分成多条命令，但所有必需命令都必须成功。不同测试项不能混在同一条执行记录中。
_Avoid_: 一条执行记录混合多个测试项, 一个测试项只执行部分必需测试函数, 用无关测试函数补足记录数量

一个测试项当前拥有的全部 `Workflow-Test` 测试函数都属于必须执行范围；测试执行记录必须覆盖这些函数，少执行任一函数都不能判定该测试项通过。测试项新增、删除或改名测试函数后，原执行记录失效。
_Avoid_: 只挑部分测试函数执行, 用一个通过的函数代表整个测试项, 测试函数变化后继续复用旧执行记录

测试命令失败时不生成正式主题测试结果、不写入当前有效执行记录，也不更新追踪表；Journal 只记录验收主题、测试项、命令、执行时间、退出码和失败状态，终端输出只供当次诊断。该失败历史只说明为什么返回上游，不能被门禁或验收当成通过证据。
_Avoid_: 失败后仍写结果文档, 把失败 Journal 当成有效执行记录, 完全不记录返回原因, 把大段失败输出复制进正式测试结果

测试失败后，程序不根据退出码自动决定返回阶段；它停止失败测试项的后续依赖，允许其他独立主题继续执行，并在终端输出失败主题、测试项、命令、退出码和具体错误。AI 必须调查测试代码、产品代码、测试计划和产品设计，向用户说明原因与建议返回阶段，用户确认后才调用 `workflow return`；临时环境问题留在当前阶段处理。
_Avoid_: 失败一律返回 impl, 程序猜测产品或测试代码责任, 不调查就修改文件, 失败主题阻塞所有独立主题

程序只负责执行测试和保存机器事实，AI 根据当前有效执行记录生成 `qa/<topic>_result.md`，把实际结果和人工验收指引写成人能理解的内容；AI 不得改写执行记录中的命令、测试函数、执行时间或退出码。`test_execution` 门禁必须核对结果文档和执行记录一致，既不让程序直接生成空泛说明，也不相信没有执行记录的 AI 手写结果。
_Avoid_: 程序只生成一份没人能理解的原始日志, AI 修改机器事实, 没有执行记录就生成结果, 文档和执行记录不一致仍放行

**Topic Acceptance Stage** (`topic_acceptance`):
先确认对应主题的测试结果已经通过，再按照 `acceptance/<topic>_plan.md` 逐条核对用户可见结果，用户确认后产出 `acceptance/<topic>_result.md`。程序门禁不能让主题验收绕过测试执行；阶段确认时只更新主题验收结果列，并记录 `acceptance_result_hash`。修 bug 在这里更新为“主题验收通过，待全量回归”，不能在测试执行阶段提前关闭缺陷。

这三个阶段不再由一个 `topic_execution` 阶段统筹，也不创建 `topic_execution` 汇总文档。测试代码、测试结果和主题验收结果分别使用自己的规则和门禁；固定条件由 Python 代码检查，不能只靠 Markdown 提醒 AI。
_Avoid_: 测试代码还没写就执行测试, 测试未通过就开始主题验收, 用主题验收结果代替测试结果, 用一个协调阶段混合三种不同工作

**Regression Test Stage** (`regression_test`):
全部主题完成后，`regression_test` 直接执行项目配置的统一测试入口。退出码为 `0` 才算通过；程序把执行状态写入 `state.json` 和 `journal.jsonl`，并更新 `traceability.md`。没有测试入口、入口无法启动、测试失败或执行超时，都不能进入整体验收。bugfix 回归失败时把缺陷状态改为“回归失败，重新处理中”。这些固定条件直接写在代码中，不依赖人工填写结果文档。

**Overall Acceptance Stage** (`overall_acceptance`):
最终全量回归通过后，由用户确认整个需求是否完成。程序门禁重新检查当前工作流的全部主题验收结果和最终全量回归结果都已经通过；第三道门记录用户是否明确接受整个需求的交付结果。该阶段不生成 `acceptance/overall_result.md`，也不建立整体验收产物模板或只重复固定门禁的独立规范文件。用户确认结果写入 State Snapshot、Journal 和 `traceability.md`；bugfix 只有在这里通过后才把缺陷记录及 `bug/index.md` 改为“已修复并验收”。任一前置结果或用户确认不满足时，不能进入详细代码设计更新。

`overall_acceptance` 不修改代码设计文档。唯一负责根据最终代码、测试和验收结果更新 `spec/architecture_code_design.md` 的 Stage 是后续 `update_code_design`。
_Avoid_: 为整体验收重复生成汇总文档, 把最终全量回归等同于用户整体验收, AI 根据测试通过自动代替用户确认, 在 overall_acceptance 修改代码设计文档, 未完成整体验收就进入 update_code_design

**Verification Invalidation** (验证结果自动失效):
当前流程骨架先实现顶层失效：验收计划变化时退回 `acceptance_plan`；测试计划变化时退回 `test_plan`；实施代码或实施记录变化时退回 `test_code`；主题测试结果变化时退回 `topic_acceptance`；主题验收结果变化时退回 `regression_test`；最终全量回归结果变化时退回 `regression_test`。程序同时清零该阶段及其后续阶段的门禁和旧哈希，并把 `current_stage` 移到最早需要重做的阶段，stdout 打印对应的下一条命令。
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
