# 【实施】0.2.0 在 GitHub 和 PyPI 完成正式发布

- 工作流编号：2026-08-06-0659-product_change
- 验收主题：0.2.0 在 GitHub 和 PyPI 完成正式发布

## 1. 实施依据

| 依据类型 | 具体内容 | 文档位置 |
|---|---|---|
| 产品设计 | 当前公开版本统一为 `0.2.0`；普通分支和手动任务不公开发布；只有最终 `v0.2.0` 标签任务在验证成功后发布 PyPI 和 GitHub Release；历史 `0.1.0` 保持不变 | [产品总说明：产品通用规则](../spec/产品总说明.md#6-产品通用规则)、[安装到项目：规则](../spec/功能_安装到项目.md#4-规则) |
| 验收条件 | AC-01 至 AC-05：版本身份统一、标签发布边界、最终任务成功、两个公开渠道内容一致、公网安装和旧版本更新正确 | [验收条件](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#4-验收条件) |
| 测试项 | TC-01 至 TC-07：本地身份、发布前空缺、非标签发布边界、流水线结构、真实标签任务、公开内容和公网安装更新 | [测试项](../qa/0_2_0_在_GitHub_和_PyPI_完成正式发布_测试计划.md#1-验收条件覆盖) |
| 代码设计 | 沿用现有公开发布适配器（发布配置）：版本核对 → 全量测试 → 构建 → 四种托管环境验证 → PyPI → GitHub Release；不新增模块、函数或架构层 | [公开发布身份与安装入口](../spec/代码架构设计.md#58-公开发布身份与安装入口) |
| 穿刺结论 | 现有 `0.1.0` 发布链路已经在 GitHub 和 PyPI 使用过；当前公开的 `0.2.0` 尚不存在，技术不确定性已在 spike（技术验证）阶段确认可跳过 | [本轮差异与实施边界](../spec/代码架构设计.md#8-产品设计与代码实现的差异) |

## 2. 实施前计划

### 2.1 预期产品结果

用户从 `0.2.0` 的 GitHub Release 或 PyPI 安装入口取得的命令、项目安装标记和六个维护脚本都使用同一版本身份。源码、README 和发布流水线也统一为 `0.2.0`；只有准确的 `v0.2.0` 标签可以创建公开版本。现有工作流行为不变，已经发布的 `0.1.0` 不被覆盖或重发。

### 2.2 代码修改计划

| 顺序 | 文件 | 类、函数或配置项 | 当前逻辑 | 计划修改的具体逻辑 | 数据、状态或输出变化 | 对应验收条件和测试项 | 前置步骤 |
|---|---|---|---|---|---|---|---|
| 1 | `pyproject.toml` | `[project].version`（项目元数据版本） | Python 包版本为 `0.1.0` | 改为 `0.2.0`，其余包名、依赖、入口和元数据不变 | 构建出的 Python 分发包版本变为 `0.2.0` | AC-01；TC-01、TC-06 | 无 |
| 2 | `uv.lock` | `workflow-loop` 包记录 | 锁定的当前项目版本为 `0.1.0` | 把当前项目包记录更新为 `0.2.0`，不改依赖解析结果 | 本地同步和构建读取到 `workflow-loop 0.2.0` | AC-01；TC-01 | 1 |
| 3 | `src/workflow_loop/__init__.py` | `__version__`（包版本常量）、`PRODUCT_IDENTITY`（产品身份） | 运行版本和命令身份为 `0.1.0` | 把 `__version__` 改为 `0.2.0`；保留产品名和身份拼接方式 | `workflow --version` 输出 `workflow-loop 0.2.0` | AC-01、AC-05；TC-01、TC-07 | 1 |
| 4 | `src/workflow_loop/cli.py` | `main()`（命令行入口）中的 `--version` 注释 | 注释仍写“输出 workflow-loop 0.1.0” | 更新注释中的当前版本说明；不改参数解析和输出实现 | 只修正文档注释，命令行为由共享版本常量改变为 `0.2.0` | AC-01；TC-01 | 3 |
| 5 | `src/workflow_loop/project.py` | `INSTALLER_VERSION`（安装器版本）、安装状态说明注释 | 运行值已从 `__version__` 读取，但注释写死 `0.1.0` | 更新注释为 `0.2.0`；保留运行时共用 `__version__` 的逻辑 | 项目骨架检查、安装状态说明与当前版本一致 | AC-01、AC-05；TC-01、TC-07 | 3 |
| 6 | `install.sh` | `PRODUCT_VERSION`（安装脚本版本） | macOS/Linux 安装脚本安装 `workflow-loop==0.1.0` | 改为 `0.2.0`；保留确认、预检、回滚、安装事务和固定 uv 资产逻辑 | 脚本安装 `workflow-loop==0.2.0`，写入项目版本 `0.2.0` | AC-01、AC-03、AC-05；TC-01、TC-04、TC-07 | 3 |
| 7 | `install.ps1` | `$ProductVersion`（PowerShell 安装脚本版本） | Windows 安装脚本安装 `workflow-loop==0.1.0` | 改为 `0.2.0`；保留 PowerShell 7 和 Windows PowerShell 5.1 共用的安装流程 | Windows 两种 PowerShell 安装到 `0.2.0` | AC-01、AC-03、AC-05；TC-01、TC-04、TC-07 | 3 |
| 8 | `update.sh` | `SCRIPT_VERSION`（更新脚本版本） | macOS/Linux 更新脚本的当前脚本版本为 `0.1.0` | 改为 `0.2.0`；保留目标版本解析、公开来源检查和项目数据保留逻辑 | 从旧版本更新时可以取得并写入 `0.2.0` | AC-01、AC-03、AC-05；TC-01、TC-04、TC-07 | 3 |
| 9 | `update.ps1` | `$ScriptVersion`（PowerShell 更新脚本版本） | Windows 更新脚本的当前脚本版本为 `0.1.0` | 改为 `0.2.0`；保留两种 PowerShell 的更新和进程清理逻辑 | Windows 更新后项目版本为 `0.2.0`，业务文件保持不变 | AC-01、AC-03、AC-05；TC-01、TC-04、TC-07 | 3 |
| 10 | `uninstall.sh` | `PRODUCT_VERSION`（卸载脚本调用版本） | macOS/Linux 卸载脚本调用 `workflow-loop==0.1.0` | 改为 `0.2.0`；保留项目卸载、全局卸载和业务文件保留逻辑 | `0.2.0` 发布附件中的卸载脚本调用正确包版本 | AC-01、AC-03、AC-04；TC-01、TC-04、TC-06 | 3 |
| 11 | `uninstall.ps1` | `$ProductVersion`（PowerShell 卸载脚本调用版本） | Windows 卸载脚本调用 `workflow-loop==0.1.0` | 改为 `0.2.0`；保留项目卸载、全局卸载和进程清理逻辑 | Windows `0.2.0` 发布附件中的卸载脚本调用正确包版本 | AC-01、AC-03、AC-04；TC-01、TC-04、TC-06 | 3 |
| 12 | `README.md` | 当前安装章节和 GitHub Release 下载地址 | 当前安装章节和固定下载地址指向 `0.1.0` | 标题、三个公开安装命令和固定版本说明改为 `0.2.0`；历史版本说明和更新示例规则不改 | 用户复制公开安装命令会取得 `v0.2.0` 附件 | AC-01、AC-04、AC-05；TC-01、TC-06、TC-07 | 6、7 |
| 13 | `.github/workflows/release.yml` | 触发标签、`PRODUCT_VERSION`、版本核对、发布条件、发布名称、正文和附件 | 发布任务只接受 `v0.1.0`，版本核对和公开发布文本也写死 `0.1.0` | 全部当前发布身份改为 `0.2.0`/`v0.2.0`；保持手动任务和普通分支不发布、作业依赖、四种托管环境验证、PyPI 已存在阻断及六个附件 | 只有最终 `v0.2.0` 标签在所有前置作业成功后上传 PyPI 并创建 `Workflow Loop 0.2.0` | AC-01 至 AC-04；TC-01 至 TC-06 | 1、3、6 至 12 |

完成上述代码修改后，使用现有 `_set_project_installer_version()`（设置项目安装版本）入口把当前仓库 `.workflow_loop/project.json` 的 `installer_version`（安装版本）从 `0.1.0` 改为 `0.2.0`。该文件属于工作流项目状态，不作为实施代码进入回退清单；只改安装版本字段，项目设计状态、主题历史、测试入口和文件标识映射保持不变。发布前检查、远程标签推送、GitHub Actions（GitHub 自动任务）和 PyPI 公开发布属于后续测试执行，不在本实施阶段执行。测试代码的版本期望值和发布查询逻辑在下一阶段 `test_code`（测试代码）单独更新。

### 2.3 开发检查计划

| 检查命令或方法 | 检查范围 | 预期观察结果 |
|---|---|---|
| `rg -n '0\\.1\\.0|v0\\.1\\.0'` 结合受控文件清单核对 | 当前版本元数据、脚本、README、源码注释和发布配置 | 受控当前文件不再保留 `0.1.0`；历史文档、测试夹具和回退副本不在本实施修改范围 |
| `.venv/bin/python -m compileall -q src/workflow_loop` | Python 源码语法 | 编译成功，无语法错误 |
| `.venv/bin/python -m workflow_loop.cli --version` | 命令公开身份 | 输出严格为 `workflow-loop 0.2.0`，标准错误为空 |
| 解析 `pyproject.toml`、`uv.lock`、`.workflow_loop/project.json` 和 `.github/workflows/release.yml` | 包版本、锁定版本、项目安装标记、标签和发布条件 | 版本全部统一，发布条件只允许 `v0.2.0`，六个附件完整 |
| `git diff --check` | 本阶段文本和脚本修改 | 无空白错误或损坏的补丁 |
| 核对 `git status`、本地标签、远程标签、GitHub Release 和 PyPI | 公开副作用边界 | 实施阶段不创建远程标签、不上传 PyPI、不创建 GitHub Release；公开发布留待后续用户批准的测试步骤 |

### 2.4 未决问题

暂无

## 3. 实施后记录

### 3.1 实际代码修改

| 对应计划步骤 | 文件 | 类、函数或配置项 | 实际修改的代码逻辑 | 数据、状态或输出的实际变化 | 对应验收条件和测试项 |
|---|---|---|---|---|---|
| 1 | `pyproject.toml` | `[project].version`（项目元数据版本） | 把 Python 包版本从 `0.1.0` 改为 `0.2.0`，其余项目元数据不变 | 构建产物使用 `workflow-loop 0.2.0` | AC-01；TC-01、TC-06 |
| 2 | `uv.lock` | `workflow-loop` 包记录 | 把当前可编辑项目的锁定版本从 `0.1.0` 改为 `0.2.0`，依赖列表不变 | 锁定文件与项目元数据使用同一版本 | AC-01；TC-01 |
| 3 | `src/workflow_loop/__init__.py` | `__version__`（包版本常量）、`PRODUCT_IDENTITY`（产品身份） | 把共享版本常量和当前发布注释改为 `0.2.0`；产品名和身份拼接方式不变 | `workflow --version` 实际输出 `workflow-loop 0.2.0` | AC-01、AC-05；TC-01、TC-07 |
| 4 | `src/workflow_loop/cli.py` | `main()`（命令行入口）中的 `--version` 注释 | 把固定身份输出说明从 `0.1.0` 改为 `0.2.0`；参数和处理逻辑不变 | 注释与真实命令输出一致 | AC-01；TC-01 |
| 5 | `src/workflow_loop/project.py` | `INSTALLER_VERSION`（安装器版本）和骨架状态说明 | 保留从共享 `__version__` 读取版本的实现，只把五处写死的版本说明改为 `0.2.0` | 项目完整安装和版本异常说明与运行规则一致 | AC-01、AC-05；TC-01、TC-07 |
| 6 | `install.sh` | `PRODUCT_VERSION`（安装脚本版本） | 把 macOS/Linux 安装目标改为 `0.2.0`，确认、预检、回滚和安装事务逻辑不变 | 脚本安装 `workflow-loop==0.2.0` | AC-01、AC-03、AC-05；TC-01、TC-04、TC-07 |
| 7 | `install.ps1` | `$ProductVersion`（PowerShell 安装脚本版本） | 把 Windows 安装目标改为 `0.2.0`，PowerShell 7 和 Windows PowerShell 5.1 共用逻辑不变 | Windows 安装脚本取得 `workflow-loop==0.2.0` | AC-01、AC-03、AC-05；TC-01、TC-04、TC-07 |
| 8 | `update.sh` | `SCRIPT_VERSION`（更新脚本版本） | 把 macOS/Linux 更新脚本自身版本改为 `0.2.0`，目标解析和数据保留逻辑不变 | 公开更新脚本与目标正式版本一致 | AC-01、AC-03、AC-05；TC-01、TC-04、TC-07 |
| 9 | `update.ps1` | `$ScriptVersion`（PowerShell 更新脚本版本） | 把 Windows 更新脚本自身版本改为 `0.2.0`，更新和进程清理逻辑不变 | 两种 Windows PowerShell 使用 `0.2.0` 更新脚本 | AC-01、AC-03、AC-05；TC-01、TC-04、TC-07 |
| 10 | `uninstall.sh` | `PRODUCT_VERSION`（卸载脚本调用版本） | 把 macOS/Linux 卸载入口调用包版本改为 `0.2.0`，项目和全局卸载范围不变 | `0.2.0` 发布附件调用同版本包 | AC-01、AC-03、AC-04；TC-01、TC-04、TC-06 |
| 11 | `uninstall.ps1` | `$ProductVersion`（PowerShell 卸载脚本调用版本） | 把 Windows 卸载入口调用包版本改为 `0.2.0`，卸载和进程清理范围不变 | Windows `0.2.0` 附件调用同版本包 | AC-01、AC-03、AC-04；TC-01、TC-04、TC-06 |
| 12 | `README.md` | 当前安装章节和固定版本下载地址 | 把安装标题、两个 shell 命令、一个 PowerShell 命令及固定版本说明改为 `0.2.0`/`v0.2.0` | 用户复制当前安装入口会下载 `v0.2.0` 附件 | AC-01、AC-04、AC-05；TC-01、TC-06、TC-07 |
| 13 | `.github/workflows/release.yml` | 触发标签、版本核对、发布条件、跨平台验证和 GitHub Release 配置 | 把当前发布身份改为 `0.2.0`/`v0.2.0`；新增锁定版本、项目安装版本和 README 当前入口核对；保持作业依赖和失败阻断；发布正文增加四种工作意图和无需开发任务简单流程，附件保持六个 | 手动任务不公开发布；只有 `v0.2.0` 标签完成全量测试、构建和四种托管环境安装/更新/卸载验证后，才依次发布 PyPI 和 `Workflow Loop 0.2.0` GitHub Release | AC-01 至 AC-04；TC-01 至 TC-06 |

代码文件修改完成后，调用现有 `_set_project_installer_version()`（设置项目安装版本）入口，只把当前仓库 `.workflow_loop/project.json` 的 `installer_version`（安装版本）从 `0.1.0` 更新为 `0.2.0`。项目设计状态、主题历史、测试入口和文件标识映射未被该入口改写；当前主题及文件标识由工作流正常登记。

### 3.2 开发检查记录

| 检查命令或方法 | 检查范围 | 实际反馈 | 是否需要继续修改 |
|---|---|---|---|
| `.venv/bin/python -m compileall -q src/workflow_loop`；`PYTHONPATH=src .venv/bin/python -m workflow_loop.cli --version` | Python 源码和命令公开身份 | Python 源码编译成功；命令输出严格为 `workflow-loop 0.2.0` | 否 |
| 使用 `tomllib`、JSON 和 PyYAML（YAML 解析器）读取版本与发布配置 | `pyproject.toml`、`uv.lock`、`.workflow_loop/project.json`、`.github/workflows/release.yml` | 包版本和安装版本均为 `0.2.0`；标签为 `v0.2.0`；两个发布作业条件一致；附件严格为六个维护脚本 | 否 |
| `bash -n install.sh update.sh uninstall.sh` | macOS/Linux 安装、更新和卸载脚本语法 | 三个 Bash 脚本语法检查成功 | 否 |
| 本机 PowerShell 可用性和脚本解析检查 | `install.ps1`、`update.ps1`、`uninstall.ps1` | 当前 macOS 主机没有 `pwsh` 或 `powershell`，未生成虚假的本机通过结论；正式解析和行为验证留给 GitHub Windows 托管环境 | 否，属于后续既定跨平台测试条件 |
| `git diff --check`；扫描 13 个受控文件中的 `0.1.0`/`v0.1.0` | 补丁格式和旧当前版本残留 | 无空白错误；13 个受控文件未发现旧当前版本残留 | 否 |
| 本地 Git、远端 Git、GitHub Release 和 PyPI 状态查询 | 实施阶段公开副作用边界 | 本地 `v0.2.0` 标签不存在，远端标签不存在，GitHub Release 不存在，PyPI `0.2.0` 返回 HTTP 404；实施阶段没有提前发布 | 否 |

### 3.3 未完成内容

暂无

## 4. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [0.2.0 在 GitHub 和 PyPI 完成正式发布验收计划](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md) | 本主题要达到的用户结果和五条验收条件 |
| 上游 | [0.2.0 在 GitHub 和 PyPI 完成正式发布测试计划](../qa/0_2_0_在_GitHub_和_PyPI_完成正式发布_测试计划.md) | 本主题准备覆盖的七个测试项 |
| 上游 | [代码架构设计：公开发布身份与安装入口](../spec/代码架构设计.md#58-公开发布身份与安装入口) | 本次实施遵守的版本和发布流水线结构 |
| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整交付链路 |
| 下游 | [0.2.0 在 GitHub 和 PyPI 完成正式发布测试结果](../qa/0_2_0_在_GitHub_和_PyPI_完成正式发布_测试结果.md) | 实施完成后执行正式测试 |
| 下游 | [0.2.0 在 GitHub 和 PyPI 完成正式发布验收结果](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收结果.md) | 测试通过后执行主题验收 |
