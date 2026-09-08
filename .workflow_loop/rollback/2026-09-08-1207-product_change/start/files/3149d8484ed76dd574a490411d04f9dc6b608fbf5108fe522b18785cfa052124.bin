# 【主题测试结果】0.2.0 在 GitHub 和 PyPI 完成正式发布

- 工作流编号：2026-08-06-0659-product_change
- 验收主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
- 自动化测试结果：通过
- 人工验收状态：待主题验收
- 测试完成时间：2026-08-06T09:31:56+00:00

## 1. 测试依据

- [验收计划](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md)
- [测试计划](./0_2_0_在_GitHub_和_PyPI_完成正式发布_测试计划.md)
- [实施计划和记录](../impl/0_2_0_在_GitHub_和_PyPI_完成正式发布_实施记录.md)
- [需求交付追踪表](../需求交付追踪表.md)

## 2. 测试环境和执行说明

- 本主题执行范围：TC-01、TC-02、TC-03、TC-04、TC-05、TC-06、TC-07
- 执行顺序：TC-01：无；TC-02：TC-01；TC-03：无；TC-04：无；TC-05：TC-02、TC-04；TC-06：TC-05；TC-07：TC-06
- 未执行项：AC-05 中从 `0.1.0` 公网更新到 `0.2.0` 的场景按用户决定不执行；其余自动化测试项全部执行

## 3. 测试项结果

### TC-01：本地版本身份和发布配置统一为 0.2.0

- 对应验收条件：[AC-01：全部发布身份统一为 0.2.0](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-01)
- 测试方式：自动化测试
- 测试入口：["tests/test_release_workflow.py::test_current_release_identity_and_non_tag_publish_rules_are_consistent"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","-s","tests/test_release_workflow.py::test_current_release_identity_and_non_tag_publish_rules_are_consistent"]
- 机器记录编号：RUN-20260806T093123+0000-9d42e243
- 工作目录：项目根
- 超时（秒）：180
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-06T09:31:23+00:00
- 结束时间：2026-08-06T09:31:23+00:00
- 时长（秒）：0.179
- 退出码：0
- 输出摘要："CURRENT_RELEASE_IDENTITY: {\"actual_command_identity\": \"workflow-loop 0.2.0\", \"future_version_rules\": {\"CONTEXT.md\": \"尚未被 PyPI 占用的新版本号\", \"docs/adr/0002-fix-product-version-at-0-1-0.md\": \"尚未被 PyPI 占用的新版本号\", \"spec/产品总说明.md\": \"未在 PyPI 发布过的新版本号\", \"spec/功能_安装到项目.md\": \"未在 Python 公共软件包仓库发布过的新版本号\"}, \"publish_conditions\": {\"github-release\": \"github.event_name == 'push' && github.ref == 'refs/tags/v0.2.0'\", \"publish-pypi\": \"github.event_name == 'push' && github.ref == 'refs/tags/v0.2.0'\"}, \"release_triggers\": {\"push\": {\"tags\": [\"v0.2.0\"]}, \"workflow_dispatch\": \"\"}, \"version_locations\": {\".github/workflows/release.yml\": \"0.2.0\", \".workflow_loop/project.json\": \"0.2.0\", \"install.ps1\": \"0.2.0\", \"install.sh\": \"0.2.0\", \"pyproject.toml\": \"0.2.0\", \"src/workflow_loop/__init__.py\": \"0.2.0\", \"src/workflow_loop/project.py\": \"0.2.0\"}}\n.\n1 passed in 0.09s\n"
- 输出哈希：44466c8958040be8ba0da633adbe5f99132bbd075e0d357888a07da96b17e42b
- 输出字节数：961
- 产品代码哈希：e97af43f3d73d7dc90ffe429c5447945042b2c25360dc3734264a6c41f5424ba
- 测试代码哈希：8ef8d5b9bad76b3f9a0cf81178671f539f8a165812366bbbf6919fca29f847f4
- 实际结果：机器输出列出源码、项目安装标记、维护脚本和发布配置的当前版本，实际命令身份为 `workflow-loop 0.2.0`；两个公开发布作业都只接受 `refs/tags/v0.2.0`。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260806T093123+0000-9d42e243；完整输出由哈希 44466c8958040be8ba0da633adbe5f99132bbd075e0d357888a07da96b17e42b 和字节数 961 绑定。版本位置清单、命令身份和发布触发条件均保存在本次机器输出中。

### TC-02：发布前公共版本空缺且最终标签指向正确

- 对应验收条件：[AC-01：全部发布身份统一为 0.2.0](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-01)
- 测试方式：自动化测试 + 人工验收
- 测试入口：["tests/release_publication_checks.py::test_public_version_is_absent_and_local_tag_is_ready"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","-s","tests/release_publication_checks.py::test_public_version_is_absent_and_local_tag_is_ready"]
- 机器记录编号：RUN-20260806T093123+0000-f590e165
- 工作目录：项目根
- 超时（秒）：300
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-06T09:31:23+00:00
- 结束时间：2026-08-06T09:31:28+00:00
- 时长（秒）：4.4
- 退出码：0
- 输出摘要："RELEASE_PREFLIGHT_AUDIT: {\"github_release_published_at\": \"2026-08-06T08:54:15Z\", \"local_tag_commit\": \"8c3f93d7409cefb4c4335335bfc38ae090e0ebc6\", \"preflight_finished_at\": \"2026-08-06T08:51:06+00:00\", \"preflight_record\": {\"action\": \"测试项执行\", \"actor\": \"workflow.py\", \"command\": [\".venv/bin/python\", \"-m\", \"pytest\", \"-q\", \"-s\", \"tests/release_publication_checks.py::test_public_version_is_absent_and_local_tag_is_ready\"], \"duration_seconds\": 5.711, \"error\": null, \"exit_code\": 0, \"finished_at\": \"2026-08-06T08:51:06+00:00\", \"started_at\": \"2026-08-06T08:51:00+00:00\", \"status\": \"passed\", \"test_id\": \"TC-02\", \"topic\": \"0.2.0 在 GitHub 和 PyPI 完成正式发布\", \"ts\": \"2026-08-06T08:56:22+00:00\", \"workflow_id\": \"2026-08-06-0659-product_change\"}, \"remote_tag_commit\": \"8c3f93d7409cefb4c4335335bfc38ae090e0ebc6\", \"tag\": \"v0.2.0\"}\n.\n1 passed in 4.32s\n"
- 输出哈希：aec814ec2d06b81208f2cd811f40efe29593ba561a3f19fc79e27a7bf1f89181
- 输出字节数：856
- 产品代码哈希：e97af43f3d73d7dc90ffe429c5447945042b2c25360dc3734264a6c41f5424ba
- 测试代码哈希：8ef8d5b9bad76b3f9a0cf81178671f539f8a165812366bbbf6919fca29f847f4
- 实际结果：机器复核到原始 TC-02 在 `2026-08-06T08:51:06+00:00` 通过，早于 GitHub Release 的 `2026-08-06T08:54:15Z` 发布时间；本地和远程 `v0.2.0` 标签都指向提交 `8c3f93d7409cefb4c4335335bfc38ae090e0ebc6`，最终标签源码仍包含远程标签、GitHub Release 和 PyPI 返回 404 的发布前阻断断言。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260806T093123+0000-f590e165；完整输出由哈希 aec814ec2d06b81208f2cd811f40efe29593ba561a3f19fc79e27a7bf1f89181 和字节数 856 绑定。当前机器输出包含原始通过流水、两个时间和本地/远程标签提交；用户对不可逆标签推送的批准在主题验收中确认。

### TC-03：手动任务和普通分支不能公开发布

- 对应验收条件：[AC-02：只有 v0.2.0 标签可以公开发布](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-02)
- 测试方式：自动化测试
- 测试入口：["tests/test_release_workflow.py::test_manual_release_run_verifies_without_publishing"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","-s","tests/test_release_workflow.py::test_manual_release_run_verifies_without_publishing"]
- 机器记录编号：RUN-20260806T093128+0000-6dfedc64
- 工作目录：项目根
- 超时（秒）：180
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-06T09:31:28+00:00
- 结束时间：2026-08-06T09:31:28+00:00
- 时长（秒）：0.107
- 退出码：0
- 输出摘要：".\n1 passed in 0.02s\n"
- 输出哈希：0e226e633ae5b5f4bb1cc054e16669d44f9686fa57a0de94f53d9ad680293f91
- 输出字节数：20
- 产品代码哈希：e97af43f3d73d7dc90ffe429c5447945042b2c25360dc3734264a6c41f5424ba
- 测试代码哈希：8ef8d5b9bad76b3f9a0cf81178671f539f8a165812366bbbf6919fca29f847f4
- 实际结果：登记的发布边界测试执行完成并退出码为 0，证明手动任务和普通分支路径不满足 PyPI 与 GitHub Release 的公开发布条件。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260806T093128+0000-6dfedc64；完整输出由哈希 0e226e633ae5b5f4bb1cc054e16669d44f9686fa57a0de94f53d9ad680293f91 和字节数 20 绑定。机器记录绑定了具体测试入口、命令、退出码和完整输出哈希。

### TC-04：发布作业顺序、平台矩阵和六个附件配置完整

- 对应验收条件：[AC-03：最终标签任务全部成功](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-03)
- 测试方式：自动化测试
- 测试入口：["tests/test_release_workflow.py::test_prepublish_matrix_covers_platforms_and_partial_install_states","tests/test_release_workflow.py::test_release_gate_matrix_and_assets_are_structurally_complete","tests/test_release_workflow.py::test_release_identity_and_publish_order_are_fixed"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","-s","tests/test_release_workflow.py::test_release_identity_and_publish_order_are_fixed","tests/test_release_workflow.py::test_prepublish_matrix_covers_platforms_and_partial_install_states","tests/test_release_workflow.py::test_release_gate_matrix_and_assets_are_structurally_complete"]
- 机器记录编号：RUN-20260806T093128+0000-26c046e1
- 工作目录：项目根
- 超时（秒）：300
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-06T09:31:28+00:00
- 结束时间：2026-08-06T09:31:28+00:00
- 时长（秒）：0.108
- 退出码：0
- 输出摘要："..RELEASE_WORKFLOW_STRUCTURE: {\"dependency_chain\": {\"build\": \"verify-and-test\", \"github-release\": \"publish-pypi\", \"prepublish-smoke\": \"build\", \"publish-pypi\": \"prepublish-smoke\"}, \"github_release\": {\"assets\": [\"install.sh\", \"install.ps1\", \"update.sh\", \"update.ps1\", \"uninstall.sh\", \"uninstall.ps1\"], \"body_requirements\": [\"macOS、Linux 和原生 Windows 使用一条命令完成安装\", \"支持从零创建、修改产品、修复缺陷和无需开发任务四种工作意图\", \"完整研发任务的每个正式环节依次经过讨论完成、程序检查和用户确认三道门\", \"无需开发任务按调查讨论、执行约定任务、核对结果和用户确认结果的简单流程处理\", \"需求交付追踪表\", \"命令、环境、时间、退出码和代码版本等机器执行记录\", \"返回上游修正、本轮修改回退和整轮作废恢复\", \"Python 3.11 或更高版本\"], \"name\": \"Workflow Loop 0.2.0\", \"permissions\": {\"contents\": \"write\"}, \"tag\": \"v0.2.0\"}, \"platform_matrix\": [\"ubuntu-latest\", \"macos-latest\", \"windows-latest\"], \"platform_steps\": {\"安装脚本冒烟：PowerShell 7（Windows）\": {\"if\": \"runner.os == 'Windows'\", \"shell\": \"pwsh\"}, \"安装脚本冒烟：Windows PowerShell 5.1（Windows）\": {\"if\": \"runner.os == 'Windows'\", \"shell\": \"pwsh\"}, \"安装脚本冒烟：确认、取消与安装（Linux）\": {\"if\": \"runner.os == 'Linux'\", \"shell\": \"default\"}, \"安装脚本冒烟：确认、取消与安装（macOS）\": {\"if\": \"runner.os == 'macOS'\", \"shell\": \"default\"}}, \"pypi_publish\": {\"duplicate_status\": \"200 时退出 1\", \"permissions\": {\"id-token\": \"write\"}, \"publisher\": \"pypa/gh-action-pypi-publish@release/v1\", \"url\": \"https://pypi.org/pypi/workflow-loop/${PRODUCT_VERSION}/json\"}, \"tag_condition\": \"github.event_name == 'push' && github.ref == 'refs/tags/v0.2.0'\"}\n.\n3 passed in 0.03s\n"
- 输出哈希：82b28d4a989891970c04fec1eb06f7b57c34727638a296925eda0156b2f75739
- 输出字节数：1836
- 产品代码哈希：e97af43f3d73d7dc90ffe429c5447945042b2c25360dc3734264a6c41f5424ba
- 测试代码哈希：8ef8d5b9bad76b3f9a0cf81178671f539f8a165812366bbbf6919fca29f847f4
- 实际结果：机器输出证明发布依赖顺序为版本核对和全量测试、构建、跨平台冒烟、PyPI、GitHub Release；平台矩阵覆盖 Ubuntu、macOS、PowerShell 7 和 Windows PowerShell 5.1，Release 配置六个维护脚本。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260806T093128+0000-26c046e1；完整输出由哈希 82b28d4a989891970c04fec1eb06f7b57c34727638a296925eda0156b2f75739 和字节数 1836 绑定。发布作业依赖、平台步骤、标签条件、权限、正文要求和附件清单均在当前输出中。

### TC-05：v0.2.0 标签对应的真实发布任务全部成功

- 对应验收条件：[AC-03：最终标签任务全部成功](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-03)
- 测试方式：自动化测试 + 人工验收
- 测试入口：["tests/release_publication_checks.py::test_final_tag_workflow_succeeds"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","-s","tests/release_publication_checks.py::test_final_tag_workflow_succeeds"]
- 机器记录编号：RUN-20260806T093128+0000-69d284f2
- 工作目录：项目根
- 超时（秒）：3600
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-06T09:31:28+00:00
- 结束时间：2026-08-06T09:31:33+00:00
- 时长（秒）：4.842
- 退出码：0
- 输出摘要："FINAL_TAG_WORKFLOW: {\"commit\": \"8c3f93d7409cefb4c4335335bfc38ae090e0ebc6\", \"jobs\": {\"build\": \"success\", \"github-release\": \"success\", \"prepublish-smoke (macos-latest)\": \"success\", \"prepublish-smoke (ubuntu-latest)\": \"success\", \"prepublish-smoke (windows-latest)\": \"success\", \"publish-pypi\": \"success\", \"verify-and-test\": \"success\"}, \"platform_steps\": {\"prepublish-smoke (macos-latest)\": [\"安装脚本冒烟：确认、取消与安装（macOS）\"], \"prepublish-smoke (ubuntu-latest)\": [\"安装脚本冒烟：确认、取消与安装（Linux）\"], \"prepublish-smoke (windows-latest)\": [\"安装脚本冒烟：PowerShell 7（Windows）\", \"安装脚本冒烟：Windows PowerShell 5.1（Windows）\"]}, \"run_id\": 31086545349, \"run_number\": 11, \"run_url\": \"https://github.com/yuzyf/workflow_loop/actions/runs/31086545349\", \"tag\": \"v0.2.0\"}\n.\n1 passed in 4.76s\n"
- 输出哈希：31dcb8c03fbc2025d206c1110c8f8f3a12e6e04ce68258379938ef6ecae7e8ed
- 输出字节数：852
- 产品代码哈希：e97af43f3d73d7dc90ffe429c5447945042b2c25360dc3734264a6c41f5424ba
- 测试代码哈希：8ef8d5b9bad76b3f9a0cf81178671f539f8a165812366bbbf6919fca29f847f4
- 实际结果：机器查询到 `v0.2.0` 对应提交 `8c3f93d7409cefb4c4335335bfc38ae090e0ebc6`；GitHub Actions 第 11 次发布任务的版本核对、全量测试、构建、macOS、Ubuntu、Windows、PyPI 和 GitHub Release 作业全部为 `success`（成功）。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260806T093128+0000-69d284f2；完整输出由哈希 31dcb8c03fbc2025d206c1110c8f8f3a12e6e04ce68258379938ef6ecae7e8ed 和字节数 852 绑定。机器输出记录任务编号 `31086545349`、任务地址、七个作业结论和四种托管环境步骤。

### TC-06：PyPI 与 GitHub Release 内容和附件一致

- 对应验收条件：[AC-04：两个公开渠道内容一致并提供六个脚本](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-04)
- 测试方式：自动化测试
- 测试入口：["tests/release_publication_checks.py::test_pypi_and_github_release_contents_match","tests/release_publication_checks.py::test_release_assets_and_platform_evidence_match_final_tag"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","-s","tests/release_publication_checks.py::test_pypi_and_github_release_contents_match","tests/release_publication_checks.py::test_release_assets_and_platform_evidence_match_final_tag"]
- 机器记录编号：RUN-20260806T093133+0000-b0eca73f
- 工作目录：项目根
- 超时（秒）：900
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-06T09:31:33+00:00
- 结束时间：2026-08-06T09:31:50+00:00
- 时长（秒）：17.049
- 退出码：0
- 输出摘要："PUBLIC_RELEASE_CONTENT: {\"github\": {\"assets\": [\"install.ps1\", \"install.sh\", \"uninstall.ps1\", \"uninstall.sh\", \"update.ps1\", \"update.sh\"], \"name\": \"Workflow Loop 0.2.0\", \"tag\": \"v0.2.0\", \"url\": \"https://github.com/yuzyf/workflow_loop/releases/tag/v0.2.0\"}, \"pypi\": {\"author\": \"yuzyf\", \"distributions\": [\"workflow_loop-0.2.0-py3-none-any.whl\", \"workflow_loop-0.2.0.tar.gz\"], \"license_expression\": \"MIT\", \"name\": \"workflow-loop\", \"project_urls\": {\"Homepage\": \"https://github.com/yuzyf/workflow_loop\", \"Repository\": \"https://github.com/yuzyf/workflow_loop\"}, \"summary\": \"为 AI 驱动的软件开发提供有状态、可验证、可回退的工作流管理。\", \"version\": \"0.2.0\"}}\n.RELEASE_ASSETS_AND_PLATFORMS: {\"assets\": {\"install.ps1\": {\"download_url\": \"https://github.com/yuzyf/workflow_loop/releases/download/v0.2.0/install.ps1\", \"sha256\": \"5b5861535ddafe91592e578ffd64bf7f646af728eac2187790dbf2d3ebc5da86\", \"size\": 18473}, \"install.sh\": {\"download_url\": \"https://github.com/yuzyf/workflow_loop/releases/download/v0.2.0/install.sh\", \"sha256\": \"aff3131d3cce35883b8d28b73a7847fc1e6f8becabdd8f6d59804c988d947a05\", \"size\": 18063}, \"uninstall.ps1\": {\"download_url\": \"https://github.com/yuzyf/workflow_loop/releases/download/v0.2.0/uninstall.ps1\", \"sha256\": \"d02e865e6a9c48c71d423499a6d8ae184952940d9879194ef40b8c5d45b570cb\", \"size\": 10700}, \"uninstall.sh\": {\"download_url\": \"https://github.com/yuzyf/workflow_loop/releases/download/v0.2.0/uninstall.sh\", \"sha256\": \"6d98b36e93f3c4b3462ef072ca739c3854fdf4512065ab0b61fb0321ec98ded2\", \"size\": 9217}, \"update.ps1\": {\"download_url\": \"https://github.com/yuzyf/workflow_loop/releases/download/v0.2.0/update.ps1\", \"sha256\": \"e3878539bbe62a97de9c64ef66e7a9d87a9b35180bd4b60994977651d617bda9\", \"size\": 12944}, \"update.sh\": {\"download_url\": \"https://github.com/yuzyf/workflow_loop/releases/download/v0.2.0/update.sh\", \"sha256\": \"fcd9b09586598c86c0fd6ddbed158534937e6c9978fc77b65ab3f59826af8866\", \"size\": 9922}}, \"commit\": \"8c3f93d7409cefb4c4335335bfc38ae090e0ebc6\", \"platform_steps\": {\"prepublish-smoke (macos-latest)\": [\"安装脚本冒烟：确认、取消与安装（macOS）\"], \"prepublish-smoke (ubuntu-latest)\": [\"安装脚本冒烟：确认、取消与安装（Linux）\"], \"prepublish-smoke (windows-latest)\": [\"安装脚本冒烟：PowerShell 7（Windows）\", \"安装脚本冒烟：Windows PowerShell 5.1（Windows）\"]}, \"run_url\": \"https://github.com/yuzyf/workflow_loop/actions/runs/31086545349\", \"tag\": \"v0.2.0\"}\n.\n2 passed in 16.95s\n"
- 输出哈希：0b001a8a5153ec2d86552e584180d864eb9a28aaf3c6d7d88c24f9ec9aee37e5
- 输出字节数：2482
- 产品代码哈希：e97af43f3d73d7dc90ffe429c5447945042b2c25360dc3734264a6c41f5424ba
- 测试代码哈希：8ef8d5b9bad76b3f9a0cf81178671f539f8a165812366bbbf6919fca29f847f4
- 实际结果：机器从公开接口确认 PyPI 提供 `workflow-loop 0.2.0` 的 wheel 和源码包，作者、MIT 许可证、中文简介和仓库链接正确；GitHub Release 名称为 `Workflow Loop 0.2.0`，六个附件逐字节等于最终标签文件，四种平台证据来自同一发布任务。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260806T093133+0000-b0eca73f；完整输出由哈希 0b001a8a5153ec2d86552e584180d864eb9a28aaf3c6d7d88c24f9ec9aee37e5 和字节数 2482 绑定。机器输出列出两个公开渠道的字段、六个附件地址/大小/SHA-256、最终提交和发布任务地址。

### TC-07：公网全新安装得到 0.2.0（本次不执行 0.1.0 升级）

- 对应验收条件：[AC-05：公网安装和从 0.1.0 更新后得到 0.2.0](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-05)
- 测试方式：自动化测试 + 人工验收
- 测试入口：["tests/release_publication_checks.py::test_clean_install_uses_public_pypi_package"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","-s","tests/release_publication_checks.py::test_clean_install_uses_public_pypi_package"]
- 机器记录编号：RUN-20260806T093150+0000-860091e0
- 工作目录：项目根
- 超时（秒）：900
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-06T09:31:50+00:00
- 结束时间：2026-08-06T09:31:56+00:00
- 时长（秒）：5.965
- 退出码：0
- 输出摘要："PUBLIC_INSTALL: {\"cache_disabled\": true, \"download_url\": \"https://files.pythonhosted.org/packages/68/00/2a0292aa6db53450aeeda2fb1cf4063bedc4f93453230d379e04b33c4c47/workflow_loop-0.2.0-py3-none-any.whl\", \"identity\": \"workflow-loop 0.2.0\", \"index\": \"https://pypi.org/simple\", \"local_sources_disabled\": true, \"requested\": \"workflow-loop==0.2.0\", \"sha256\": \"36703bf897baba49b697c0772c4a1c85711742f1b243a9176233e89d163406fb\"}\n.\n1 passed in 5.88s\n"
- 输出哈希：f5d38fdd4c57d50f33a9b3082351cd7c8b47188c711744cd23d8fa6c2fc71e1e
- 输出字节数：442
- 产品代码哈希：e97af43f3d73d7dc90ffe429c5447945042b2c25360dc3734264a6c41f5424ba
- 测试代码哈希：8ef8d5b9bad76b3f9a0cf81178671f539f8a165812366bbbf6919fca29f847f4
- 实际结果：机器在禁用本地源码和缓存的隔离环境中，从 `https://pypi.org/simple` 请求 `workflow-loop==0.2.0`，下载来源为 `files.pythonhosted.org`，安装后的命令身份为 `workflow-loop 0.2.0`。本次没有执行从 `0.1.0` 更新的场景，不用本记录证明该部分。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260806T093150+0000-860091e0；完整输出由哈希 f5d38fdd4c57d50f33a9b3082351cd7c8b47188c711744cd23d8fa6c2fc71e1e 和字节数 442 绑定。机器输出记录公开 wheel 地址、SHA-256、索引地址、请求版本和安装后命令身份；升级场景的排除由用户在主题验收中确认。

## 4. 人工验收交接

- 人工验收对象：TC-02 的发布前检查时间线和标签推送批准；TC-05 的最终发布任务；TC-07 的公网安装结果与未执行升级场景边界。
- 人工检查方法：核对 TC-02 的原始通过时间早于 Release 发布时间，核对 TC-05 的最终提交、任务编号和全部成功作业，核对 TC-07 的公开下载来源和命令身份；同时确认本轮不要求补做 `0.1.0` 升级场景。
- 自动化已经证明：发布前空缺检查曾在公开发布前通过，最终标签任务全部成功，PyPI 与 GitHub Release 内容一致，六个附件属于最终标签，公网全新安装得到 `workflow-loop 0.2.0`。
- 还需要用户确认：不可逆标签推送是用户批准的；公开结果满足本次发布目标；AC-05 只以公网全新安装作为本轮机器证据，不声称已验证 `0.1.0` 更新路径。
- 人工结果填写位置：`acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收结果.md`

## 5. 未通过或阻塞

暂无

## 6. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [验收计划](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md) | 说明什么算完成 |
| 上游 | [测试计划](./0_2_0_在_GitHub_和_PyPI_完成正式发布_测试计划.md) | 说明本次覆盖哪些测试项 |
| 上游 | [实施记录](../impl/0_2_0_在_GitHub_和_PyPI_完成正式发布_实施记录.md) | 说明本次代码怎样实现 |
| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整链路 |
| 下游 | [主题验收](../acceptance/0_2_0_在_GitHub_和_PyPI_完成正式发布_验收结果.md) | 混合测试在这里接收人工确认 |
