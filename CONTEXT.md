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
项目级持久事实，记录在 `.workflow_loop/project.json` 的 `project_design_initialized` 字段中，不放进会被新 Run 覆盖的 `state.json`。安装时初始为 `false`。首次处理已有代码项目时，`product_change` / `bugfix` 共享前置 `project_design_init` Stage；它根据代码建立 `spec/product.md`、多个 `spec/feature_<english-name>.md` 与 `spec/architecture_code_design.md`，三类产物通过门禁并由用户确认后才写为 `true`。若在该 Stage 完成前作废，字段保持 `false`。`from_scratch` 不走该前置 Stage，但在 `spec` 与初步 `code_design` 均确认完成后同样写为 `true`。
_Avoid_: 用架构文件是否存在代替初始化状态, 把字段放进单轮 state.json, 只生成架构文档就视为项目设计已初始化, 安装时直接写 true

**Bugfix Intent** (修 bug):
定位并修复一个具体缺陷的工作意图。
_Avoid_: bugfix scenario（旧四选一场景）

**Stage Path** (阶段路径):
本次 Workflow Run 将顺序经过的 stage 列表。项目安装是开工硬前置；安装完成后，路径由「工作意图」与 `project_design_initialized`（项目设计已初始化）等项目事实组合生成，而不是从固定四场景枚举取出。
_Avoid_: Scenario stages, pipeline template（若暗示四条平行流水线）

**Stage Path Composition** (路径拼法):
- 未安装：必须先在项目根执行官方安装脚本；日常 CLI 只做异常保护，不在 `start` 状态检查中提供安装分支
- **from_scratch（从零做）**：先清场（删除旧设计/过程产物；保留规范与模板仓库）→ `spec`（产品设计 + 功能拆分）→ `code_design`（初步，不可因旧文件跳过）→ `spike`（可选）→ `plan`（制定实施计划）→ `acceptance_plan`（制定验收计划）→ `test_plan`（制定测试计划）→ `impl`（执行实施）→ `test`（执行测试）→ `acceptance`（最终验收）→ `update_code_design`（详细落地，强制；与其它意图末环同名）
- **product_change（改产品）**：若 `project_design_initialized=false`，先走 `project_design_init`；之后统一走 `spec`（重新设计产品 + 功能拆分）→ `revise_code_design`（设计期：按新设计改架构图）→ `spike`（可选）→ `plan` → `acceptance_plan` → `test_plan` → `impl` → `test` → `acceptance` → `update_code_design`
- **bugfix（修 bug）**：若 `project_design_initialized=false`，先走 `project_design_init`；之后走 `reproduce` → `fix_plan` → `acceptance_plan` → `test_plan` → `impl` → `test` → `acceptance` → `update_code_design`（详细强制；无结构变化须在该 stage 显式确认，不可省略）
- `project_design_initialized=true`：改产品/修 bug 跳过共享初始化阶段；文件是否存在不能单独决定跳过。任何意图不得跳过末段详细架构 Stage
- 共享后半截：实施/修复计划 → `acceptance_plan` → `test_plan` → `impl` → `test` → `acceptance` → `update_code_design`
_Avoid_: 修 bug 可无设计基线, 写完测试计划就视为测试通过, 写完验收计划就视为验收通过, impl 后直接更新架构而不执行测试和验收, 旧四场景平行流水线, 改产品保留 requirement/product_update/feature_split 三段式流程

**Architecture Document** (架构文档):
固定产物 `spec/architecture_code_design.md`（code_design）。已经安装 Workflow Loop 并进入正式开发路径的项目，必须有该文档；不是可有可无的附件。
_Avoid_: 可长期缺失的架构说明, 仅口头架构

**Architecture Doc Phases** (架构文档双阶段):
同一份架构文档的两种完成度，不是两个无关文件：
1. **初步架构**（前期设计）：路径前段产出或补齐，服务计划与实施前的共同理解。从零做时顺序固定为**先产品设计与功能拆分、后初步架构**（先定做什么，再定怎么搭）；首次接入已有代码项目时由 `project_design_init` 与产品、功能基线一起从代码反推建立。
2. **详细架构**（代码通过测试与最终验收后）：`acceptance` 之后强制更新/写全，反映最终被验证和接受的真实结构
Stage 命名：从零做的前段初步架构为 `code_design`；存量项目首次初始化为 `project_design_init`；改产品设计期为 `revise_code_design`；**所有意图** 最终验收后详细收尾一律 `update_code_design`。废弃 `generate_code_design`（初步阶段已可能创建同文件，末环不是“首次生成”语义）。
_Avoid_: 只在 impl 后才第一次写架构, 未测试验收就写最终详细架构, 有初步无详细收尾, 有详细却声称前期不需要图

**Project Design Init Skip** (项目设计架构初始化跳过):
仅对 `product_change` / `bugfix`：读取 `.workflow_loop/project.json` 的 `project_design_initialized`。为 `true` 时跳过共享前置 `project_design_init`；为 `false` 时必须执行。不得再用 `spec/architecture_code_design.md` 或其它单个文件是否存在决定跳过。这不表示本轮可以不改架构图：改产品在 `spec` 后必须有 `revise_code_design`，任何意图在测试与最终验收后必须有详细 `update_code_design`。不适用于 `from_scratch`。
_Avoid_: 用架构文件存在代替项目初始化标记, 从零做进入存量初始化, 跳过初始化被理解成整轮不改架构, 因已有架构而跳过末尾详细更新


**Architecture Gate Marks** (架构门禁标记):
State Snapshot 中记录架构完成度，至少区分 `architecture.preliminary_done`（初步架构完成）与 `architecture.detailed_done`（详细架构完成）。前段架构 Stage 用户确认后置 preliminary；最终 `acceptance`（验收执行）通过后的架构 Stage 确认后置 detailed。文件存在只是必要条件；**不得**因 `spec/architecture_code_design.md` 已存在而自动跳过详细架构收尾。
_Avoid_: 仅用文件存在判定详细完成, 初步与详细共用一个模糊 done 位



**Scenario** (场景，旧模型):
历史上把资产状态与工作意图捏成四个互斥入口（new-project / existing-no-workflow / bugfix / product-mod）的错误模型。新模型中不再作为主入口概念。
_Avoid_: 继续用 scenario 指“本次要做什么”

**Entry** (入口，旧模型):
旧 CLI 里 `start --entry` 的四选一键。新模型中不应再表示互斥场景；若保留命令形态，语义需重定义为“意图 + 状态”的启动参数，而不是场景 ID。
_Avoid_: 把 entry 当场景主键

**Stage**:
路径上的一个具名环节（如 spec、spike、plan、impl、test、acceptance）；内部走讨论与门禁循环。
_Avoid_: Step（易与 stage 内 7 步混淆）, phase（除非明确同义）

**Gate** (门禁):
阻止进入下一 Stage 的代码关卡（讨论完毕 / 产出校验 / 用户确认）。强制力放在门禁，不在每轮唠叨。
_Avoid_: Checkpoint（若不含强制）, validation alone

**Gate Policy** (门禁策略，第一版):
每个正式 Stage 仍保留**三道门、顺序硬性**（与现实现一致）：
1. 讨论完毕：`gate <stage> --discuss-done`
2. 代码/产物校验：`gate <stage>`
3. 用户确认：`gate <stage> --confirmed`
入口与路径模型重做时**不砍门禁协议**。可选 spike 的 `gate spike --skip` 是额外跳过动作，不取消其它 stage 的三道门，也不把三道门合并或改成“校验过即当用户确认”。`test`（测试执行）与 `acceptance`（验收执行）是三种意图的强制 Stage，不提供 `--skip`；自动测试不可用时可执行人工测试并记录证据，环境阻塞或用户未验收不得按通过处理。
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
本局功能/修复的命名字符串，供 `plan/`、`acceptance/`、`qa/` 等产物文件名与 index 使用。计划与结果分别命名为 `acceptance/<topic>_plan.md`、`acceptance/<topic>_result.md`、`qa/<topic>_plan.md`、`qa/<topic>_result.md`。**写入时机（维持现状）**：
- `from_scratch` / `product_change`：在 **`plan`** stage 用户确认通过（或该 stage 推进落盘）时写入 `state.topic`
- `bugfix`：在 **`fix_plan`** stage 同样时机写入
`start` **不**强制 `--topic`；spec / reproduce / 前段架构等可以尚无 topic。未定时门禁与路径不因缺 topic 而假装已有；需要主题的 stage 在讨论/产出中定下后再写入。
_Avoid_: start 强制 --topic, 每个意图第一环就定 topic, 无 plan/fix_plan 却提前写死 topic


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
从零做 / 改产品路径上的风险验证 Stage。默认在路径中。用户确认不需要穿刺后，通过显式门禁动作跳过（例如 `workflow gate spike --skip`）：state 记 skipped、journal 记跳过并推进下一 Stage；不要求 throwaway 与完整结论文档。不能靠 AI 自觉删 stage；不在 start 时默认从路径抹掉 spike。
_Avoid_: 固定必做无法跳过, start --no-spike 作为唯一跳过方式, AI 自行跳 stage

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
- **删除**（仅项目根产物侧）：`spec/`、`plan/`、`acceptance/`、`qa/`、`impl/`、`bug/` 等目录下由 workflow 约定写出的设计/过程文档（如 `spec/product.md`、`spec/architecture_code_design.md`、`spec/feature_*.md`、`plan/*` 等）。
- **不删除**：`.workflow_loop/Template_Repository/` 与 `.workflow_loop/Standardized_Repository/` 全部内容（含其中的 `spec/`、`plan/` 等**提示词/规范**子目录）；`.workflow_loop/project.json` 文件本身（只更新初始化字段）；源代码、`.git`、与设计产物无关的项目文件；`.workflow_loop/` 运行时骨架本身（仅重建本次 Run 的 state，不拆模板仓库）。
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
`product_change` 在 `spec`（产品设计与功能拆分）之后、`plan` 之前必须经过 `revise_code_design`：按变更后的产品设计改架构图。代码实施、测试和最终验收完成后另走 `update_code_design` 做详细落地。两次强制，名称分开以免 state 主键冲突。
_Avoid_: 改产品只在末尾改一次架构, 路径上两个同名 update_code_design, 改设计却不改架构图

**Bugfix Architecture Update** (修 bug 时的架构):
`bugfix` 在 `test` 与最终 `acceptance` 通过之后必须经过 `update_code_design`。若 fix_plan/实施判定不涉及结构变更，仍须走该 Stage，并在门禁中显式确认「无结构变化」；涉及结构则必须改架构图。不可因“只是小 bug”省略测试、验收或架构 Stage。
_Avoid_: 修 bug 默认跳过架构收尾, 无结构变化就不跑 stage

**Revise Code Design Stage** (`revise_code_design`):
改产品路径上、`spec` 产品设计与功能拆分之后的设计期改架构 Stage。与末段 `update_code_design`（详细落地）名称分离，避免同一 Run 内 stage 名冲突。
_Avoid_: 与 update_code_design 共用同一 stage 名当主键

**Project Design Init Stage** (`project_design_init`):
首次处理已有代码项目时，为 `product_change` / `bugfix` 共享的前置 Stage，中文名“项目设计架构初始化”。角色为“存量产品与架构分析师”；同时加载 `spec/spec.md` 与 `code_design/code_design.md` 两组提示词和规范。根据现有代码及可运行行为一次建立：`spec/product.md`、多个 `spec/feature_<english-name>.md`、`spec/architecture_code_design.md`。门2必须同时校验三类产物，门3确认后写 `project_design_initialized=true` 与 `architecture.preliminary_done=true`。该 Stage 完成前作废不得写 true。
_Avoid_: 只生成 architecture_code_design.md, 拆成彼此可能不一致的产品反推和架构反推两轮, 用旧文档存在冒充本次初始化完成

**Product Spec Stage** (`spec`):
统一负责“产品设计 + 功能拆分”。角色为产品设计师；加载 `.workflow_loop/Template_Repository/spec/spec.md` 与 `.workflow_loop/Standardized_Repository/spec/spec.md`；产物为 `spec/product.md` 与多个 `spec/feature_<english-name>.md`。`from_scratch` 中负责从零建立；`product_change` 中负责基于现状重新设计，可新增、修改或删除功能文档。门2必须证明产物属于本 Run：阶段进入时记录相关文件路径与内容哈希，校验时比较前后变化。`from_scratch` 要求新建 product.md 且至少新建一个功能文档；`product_change` 要求 product.md 有变化且至少一个功能文档新增、修改或删除。
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
项目根下的 `spec/product.md`，固定包含九章：产品背景与目标、术语、用户与场景、产品边界、产品组成与主要流程、产品通用规则、产品功能、相关文档、修改记录。其中“产品组成与主要流程”只说明产品各部分的关系和用户在功能间怎样流转，不写代码模块、接口或数据库结构；“产品功能”只放功能名称、一句话说明、对应场景和详细功能文档链接。“产品边界”单独说明整个产品支持和不支持什么，不代替各功能文档中的“功能边界”。每个功能的全部规则和细节放在独立功能文档中。“相关文档”可链接代码设计文档，不链接尚未生成或持续变化的开发计划。
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
项目根下的 `spec/feature_<english-name>.md`，其中 `<english-name>` 使用小写英文单词并以下划线连接，文件正文继续使用中文，文档一级标题固定为 `# 【功能】<功能名称>`，`spec/product.md` 中的功能名称和链接文字也使用中文。代码校验只接受 `feature_*.md`，不兼容旧的 `功能*.md` 命名；已有中文文件必须删除或重命名。每个文件只说明一个功能的用户可见设计，固定包含“背景、场景、功能边界、规则、使用过程、异常情况”六部分；由 `spec/product.md` 链接进入，不写程序类、接口、数据库、模块划分等技术实现。“使用过程”若没有用户操作，则写系统在什么条件下自动执行以及产生什么结果。
_Avoid_: 继续接受 功能*.md, 两套功能文件命名并存, 多个无关功能写在同一文件, 重复整份产品总说明, 缺少 product.md 入口, 混入代码设计或施工步骤

**Feature Background**（功能背景）:
功能说明文档中的“背景”说明产品中出现了什么具体需求，因此设计这个功能。它交代功能的需求来源和设计原因，不机械要求先写“目前存在什么问题”，不重复整份产品背景，也不写技术实现或开发过程。
_Avoid_: 为功能虚构问题, 用技术缺陷代替产品需求, 重复整份产品背景, 在背景写实现方案

**Requirement Discussion Process**（需求讨论过程）:
产品设计规范提示词规定的 AI 工作过程，不是用户可独立使用的产品功能，也不生成 `spec/feature_*.md` 功能文档。它负责调查事实、逐个确认决定、总结共同理解，并在用户确认后触发生成产品设计文档。
_Avoid_: 把需求讨论过程当成产品功能, 为提示词内部流程生成独立功能文档

**Feature Boundary Rule**（功能拆分标准）:
一份功能文档对应一件可以独立完成的用户事情；为了完成同一件事而共同使用的搜索、筛选、翻页等操作可留在同一功能中，目的、规则或异常处理明显不同的事情应拆开。功能不按按钮数量、页面数量或程序模块划分。
_Avoid_: 一个按钮一份功能文档, 整个产品只有一份巨型功能文档, 按代码模块拆产品功能

**Acceptance Plan Stage** (`acceptance_plan`):
制定“什么算完成”的验收计划，不执行最终验收。角色为验收计划制定者；提示词与规范分别为 `.workflow_loop/Template_Repository/qa/acceptance_plan.md`、`.workflow_loop/Standardized_Repository/qa/acceptance_plan.md`；产物为 `acceptance/<topic>_plan.md`。门2校验文件属于当前 Run、文件名与 `state.topic` 一致、每条验收条件可判定且覆盖本次实施计划。
_Avoid_: 继续用 acceptance 名称表示计划制定, 写完验收计划就视为已验收, 只检查 acceptance 目录任意 md

**Test Plan Stage** (`test_plan`):
把验收条件转换为可执行测试范围、步骤、回归项、边界与证据要求，不实际执行测试。角色为测试计划制定者；提示词与规范分别为 `.workflow_loop/Template_Repository/qa/test_plan.md`、`.workflow_loop/Standardized_Repository/qa/test_plan.md`；产物为 `qa/<topic>_plan.md` 并更新 `qa/index.md`。门2必须校验测试计划属于当前 Run、文件名与 topic 一致，并证明每条验收条件至少被一个测试项或明确的人工验收项覆盖。
_Avoid_: 继续用 qa 名称混淆计划与执行, 测试计划不覆盖验收条件, 只硬校验 qa/index.md

**Implementation Stage** (`impl`):
执行已经确认的实施/修复计划并修改真实代码，不再承担“再制定一份实施计划”的职责。角色为实施执行者；提示词与规范保持 `.workflow_loop/Template_Repository/impl/impl.md`、`.workflow_loop/Standardized_Repository/impl/impl.md`；产物为实际代码修改及 `impl/<topic>.md` 实施记录。门2校验实施记录与当前 Run/topic 对应，并记录当前代码与实施记录内容哈希。门3通过后进入 `test`，不得直接进入 `update_code_design`。
_Avoid_: impl 仍只写计划不改代码, plan 与 impl 重复制定计划, impl 后直接收工或更新详细架构

**Test Execution Stage** (`test`):
按照 `qa/<topic>_plan.md` 执行全部必要测试并记录证据。角色为测试执行者；提示词与规范分别为 `.workflow_loop/Template_Repository/qa/test.md`、`.workflow_loop/Standardized_Repository/qa/test.md`；产物为 `qa/<topic>_result.md` 并更新 `qa/index.md`。结果必须绑定当前代码/实施记录哈希与测试计划哈希，逐项记录 pass / fail / blocked 及命令、日志、截图或人工测试证据。门2要求当前 Run 的所有必测项通过且无未解决 fail/blocked；门3仍由用户确认。失败必须回到 `impl`，修改后旧测试与验收状态失效并重新完整测试。该 Stage 强制，不提供 `--skip`。
_Avoid_: 写测试计划冒充测试执行, 只写“测试通过”无逐项证据, 修代码后沿用旧测试结果, blocked 当通过, 跳过测试

**Acceptance Execution Stage** (`acceptance`):
在测试通过后，按照 `acceptance/<topic>_plan.md` 执行最终验收。角色为验收执行者；提示词与规范分别为 `.workflow_loop/Template_Repository/qa/acceptance.md`、`.workflow_loop/Standardized_Repository/qa/acceptance.md`；产物为 `acceptance/<topic>_result.md`。结果必须绑定验收计划哈希与最新测试结果哈希，并逐项给出可复核证据。门2要求全部适用验收项通过且无阻塞；门3必须由用户明确确认，AI 不得自动代验收。实现不符合计划时回到 `impl`，之后重新走 `test` 与 `acceptance`；验收计划错误、遗漏或不可判定时回到 `acceptance_plan`，修改后重新检查 `test_plan` 并使旧结果失效。该 Stage 强制，不提供 `--skip`。
_Avoid_: AI 自动替用户验收, 测试未通过就验收, 验收失败只改结果文件, 修改验收标准后沿用旧测试或验收结果, 跳过最终验收

**Verification Invalidation** (验证结果自动失效):
通过状态只对绑定的上游内容有效。`impl` 的代码或实施记录变化时，清零 `test` 与 `acceptance` 的门禁状态；`test_plan` 变化时，清零测试与验收状态；`acceptance_plan` 变化时，清零验收状态并把 `test_plan` 退回待检查。新测试结果绑定当前代码/实施记录及测试计划哈希；新验收结果绑定当前测试结果及验收计划哈希。失效动作写入 State Snapshot 与 Journal，不能只靠 AI 记忆。
_Avoid_: 上游变化后下游仍显示 done, 仅比较文件存在不比较内容, 失败重试沿用旧结果, 不记录失效原因

**Update Code Design Stage** (`update_code_design`):
所有工作意图在 `test` 通过且最终 `acceptance` 经用户确认之后的详细架构收尾 Stage。写入/更新同一文件 `spec/architecture_code_design.md`，用户确认后置 `architecture.detailed_done`。从零做、改产品、修 bug 末环同名；不再使用 `generate_code_design`。
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
