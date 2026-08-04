# 【主题测试结果】0.1.0 在 GitHub 和 PyPI 完成正式发布

- 工作流编号：2026-08-03-1150-product_change
- 验收主题：0.1.0 在 GitHub 和 PyPI 完成正式发布
- 自动化测试结果：通过
- 人工验收状态：待主题验收
- 测试完成时间：2026-08-04T08:22:16+00:00

## 1. 测试依据

- [验收计划](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md)
- [测试计划](./0_1_0_在_GitHub_和_PyPI_完成正式发布_测试计划.md)
- [实施计划和记录](../impl/0_1_0_在_GitHub_和_PyPI_完成正式发布_实施记录.md)
- [需求交付追踪表](../需求交付追踪表.md)

## 2. 测试环境和执行说明

- 本主题执行范围：TC-01、TC-02、TC-03、TC-04、TC-05、TC-06、TC-07
- 执行顺序：TC-01：无；TC-02：TC-01；TC-03：无；TC-04：TC-02、TC-03；TC-05：TC-04；TC-06：TC-05；TC-07：TC-04
- 未执行项：暂无

## 3. 测试项结果

### TC-01：本次版本身份和非标签发布规则一致

- 对应验收条件：[AC-01：最终发布身份和前置条件一致](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-01)
- 测试方式：自动化测试
- 测试入口：["tests/test_release_workflow.py::test_current_release_identity_and_non_tag_publish_rules_are_consistent"]
- 执行命令：["scripts/test_all.sh","-s","tests/test_release_workflow.py::test_current_release_identity_and_non_tag_publish_rules_are_consistent"]
- 机器记录编号：RUN-20260804T080245+0000-d9176773
- 工作目录：项目根
- 超时（秒）：180
- 运行环境：平台=darwin；可执行文件=scripts/test_all.sh
- 开始时间：2026-08-04T08:02:45+00:00
- 结束时间：2026-08-04T08:02:45+00:00
- 时长（秒）：0.16
- 退出码：0
- 输出摘要："CURRENT_RELEASE_IDENTITY: {\"actual_command_identity\": \"workflow-loop 0.1.0\", \"future_version_rules\": {\"CONTEXT.md\": \"尚未被 PyPI 占用的新版本号\", \"docs/adr/0002-fix-product-version-at-0-1-0.md\": \"尚未被 PyPI 占用的新版本号\", \"spec/产品总说明.md\": \"未在 PyPI 发布过的新版本号\", \"spec/功能_安装到项目.md\": \"未在 Python 公共软件包仓库发布过的新版本号\"}, \"publish_conditions\": {\"github-release\": \"github.event_name == 'push' && github.ref == 'refs/tags/v0.1.0'\", \"publish-pypi\": \"github.event_name == 'push' && github.ref == 'refs/tags/v0.1.0'\"}, \"release_triggers\": {\"push\": {\"tags\": [\"v0.1.0\"]}, \"workflow_dispatch\": \"\"}, \"version_locations\": {\".github/workflows/release.yml\": \"0.1.0\", \".workflow_loop/project.json\": \"0.1.0\", \"install.ps1\": \"0.1.0\", \"install.sh\": \"0.1.0\", \"pyproject.toml\": \"0.1.0\", \"src/workflow_loop/__init__.py\": \"0.1.0\", \"src/workflow_loop/project.py\": \"0.1.0\"}}\n.\n1 passed in 0.07s\n"
- 输出哈希：fcf0245386239dcbd266217faed69af9452bbc475e3f8b66a56ee932adaa8c53
- 输出字节数：961
- 产品代码哈希：63ce041fae999aad55cbd1cedf8addd5bcc20521f97d62d15fbc59775424f0aa
- 测试代码哈希：3d4561c53aaa16913c21b06fea56568836aa7efc5511580d620c6148f869a83b
- 实际结果：机器输出证明本次版本位置和实际命令身份全部为 `0.1.0`，只有推送 `v0.1.0` 标签才允许公开发布，手动任务不会发布；四份规则文档均要求未来使用尚未被 PyPI 占用的新版本号。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260804T080245+0000-d9176773；完整输出由哈希 fcf0245386239dcbd266217faed69af9452bbc475e3f8b66a56ee932adaa8c53 和字节数 961 绑定。

### TC-02：发布前公共版本空缺且标签准备正确

- 对应验收条件：[AC-01：最终发布身份和前置条件一致](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-01)
- 测试方式：自动化测试 + 人工验收
- 测试入口：["tests/release_publication_checks.py::test_public_version_is_absent_and_local_tag_is_ready"]
- 执行命令：["scripts/test_all.sh","-s","tests/release_publication_checks.py::test_public_version_is_absent_and_local_tag_is_ready"]
- 机器记录编号：RUN-20260804T080245+0000-60e79198
- 工作目录：项目根
- 超时（秒）：180
- 运行环境：平台=darwin；可执行文件=scripts/test_all.sh
- 开始时间：2026-08-04T08:02:45+00:00
- 结束时间：2026-08-04T08:02:54+00:00
- 时长（秒）：9.241
- 退出码：0
- 输出摘要："RELEASE_PREFLIGHT_READY: {\"checked_at\": \"2026-08-04T08:02:54+00:00\", \"github_release\": {\"body\": \"{\\\"message\\\":\\\"Not Found\\\",\\\"documentation_url\\\":\\\"https://docs.github.com/rest/releases/releases#get-a-release-by-tag-name\\\",\\\"status\\\":\\\"404\\\"}\", \"status\": 404, \"url\": \"https://api.github.com/repos/yuzyf/workflow_loop/releases/tags/v0.1.0\"}, \"github_tag\": {\"body\": \"{\\\"message\\\":\\\"Not Found\\\",\\\"documentation_url\\\":\\\"https://docs.github.com/rest/git/refs#get-a-reference\\\",\\\"status\\\":\\\"404\\\"}\", \"status\": 404, \"url\": \"https://api.github.com/repos/yuzyf/workflow_loop/git/ref/tags/v0.1.0\"}, \"head_commit\": \"f612e7d724ff34606919a5951545966c1efbcf1d\", \"local_tag_commit\": \"f612e7d724ff34606919a5951545966c1efbcf1d\", \"pypi_release\": {\"body\": \"{\\\"message\\\": \\\"Not Found\\\"}\", \"status\": 404, \"url\": \"https://pypi.org/pypi/workflow-loop/0.1.0/json\"}, \"ready\": true, \"remote_main_commit\": \"f612e7d724ff34606919a5951545966c1efbcf1d\", \"required_tag_files\": [\".github/workflows/release.yml\", \"LICENSE\", \"README.md\", \"install.ps1\", \"install.sh\", \"pyproject.toml\", \"tests/public_repository_checks.py\", \"tests/release_publication_checks.py\", \"tests/test_public_project.py\", \"tests/test_release_workflow.py\"], \"tag\": \"v0.1.0\"}\n.\n1 passed in 9.14s\n"
- 输出哈希：9fc02fd3861c0ad1df4f6fa1094b7bf22d17a5c4a259aa23ee7a7445a3710f53
- 输出字节数：1230
- 产品代码哈希：63ce041fae999aad55cbd1cedf8addd5bcc20521f97d62d15fbc59775424f0aa
- 测试代码哈希：3d4561c53aaa16913c21b06fea56568836aa7efc5511580d620c6148f869a83b
- 实际结果：机器在 `2026-08-04T08:02:54+00:00` 查询到远程标签、GitHub Release 和 PyPI `0.1.0` 均返回 404，并证明主分支、本地标签和当前提交都指向 `f612e7d724ff34606919a5951545966c1efbcf1d`；不可逆推送的批准仍由用户决定。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260804T080245+0000-60e79198；完整输出由哈希 9fc02fd3861c0ad1df4f6fa1094b7bf22d17a5c4a259aa23ee7a7445a3710f53 和字节数 1230 绑定；展示预检结果并询问“你确认现在把本地 `v0.1.0` 推送到远程并触发正式发布吗？”后，用户回复“可以”。

### TC-03：发布任务门控平台矩阵和附件配置正确

- 对应验收条件：[AC-02：最终标签任务全部成功](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-02)
- 测试方式：自动化测试
- 测试入口：["tests/test_release_workflow.py::test_release_gate_matrix_and_assets_are_structurally_complete"]
- 执行命令：["scripts/test_all.sh","-s","tests/test_release_workflow.py::test_release_gate_matrix_and_assets_are_structurally_complete"]
- 机器记录编号：RUN-20260804T080254+0000-8cb19dee
- 工作目录：项目根
- 超时（秒）：180
- 运行环境：平台=darwin；可执行文件=scripts/test_all.sh
- 开始时间：2026-08-04T08:02:54+00:00
- 结束时间：2026-08-04T08:02:54+00:00
- 时长（秒）：0.104
- 退出码：0
- 输出摘要："RELEASE_WORKFLOW_STRUCTURE: {\"dependency_chain\": {\"build\": \"verify-and-test\", \"github-release\": \"publish-pypi\", \"prepublish-smoke\": \"build\", \"publish-pypi\": \"prepublish-smoke\"}, \"github_release\": {\"assets\": [\"install.sh\", \"install.ps1\"], \"body_requirements\": [\"macOS、Linux 和原生 Windows 使用一条命令完成安装\", \"从零创建、修改产品和修复缺陷三种工作意图\", \"讨论完成、程序检查和用户确认三道门\", \"需求交付追踪表\", \"命令、环境、时间、退出码和代码版本等机器执行记录\", \"返回上游修正、本轮修改回退和整轮作废恢复\", \"Python 3.11 或更高版本\"], \"name\": \"Workflow Loop 0.1.0\", \"permissions\": {\"contents\": \"write\"}, \"tag\": \"v0.1.0\"}, \"platform_matrix\": [\"ubuntu-latest\", \"macos-latest\", \"windows-latest\"], \"platform_steps\": {\"安装脚本冒烟：PowerShell 7（Windows）\": {\"if\": \"runner.os == 'Windows'\", \"shell\": \"pwsh\"}, \"安装脚本冒烟：Windows PowerShell 5.1（Windows）\": {\"if\": \"runner.os == 'Windows'\", \"shell\": \"pwsh\"}, \"安装脚本冒烟：确认、取消与安装（Linux）\": {\"if\": \"runner.os == 'Linux'\", \"shell\": \"default\"}, \"安装脚本冒烟：确认、取消与安装（macOS）\": {\"if\": \"runner.os == 'macOS'\", \"shell\": \"default\"}}, \"pypi_publish\": {\"duplicate_status\": \"200 时退出 1\", \"permissions\": {\"id-token\": \"write\"}, \"publisher\": \"pypa/gh-action-pypi-publish@release/v1\", \"url\": \"https://pypi.org/pypi/workflow-loop/${PRODUCT_VERSION}/json\"}, \"tag_condition\": \"github.event_name == 'push' && github.ref == 'refs/tags/v0.1.0'\"}\n.\n1 passed in 0.01s\n"
- 输出哈希：ceb77b142f4e965f091aaa583c8317ff9cda18c6fa5e95d543cc1df237d6a872
- 输出字节数：1581
- 产品代码哈希：63ce041fae999aad55cbd1cedf8addd5bcc20521f97d62d15fbc59775424f0aa
- 测试代码哈希：3d4561c53aaa16913c21b06fea56568836aa7efc5511580d620c6148f869a83b
- 实际结果：机器输出证明发布依赖顺序固定为测试、构建、三平台安装、PyPI、GitHub Release，并列出 Ubuntu、macOS、PowerShell 7 和 Windows PowerShell 5.1 的检查步骤、标签条件、发布权限、正式发布正文要求和两个附件。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260804T080254+0000-8cb19dee；完整输出由哈希 ceb77b142f4e965f091aaa583c8317ff9cda18c6fa5e95d543cc1df237d6a872 和字节数 1581 绑定。

### TC-04：最终标签任务全部成功

- 对应验收条件：[AC-02：最终标签任务全部成功](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-02)
- 测试方式：自动化测试
- 测试入口：["tests/release_publication_checks.py::test_final_tag_workflow_succeeds"]
- 执行命令：["scripts/test_all.sh","-s","tests/release_publication_checks.py::test_final_tag_workflow_succeeds"]
- 机器记录编号：RUN-20260804T080254+0000-41b7cb60
- 工作目录：项目根
- 超时（秒）：3600
- 运行环境：平台=darwin；可执行文件=scripts/test_all.sh
- 开始时间：2026-08-04T08:02:54+00:00
- 结束时间：2026-08-04T08:21:52+00:00
- 时长（秒）：1138.238
- 退出码：0
- 输出摘要："FINAL_TAG_WORKFLOW: {\"commit\": \"f612e7d724ff34606919a5951545966c1efbcf1d\", \"jobs\": {\"build\": \"success\", \"github-release\": \"success\", \"prepublish-smoke (macos-latest)\": \"success\", \"prepublish-smoke (ubuntu-latest)\": \"success\", \"prepublish-smoke (windows-latest)\": \"success\", \"publish-pypi\": \"success\", \"verify-and-test\": \"success\"}, \"platform_steps\": {\"prepublish-smoke (macos-latest)\": [\"安装脚本冒烟：确认、取消与安装（macOS）\"], \"prepublish-smoke (ubuntu-latest)\": [\"安装脚本冒烟：确认、取消与安装（Linux）\"], \"prepublish-smoke (windows-latest)\": [\"安装脚本冒烟：PowerShell 7（Windows）\", \"安装脚本冒烟：Windows PowerShell 5.1（Windows）\"]}, \"run_id\": 30891477196, \"run_number\": 7, \"run_url\": \"https://github.com/yuzyf/workflow_loop/actions/runs/30891477196\", \"tag\": \"v0.1.0\"}\n.\n1 passed in 1138.13s (0:18:58)\n"
- 输出哈希：239e72b586519b0b290791dacc0363aa04f47c1f26770ef2b2fcb4387ddd4c68
- 输出字节数：864
- 产品代码哈希：63ce041fae999aad55cbd1cedf8addd5bcc20521f97d62d15fbc59775424f0aa
- 测试代码哈希：3d4561c53aaa16913c21b06fea56568836aa7efc5511580d620c6148f869a83b
- 实际结果：机器查询到 `v0.1.0` 对应提交 `f612e7d724ff34606919a5951545966c1efbcf1d`，第 7 次标签任务的版本核对、完整测试、构建、macOS、Ubuntu、Windows、PyPI 和 GitHub Release 作业全部为 `success`（成功）。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260804T080254+0000-41b7cb60；完整输出由哈希 239e72b586519b0b290791dacc0363aa04f47c1f26770ef2b2fcb4387ddd4c68 和字节数 864 绑定；任务：https://github.com/yuzyf/workflow_loop/actions/runs/30891477196

### TC-05：PyPI 与 GitHub 正式发布内容一致

- 对应验收条件：[AC-03：两个公开渠道内容一致](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-03)
- 测试方式：自动化测试
- 测试入口：["tests/release_publication_checks.py::test_pypi_and_github_release_contents_match"]
- 执行命令：["scripts/test_all.sh","-s","tests/release_publication_checks.py::test_pypi_and_github_release_contents_match"]
- 机器记录编号：RUN-20260804T082152+0000-d34450df
- 工作目录：项目根
- 超时（秒）：600
- 运行环境：平台=darwin；可执行文件=scripts/test_all.sh
- 开始时间：2026-08-04T08:21:52+00:00
- 结束时间：2026-08-04T08:21:56+00:00
- 时长（秒）：3.647
- 退出码：0
- 输出摘要："PUBLIC_RELEASE_CONTENT: {\"github\": {\"assets\": [\"install.ps1\", \"install.sh\"], \"name\": \"Workflow Loop 0.1.0\", \"tag\": \"v0.1.0\", \"url\": \"https://github.com/yuzyf/workflow_loop/releases/tag/v0.1.0\"}, \"pypi\": {\"author\": \"yuzyf\", \"distributions\": [\"workflow_loop-0.1.0-py3-none-any.whl\", \"workflow_loop-0.1.0.tar.gz\"], \"license_expression\": \"MIT\", \"name\": \"workflow-loop\", \"project_urls\": {\"Homepage\": \"https://github.com/yuzyf/workflow_loop\", \"Repository\": \"https://github.com/yuzyf/workflow_loop\"}, \"summary\": \"为 AI 驱动的软件开发提供有状态、可验证、可回退的工作流管理。\", \"version\": \"0.1.0\"}}\n.\n1 passed in 3.49s\n"
- 输出哈希：57b87e8d689c72fcea136de841901a39e6f245b759aefcb12e002cd54c9b4b43
- 输出字节数：638
- 产品代码哈希：63ce041fae999aad55cbd1cedf8addd5bcc20521f97d62d15fbc59775424f0aa
- 测试代码哈希：3d4561c53aaa16913c21b06fea56568836aa7efc5511580d620c6148f869a83b
- 实际结果：机器从两个公开接口确认 GitHub Release 名称为 `Workflow Loop 0.1.0`，标签为 `v0.1.0`，附件为两个安装脚本；PyPI 同时提供 wheel 和源码分发包，版本、作者、MIT 许可证、中文简介和新仓库链接一致。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260804T082152+0000-d34450df；完整输出由哈希 57b87e8d689c72fcea136de841901a39e6f245b759aefcb12e002cd54c9b4b43 和字节数 638 绑定；GitHub Release：https://github.com/yuzyf/workflow_loop/releases/tag/v0.1.0；PyPI：https://pypi.org/project/workflow-loop/0.1.0/

### TC-06：从公网全新安装得到正确命令身份

- 对应验收条件：[AC-04：公开安装得到正确版本](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-04)
- 测试方式：自动化测试
- 测试入口：["tests/release_publication_checks.py::test_clean_install_uses_public_pypi_package"]
- 执行命令：["scripts/test_all.sh","-s","tests/release_publication_checks.py::test_clean_install_uses_public_pypi_package"]
- 机器记录编号：RUN-20260804T082156+0000-c646710e
- 工作目录：项目根
- 超时（秒）：600
- 运行环境：平台=darwin；可执行文件=scripts/test_all.sh
- 开始时间：2026-08-04T08:21:56+00:00
- 结束时间：2026-08-04T08:22:03+00:00
- 时长（秒）：7.241
- 退出码：0
- 输出摘要："PUBLIC_INSTALL: {\"cache_disabled\": true, \"download_url\": \"https://files.pythonhosted.org/packages/ba/5a/28a62747d78498da5ef910d6b47157351bd705b6674483eaf23afd1ac5e2/workflow_loop-0.1.0-py3-none-any.whl\", \"identity\": \"workflow-loop 0.1.0\", \"index\": \"https://pypi.org/simple\", \"local_sources_disabled\": true, \"requested\": \"workflow-loop==0.1.0\", \"sha256\": \"3ef61843fe752b7f45d6cbe9f8cc95a6ab543ecfad4cc0e9e1ba06f7fe7ed4bd\"}\n.\n1 passed in 7.14s\n"
- 输出哈希：1a2a744052cdc54aa235ca6c6ec0d90e6470238ecaf38fdb53d2bb617261d8b7
- 输出字节数：442
- 产品代码哈希：63ce041fae999aad55cbd1cedf8addd5bcc20521f97d62d15fbc59775424f0aa
- 测试代码哈希：3d4561c53aaa16913c21b06fea56568836aa7efc5511580d620c6148f869a83b
- 实际结果：机器在禁用本地源码和缓存的全新环境中，从 `https://pypi.org/simple` 请求 `workflow-loop==0.1.0`，下载来源为 `files.pythonhosted.org`，安装后的命令身份为 `workflow-loop 0.1.0`。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260804T082156+0000-c646710e；完整输出由哈希 1a2a744052cdc54aa235ca6c6ec0d90e6470238ecaf38fdb53d2bb617261d8b7 和字节数 442 绑定；公开 wheel 摘要为 3ef61843fe752b7f45d6cbe9f8cc95a6ab543ecfad4cc0e9e1ba06f7fe7ed4bd。

### TC-07：两个附件可下载且三平台证据属于最终标签

- 对应验收条件：[AC-04：公开安装得到正确版本](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md#ac-04)
- 测试方式：自动化测试
- 测试入口：["tests/release_publication_checks.py::test_release_assets_and_platform_evidence_match_final_tag"]
- 执行命令：["scripts/test_all.sh","-s","tests/release_publication_checks.py::test_release_assets_and_platform_evidence_match_final_tag"]
- 机器记录编号：RUN-20260804T082203+0000-ed9d5f68
- 工作目录：项目根
- 超时（秒）：600
- 运行环境：平台=darwin；可执行文件=scripts/test_all.sh
- 开始时间：2026-08-04T08:22:03+00:00
- 结束时间：2026-08-04T08:22:16+00:00
- 时长（秒）：13.076
- 退出码：0
- 输出摘要："RELEASE_ASSETS_AND_PLATFORMS: {\"assets\": {\"install.ps1\": {\"download_url\": \"https://github.com/yuzyf/workflow_loop/releases/download/v0.1.0/install.ps1\", \"sha256\": \"a65ef568905674b1e018ab5590d8bae0e4c78c0bd2dca87d44e2f536e5037182\", \"size\": 15794}, \"install.sh\": {\"download_url\": \"https://github.com/yuzyf/workflow_loop/releases/download/v0.1.0/install.sh\", \"sha256\": \"ccca5cf090d0278802f0b4c9cb50e49a46ebfe31e11778ad9b7be4695fe70137\", \"size\": 15460}}, \"commit\": \"f612e7d724ff34606919a5951545966c1efbcf1d\", \"platform_steps\": {\"prepublish-smoke (macos-latest)\": [\"安装脚本冒烟：确认、取消与安装（macOS）\"], \"prepublish-smoke (ubuntu-latest)\": [\"安装脚本冒烟：确认、取消与安装（Linux）\"], \"prepublish-smoke (windows-latest)\": [\"安装脚本冒烟：PowerShell 7（Windows）\", \"安装脚本冒烟：Windows PowerShell 5.1（Windows）\"]}, \"run_url\": \"https://github.com/yuzyf/workflow_loop/actions/runs/30891477196\", \"tag\": \"v0.1.0\"}\n.\n1 passed in 12.97s\n"
- 输出哈希：761ca375ed01cbfc6e0a88b7127cd37d373a0b59f0ceb017dcfbca5f0573d804
- 输出字节数：985
- 产品代码哈希：63ce041fae999aad55cbd1cedf8addd5bcc20521f97d62d15fbc59775424f0aa
- 测试代码哈希：3d4561c53aaa16913c21b06fea56568836aa7efc5511580d620c6148f869a83b
- 实际结果：机器从公开 GitHub Release 下载两个安装附件并核对其大小和 SHA-256（文件内容摘要），确认它们属于 `v0.1.0` 的最终提交；同一标签任务包含 macOS、Ubuntu、PowerShell 7 和 Windows PowerShell 5.1 的成功步骤。
- 自动化测试结果：通过
- 证据：机器记录编号 RUN-20260804T082203+0000-ed9d5f68；完整输出由哈希 761ca375ed01cbfc6e0a88b7127cd37d373a0b59f0ceb017dcfbca5f0573d804 和字节数 985 绑定；安装附件：https://github.com/yuzyf/workflow_loop/releases/tag/v0.1.0；标签任务：https://github.com/yuzyf/workflow_loop/actions/runs/30891477196

## 4. 人工验收交接

- 人工验收对象：标签推送前的公共版本空缺记录、最终提交与本地标签对应关系，以及用户批准推送标签的对话记录。
- 人工检查方法：核对 TC-02 的机器记录时间、三个 404 响应和三个相同提交编号，再核对机器结果展示后、标签推送前用户对唯一确认问题回复了“可以”。
- 自动化已经证明：批准前 GitHub 远程标签、GitHub Release 和 PyPI `0.1.0` 都不存在，本地标签、远程主分支和当前提交完全一致，所需发布文件齐全。
- 还需要用户确认：主题验收时确认“可以”就是在看到上述预检事实后，对推送不可逆的 `v0.1.0` 标签并触发正式发布的明确批准。
- 人工结果填写位置：`acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收结果.md`

## 5. 未通过或阻塞

暂无

## 6. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [验收计划](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收计划.md) | 说明什么算完成 |
| 上游 | [测试计划](./0_1_0_在_GitHub_和_PyPI_完成正式发布_测试计划.md) | 说明本次覆盖哪些测试项 |
| 上游 | [实施记录](../impl/0_1_0_在_GitHub_和_PyPI_完成正式发布_实施记录.md) | 说明本次代码怎样实现 |
| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整链路 |
| 下游 | [主题验收](../acceptance/0_1_0_在_GitHub_和_PyPI_完成正式发布_验收结果.md) | 混合测试在这里接收人工确认 |
