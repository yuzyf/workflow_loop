# 【穿刺】验证固定版本 uv 的隔离安装

- 工作流编号：2026-07-30-0740-product_change
- 穿刺项编号：SP-001

## 1. 真实场景与不确定性

Workflow Loop 的官方安装脚本不能要求用户预装 `uv`，也不能使用会变化的最新版。脚本需要下载一个固定版本的独立 `uv` 可执行文件，校验 SHA-256 文件摘要，显式使用用户已经安装的 Python 3.11 或更高版本，把 `workflow-loop==0.1.0` 安装到工具环境，并在不等待用户重开终端的情况下直接执行新命令。

当前本机已有的 `uv 0.11.3` 可以显示相关命令帮助，但这不能证明从官方发布下载的固定资产在隔离目录中的真实行为，也不能证明它不会修改用户 PATH 或自动下载 Python。

## 2. 验证结果用于决定什么

验证通过时，实施阶段锁定实际验证的 uv 版本、官方资产命名、SHA-256 摘要、Python 参数和隔离目录环境变量。验证失败时，不继续按当前安装方案实施，先根据失败行为修改代码设计中的安装工具调用方式。

Windows 和 Linux 资产的摘要可以从同一不可变官方发布取得，但当前环境只能真实运行 Apple Silicon macOS 资产。Windows 和 Linux 的可执行行为必须在后续三平台发布测试中继续验证，不能用本机结果冒充。

## 3. 已知事实与验证范围

### 3.1 已知事实

- 当前产品和代码设计要求产品版本永久固定为 `0.1.0`，安装时不得自动下载 Python。
- 当前项目 `pyproject.toml` 声明 Python 3.11 或更高版本，并提供 `workflow` 命令入口。
- 当前环境是 Apple Silicon macOS，`python3 --version` 返回 3.14.4。
- 当前环境已有 `uv 0.11.3`；它的命令帮助包含 `--python`、`--no-managed-python`、`--no-python-downloads` 和 `uv tool dir --bin`。
- uv 官方 0.11.33 是 2026-07-28 发布的不可变发布，提供 Apple Silicon macOS、Intel macOS、ARM64/x64 Windows 和 ARM64/x64 Linux 资产及独立摘要文件。
- 安装、测试入口和测试执行相关的现有 32 项单元测试已通过；它们验证的是旧实现，不包含本次固定 uv 隔离安装。

### 3.2 本次验证范围

- 下载 uv 0.11.33 的 `uv-aarch64-apple-darwin.tar.gz` 和对应官方 `.sha256` 文件。
- 比较实际下载文件摘要与官方摘要。
- 解压后直接运行下载的 `uv`，确认版本严格等于 0.11.33。
- 在临时目录构建本项目 `workflow-loop` 0.1.0 wheel，也就是 Python 二进制分发包。
- 设置临时 `UV_TOOL_DIR` 和 `UV_TOOL_BIN_DIR`，显式指定当前 Python，并禁止 uv 使用托管 Python和下载 Python。
- 安装本地构建的 wheel，查询实际命令目录并执行其中的 `workflow --version`。
- 比较验证前后的用户工具目录和 Shell 配置文件哈希，确认没有修改用户 PATH 或全局工具环境。
- 不验证 PyPI（Python 公共软件包仓库）发布动作；发布前三平台作业必须安装本次构建的同一份 0.1.0 分发包，全部成功后才能把该分发包上传到 PyPI。
- 不在本机验证 Windows 和 Linux 可执行行为；它们由后续三平台持续集成作业验证。GitHub 托管 Windows 作业只能证明其实际 Windows Server 环境，不作为 Windows 10 或 Windows 11 桌面版本的执行证据。

## 4. 验证方法

- 使用的方法：uv 官方不可变发布资产、SHA-256 摘要、当前项目真实源代码和临时隔离工具目录。
- 临时内容位置：`.workflow_loop/spike_tmp/pinned_uv_isolated_install/`
- 执行步骤：记录用户工具目录和 Shell 配置哈希；下载并校验 uv 0.11.33；解压；用下载的 uv 构建本项目 wheel；使用显式 Python和禁止下载参数安装到临时工具目录；运行临时 `workflow --version`；再次核对用户目录；删除临时内容。
- 外部影响：只从 uv 官方发布地址下载文件；不发布、不扣费、不发送内容、不修改外部数据、不安装全局命令、不修改用户 PATH。

## 5. 实际执行记录

- 执行时间：2026-07-30T12:06:30Z
- 运行环境：Apple Silicon macOS，Darwin 25.4.0 arm64；`/opt/homebrew/bin/python3` 3.14.4；下载后直接执行的 uv 0.11.33。
- 实际命令：实际执行了下列关键命令；路径都位于当前项目或本次临时目录。

```bash
shasum -a 256 -c uv-aarch64-apple-darwin.tar.gz.sha256
./uv-aarch64-apple-darwin/uv --version
.workflow_loop/spike_tmp/pinned_uv_isolated_install/download/uv-aarch64-apple-darwin/uv build --wheel --out-dir .workflow_loop/spike_tmp/pinned_uv_isolated_install/dist --clear --no-create-gitignore --python /opt/homebrew/bin/python3 --no-managed-python --no-python-downloads --cache-dir /tmp/workflow_loop_uv_spike_cache .
UV_TOOL_DIR="$PWD/.workflow_loop/spike_tmp/pinned_uv_isolated_install/tool-dir" UV_TOOL_BIN_DIR="$PWD/.workflow_loop/spike_tmp/pinned_uv_isolated_install/tool-bin" UV_CACHE_DIR="$PWD/.workflow_loop/spike_tmp/pinned_uv_isolated_install/cache" .workflow_loop/spike_tmp/pinned_uv_isolated_install/download/uv-aarch64-apple-darwin/uv tool install "$PWD/.workflow_loop/spike_tmp/pinned_uv_isolated_install/dist/workflow_loop-0.1.0-py3-none-any.whl" --python /opt/homebrew/bin/python3 --no-managed-python --no-python-downloads --no-config
UV_TOOL_DIR="$PWD/.workflow_loop/spike_tmp/pinned_uv_isolated_install/tool-dir" UV_TOOL_BIN_DIR="$PWD/.workflow_loop/spike_tmp/pinned_uv_isolated_install/tool-bin" .workflow_loop/spike_tmp/pinned_uv_isolated_install/download/uv-aarch64-apple-darwin/uv tool dir --bin --no-config
.workflow_loop/spike_tmp/pinned_uv_isolated_install/tool-bin/workflow --version
.workflow_loop/spike_tmp/pinned_uv_isolated_install/tool-bin/workflow --help
.workflow_loop/spike_tmp/pinned_uv_isolated_install/tool-dir/workflow-loop/bin/python -c "from importlib.metadata import version; print(version('workflow-loop'))"
shasum -a 256 /Users/yu/.local/bin/workflow /Users/yu/.zshrc /Users/yu/.zprofile
```

- 真实输入或样本：当前项目真实源代码；官方 uv 0.11.33 Apple Silicon macOS 资产，SHA-256 为 `d75e3d2bfc203d17388edaabd3aa37958edbcbfc36219e3ee0d31bb080b4baa2`；本次构建的 `workflow_loop-0.1.0-py3-none-any.whl`，SHA-256 为 `51ef4943036c4ba738858c4486a60d92cea9ba3bd0eaa7cfb8e50bf51dfb5f0f`。
- 执行失败：沙箱内首次下载和构建因域名解析受限而失败，获准使用外部网络后成功；安装后的 `workflow --version` 返回退出码 2 和 `unrecognized arguments: --version`，原因是当前源码尚未实现计划中的版本选项，不是 uv 安装或命令暴露失败。

## 6. 实际观察结果

- 官方 `.sha256` 文件给出的资产摘要与实际下载文件完全一致，`shasum` 返回 `OK`。
- 下载资产中的可执行文件返回 `uv 0.11.33 (fece32fc5 2026-07-28 aarch64-apple-darwin)`，没有调用本机原有的 uv 0.11.3。
- 固定 uv 使用显式 Python 和禁止托管、禁止下载 Python 的参数，成功构建 `workflow-loop` 0.1.0 wheel。
- `uv tool install` 解析并安装 1 个包，返回 `workflow-loop==0.1.0`，并在指定的临时命令目录生成 `workflow` 符号链接。该链接指向指定的临时工具环境，不指向用户现有工具环境。
- `uv tool dir --bin` 返回指定的项目内临时命令目录。uv 只警告该目录不在 PATH，没有自行修改 PATH。
- 临时 `workflow --help` 成功并列出当前全部子命令，证明新安装的入口能够执行；临时工具环境中的 Python 读取包元数据得到版本 `0.1.0`。
- 临时 `workflow --version` 失败，直接暴露出当前源码缺少该计划功能。代码设计已经要求在实施阶段补上这个身份入口。
- 验证前后，用户现有 `/Users/yu/.local/bin/workflow`、`.zshrc` 和 `.zprofile` 的 SHA-256 分别保持为 `5b454658ba7448118cc006d4a4a6145d65f5be2ce5807ca7cd79a02eb4943676`、`a708ddf27e917c2c44274651affd1cf39a136da50d50556bad50261d298e15f5` 和 `01a10534ef168af8b982ad4363a7355ecc6a3dd9cce0d6b14a00b690dedecc48`。
- 用户现有 `/Users/yu/.local/bin/workflow` 仍指向 `/Users/yu/.local/share/uv/tools/workflow-loop/bin/workflow`，没有被本次临时安装替换。

<a id="7-结论"></a>
## 7. 结论

- 结果状态：已确认
- 是否阻塞后续：否
- 已确认内容：uv 0.11.33 的 Apple Silicon macOS 官方资产可以校验固定摘要；在显式使用现有 Python、禁止 uv 托管或下载 Python、指定隔离工具和命令目录时，可以安装本项目 0.1.0 wheel 并直接运行新入口，而且不会修改用户现有命令和 Shell 配置。
- 仍未确认内容：Windows 和 Linux 资产尚未在对应托管操作系统中执行。这项内容由发布前的三平台真实安装作业验证，不阻塞当前实施。

## 8. 对后续工作的影响

- 产品设计影响：无需修改
- 产品设计更新位置：无
- 代码设计影响：需要修改
- 代码设计更新位置：`spec/代码架构设计.md` 的“4.2 终端与发布适配层”“5.3 安装事务”和“6.1 安装到项目”。
- 剩余风险：Windows 和 Linux 的资产选择、固定摘要和原生命令行为仍需在对应托管平台验证；GitHub 的 Windows Server 作业不能扩大解读为 Windows 10 或 Windows 11 桌面版本证据；实现后的 `workflow --version` 必须从实际安装路径返回严格的 `workflow-loop 0.1.0`。
- 后续处理阶段：impl
- 后续需要检查什么：实施时固定 uv 0.11.33 和各平台资产摘要，补上 `workflow --version`；发布前让 Windows、Linux 和 macOS 作业安装本次构建的同一份 0.1.0 分发包，三平台全部成功后才允许发布该包。
