# 【穿刺】Windows 辅助进程替换或删除正在运行的全局命令

- 工作流编号：2026-08-04-0950-product_change
- 穿刺项编号：SP-001

## 1. 真实场景与不确定性

Windows 用户已经通过 uv 安装全局 `workflow` 命令。用户在项目根目录执行 `workflow update` 时，需要先让全局命令升级到目标版本，再更新当前项目；用户执行 `workflow uninstall --global` 时，需要删除 uv 管理的全局工具。两种操作开始时，当前 `workflow.exe` 仍在运行。

Windows 通常不允许替换或删除仍被进程占用的可执行文件。当前不确定的是：由 `workflow.exe` 启动的 PowerShell 辅助进程，能否等待父命令退出后，再用真实的 uv 工具管理命令可靠完成替换或删除；还需要分别确认 Windows PowerShell 5.1 和 PowerShell 7 的行为。

## 2. 验证结果用于决定什么

验证通过时，代码设计明确采用“当前命令写入并启动辅助脚本，立即退出；辅助脚本等待父进程结束后调用 uv”的进程交接方式。验证失败时，不按这个方案实施，需要把 Windows 更新和全局卸载改成用户单独运行的外部脚本，或选择不依赖正在运行入口的独立启动器。

## 3. 已知事实与验证范围

### 3.1 已知事实

- 当前项目通过 Python 控制台入口生成 `workflow` 命令，全局安装由 uv 工具环境管理。
- `uv tool install --force` 是计划中的全局更新命令，`uv tool uninstall` 是计划中的全局卸载命令。
- 当前 GitHub Actions 发布流程已经使用 `windows-latest`，可以取得真实 Windows Server 托管环境，但现有作业没有覆盖命令自更新或自删除。
- 当前产品规则要求一条命令完成操作，不要求用户在当前命令退出后手工执行第二条命令。
- 用户已经确认允许创建临时远端分支、运行一次 GitHub Actions，并在取得证据后删除临时分支和运行记录；不发布版本、不修改主分支、不接触生产数据。

### 3.2 本次验证范围

- 在 GitHub 托管的 `windows-latest` 真实 Windows 环境中，使用隔离的 `UV_TOOL_DIR`（uv 工具目录）和 `UV_TOOL_BIN_DIR`（uv 命令目录）。
- 构建并安装一个最小 Python 包，生成真实的 Windows 命令入口；包名和命令名使用穿刺专用名称，不安装本项目的生产包。
- 从正在运行的命令入口分别启动 Windows PowerShell 5.1 和 PowerShell 7 辅助进程，辅助进程等待父进程退出。
- 更新路径调用真实的 `uv tool install --force`，并验证命令版本从 1.0.0 变为 2.0.0。
- 卸载路径调用真实的 `uv tool uninstall`，并验证命令入口和工具环境被删除。
- 记录操作系统、PowerShell、Python、uv 版本、退出码、结果文件和关键目录状态。
- 不验证 Windows 10 或 Windows 11 桌面版，不验证杀毒软件或企业终端策略造成的额外文件锁，不发布 Workflow Loop 正式包。
- 更新和卸载两条路径、两种 PowerShell 都得到可重复的实际结果后停止。

## 4. 验证方法

- 使用的方法：临时 Git 分支上的 GitHub Actions Windows 作业；作业内构建真实 Python wheel（二进制分发包），使用真实 uv 工具安装、更新和卸载；最小 Python 命令只负责把自己的进程编号交给 PowerShell 辅助脚本后退出。
- 临时内容位置：`.workflow_loop/spike_tmp/windows_self_maintenance/`
- 执行步骤：创建隔离工作树和临时分支；加入仅对临时分支触发的 Windows 验证作业；推送并等待一次作业完成；保存不含凭据的关键日志和运行编号；删除远端临时分支与运行记录；删除本地临时工作树和分支。
- 外部影响：会在 `yuzyf/workflow_loop` 创建一个可撤销的临时分支并消耗一次 GitHub Actions Windows 作业时长，随后删除该分支和运行记录；用户已明确确认。不会创建发布、修改主分支、安装用户本机全局命令或读写生产数据。

## 5. 实际执行记录

- 执行时间：2026-08-04T12:25:20Z 至 2026-08-04T12:27:02Z
- 运行环境：GitHub Actions `windows-latest`，实际镜像为 Windows Server 2025 `10.0.26100`；Python 3.13.14；uv 0.11.33 `x86_64-pc-windows-msvc`；两个矩阵作业分别使用 Windows PowerShell 5.1.26100.33158 和 PowerShell 7.6.4。
- 实际命令：临时分支提交 `4b6c510f346c060e85c352b33a281287eaf8cd01` 触发 GitHub Actions 运行 `30909020532`；作业内实际执行 `python -m pip install uv==0.11.33`、`uv tool install 临时工作目录/probe-v1 --python PythonPath --no-managed-python --no-python-downloads --no-config`、正在运行的 `workflow-spike-probe handoff update ...`、辅助进程中的 `uv tool install --force 临时工作目录/probe-v2 ...`、正在运行的 `workflow-spike-probe handoff uninstall ...` 和辅助进程中的 `uv tool uninstall workflow-loop-spike-probe --no-config`。命令参数中的路径均为 Actions 临时工作目录；未记录任何凭据。
- 真实输入或样本：两个真实 Python wheel 安装源目录 `probe-v1`（版本 1.0.0）和 `probe-v2`（版本 2.0.0），由 uv 在 Windows 作业中真实构建并安装；临时验证作业文件、辅助脚本和两个探针入口的 SHA-256 分别为 `865c92775fc2fba74acba0362e7de0bdb5675465d70c003817fa507067f76c70`、`32f0667b501324cedfe97f2c0a5a3906d1f362605a1fa2e3275a7209d70321b3`、`dc344d471e3992818083cf2916db1312bc589c6bcd5bea5b4589c45ad15f40c9`、`b5647c674ed24bd56cd51177590611912fa8925bbf5369fd579cc3417134b2`。
- 执行失败：Windows PowerShell 5.1 作业在更新辅助进程调用 uv 时失败。父进程已退出，辅助进程读取到 uv 正常进度文本 `Resolved 1 package in 2ms` 后，由于脚本的 `ErrorActionPreference=Stop` 将合并的标准错误流升级为异常，结果文件记录 `parentExited=true`、`uvExitCode=-1`；这不是文件替换失败。PowerShell 7 作业成功完成全部更新和卸载断言。

## 6. 实际观察结果

PowerShell 7 作业输出确认：`workflow-spike-probe` 从 `1.0.0` 更新到 `2.0.0`；更新结果 `success=true`、`parentExited=true`、`uvExitCode=0`、等待 544 毫秒；卸载结果 `success=true`、`parentExited=true`、`uvExitCode=0`、等待 136 毫秒；命令入口和 `UV_TOOL_DIR` 下的工具环境都被删除，`uv tool list` 不再列出探针。

Windows PowerShell 5.1 作业输出确认：父进程等待成立，等待 743 毫秒后开始调用 uv；但把 uv 的正常标准错误进度文字通过 `2>&1` 合并到当前 PowerShell 错误流，在 `ErrorActionPreference=Stop` 下提前进入异常处理，未完成后续版本和卸载断言。该失败暴露的是输出流处理方式，不是否定辅助进程交接。

<a id="7-结论"></a>
## 7. 结论

- 结果状态：限制已确认
- 是否阻塞后续：否
- 已确认内容：辅助 PowerShell 进程可以在父 `workflow.exe` 退出后继续运行；PowerShell 7.6.4 已真实完成 uv 工具更新和卸载；Windows PowerShell 5.1.26100.33158 已真实确认等待父进程退出，但必须使用独立标准输出、标准错误重定向并按 uv 退出码判断，不能在 `ErrorActionPreference=Stop` 下合并错误流。
- 仍未确认内容：正式实现采用修正后的 5.1 输出捕获方式后，需由后续 Windows 自动化测试确认最终 Workflow Loop 脚本的完整返回码和提示文本；这不阻塞按已确认架构进入实施。

## 8. 对后续工作的影响

- 产品设计影响：无需修改
- 产品设计更新位置：无
- 代码设计影响：需要修改
- 代码设计更新位置：`spec/代码架构设计.md` 的“5.9 更新编排”“5.10 卸载编排”“6.14 更新已安装项目”“6.15 卸载 Workflow Loop”和 Windows 平台限制说明。
- 剩余风险：正式实现若错误地复用 `2>&1` 和 `ErrorActionPreference=Stop`，Windows PowerShell 5.1 可能在 uv 已成功执行时误判失败；Windows 10/11 桌面版和企业安全软件额外文件锁不在本次验证范围。
- 后续处理阶段：impl
- 后续需要检查什么：正式 Windows 脚本必须使用独立输出文件或等价捕获方式；测试 PowerShell 5.1 和 7 的更新、全局卸载、父进程等待、退出码、命令删除和项目范围隔离；记录全局与项目任一侧失败时的实际版本。
