import os

from workflow_loop.installer import install_project
from workflow_loop.project import load_project, is_installed


# 测试 install_project 创建所有必要的目录和文件（.workflow_loop/、project.json、AGENTS.md 等）
def test_install_project_creates_all(tmp_path):
    # 执行安装
    code = install_project(str(tmp_path))
    # 验证返回码 0（成功）
    assert code == 0
    # 验证 .workflow_loop/ 目录被创建
    assert os.path.exists(os.path.join(str(tmp_path), ".workflow_loop"))
    # 验证 project.json 被创建
    assert os.path.exists(os.path.join(str(tmp_path), ".workflow_loop", "project.json"))
    # 验证 Template_Repository/ 被创建（产物文档模板源）
    assert os.path.exists(os.path.join(str(tmp_path), ".workflow_loop", "Template_Repository"))
    # 验证 Standardized_Repository/ 被创建（阶段工作规范源）
    assert os.path.exists(os.path.join(str(tmp_path), ".workflow_loop", "Standardized_Repository"))
    # 验证所有 stage 共用的全局写作规范被安装
    assert os.path.exists(os.path.join(
        str(tmp_path), ".workflow_loop", "Standardized_Repository",
        "global", "document_writing.md",
    ))
    # 验证 AGENTS.md 被创建（项目根的 agent 契约）
    assert os.path.exists(os.path.join(str(tmp_path), "AGENTS.md"))
    # 验证 is_installed 返回 True
    assert is_installed(str(tmp_path))


# 测试 install_project 拷贝所有 stage 模板文件到 Template_Repository/
def test_install_project_copies_templates(tmp_path):
    # 执行安装
    install_project(str(tmp_path))
    # 拼出 Template_Repository 路径
    template_dir = os.path.join(str(tmp_path), ".workflow_loop", "Template_Repository")
    # 验证 spec/spec.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "spec", "spec.md"))
    # 验证 code_design/code_design.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "code_design", "code_design.md"))
    # 项目设计初始化只有调查证据专用模板；三个代码设计阶段共用 code_design.md
    assert os.path.exists(os.path.join(
        template_dir, "code_design", "project_design_init_evidence.md",
    ))
    assert not os.path.exists(os.path.join(template_dir, "code_design", "revise_code_design.md"))
    assert not os.path.exists(os.path.join(template_dir, "code_design", "project_design_init.md"))
    assert not os.path.exists(os.path.join(template_dir, "code_design", "update_code_design.md"))
    # 验证 spike/spike.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "spike", "spike.md"))
    # 验证 acceptance/ 下的验收计划和主题验收模板存在
    assert os.path.exists(os.path.join(template_dir, "acceptance", "acceptance_plan.md"))
    assert os.path.exists(os.path.join(template_dir, "acceptance", "acceptance_result.md"))
    # 验证 qa/test_plan.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "qa", "test_plan.md"))
    # 验证 qa/test.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "qa", "test.md"))
    # test_code 直接产出代码，没有 Markdown 产物模板。
    assert not os.path.exists(os.path.join(template_dir, "qa", "test_code.md"))
    assert not os.path.exists(os.path.join(template_dir, "qa", "final_regression.md"))
    assert not os.path.exists(os.path.join(template_dir, "acceptance", "overall_acceptance.md"))
    assert not os.path.exists(os.path.join(template_dir, "execution", "topic_execution.md"))
    # 验证 impl/impl.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "impl", "impl.md"))
    # 验证 reproduce/reproduce.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "reproduce", "reproduce.md"))


def test_install_project_uses_english_feature_document_names(tmp_path):
    install_project(str(tmp_path))
    workflow_dir = os.path.join(str(tmp_path), ".workflow_loop")
    prompt_paths = [
        os.path.join(workflow_dir, "Template_Repository", "spec", "spec.md"),
        os.path.join(workflow_dir, "Standardized_Repository", "spec", "spec.md"),
        os.path.join(workflow_dir, "Standardized_Repository", "code_design", "project_design_init.md"),
    ]

    for prompt_path in prompt_paths:
        with open(prompt_path) as f:
            content = f.read()
        assert "feature_" in content
        assert "spec/功能" not in content


def test_install_project_copies_product_background_and_bugfix_rules(tmp_path):
    install_project(str(tmp_path))
    workflow_dir = os.path.join(str(tmp_path), ".workflow_loop")
    template_path = os.path.join(
        workflow_dir, "Template_Repository", "spec", "spec.md",
    )
    standard_path = os.path.join(
        workflow_dir, "Standardized_Repository", "spec", "spec.md",
    )

    with open(template_path) as f:
        template_content = f.read()
    with open(standard_path) as f:
        standard_content = f.read()

    assert "这个产品在什么背景下产生" in template_content
    assert "什么具体产品需求促使设计这个功能" in template_content
    assert "产品设计文档通用规则" in template_content
    assert "代码和运行结果只能证明产品现在怎样工作" in template_content
    assert "说明目前存在什么问题" not in template_content
    assert "通用写作要求" not in template_content
    assert "修复产品缺陷" in standard_content
    assert "需要改变产品行为时改走修改产品流程" in standard_content


def test_install_project_copies_product_driven_code_design_rules(tmp_path):
    install_project(str(tmp_path))
    workflow_dir = os.path.join(str(tmp_path), ".workflow_loop")

    code_template_path = os.path.join(
        workflow_dir, "Template_Repository", "code_design", "code_design.md",
    )
    code_standard_path = os.path.join(
        workflow_dir, "Standardized_Repository", "code_design", "code_design.md",
    )
    init_template_path = os.path.join(
        workflow_dir, "Template_Repository", "code_design", "project_design_init_evidence.md",
    )
    init_standard_path = os.path.join(
        workflow_dir, "Standardized_Repository", "code_design", "project_design_init.md",
    )

    with open(code_template_path) as f:
        code_template = f.read()
    with open(code_standard_path) as f:
        code_standard = f.read()
    with open(init_template_path) as f:
        init_template = f.read()
    with open(init_standard_path) as f:
        init_standard = f.read()

    assert "产品设计决定代码设计" in code_template
    assert "架构图只表达代码分层" in code_template
    assert "每个程序处理节点必须直接标出对应文件和符号" in code_template
    assert "各产品功能的代码设计" in code_template
    assert "由产品职责推导代码架构" in code_standard
    assert "只列函数名不算完成" in code_standard
    assert "不能脱离流程单独列一个看不懂的字段" in code_standard
    assert "项目设计初始化调查证据文档模板" in init_template
    assert "具备安全的本地运行条件时，必须实际运行" in init_standard
    assert "运行确认" in init_standard
    assert "spec/project_design_init_evidence.md" in init_template
    assert "已检查代码" in init_template
    assert "运行条件：具备 | 不具备" in init_template
    assert "场景B" not in code_template
    assert "场景B" not in code_standard


def test_install_project_copies_structured_reproduce_rules(tmp_path):
    install_project(str(tmp_path))
    workflow_dir = os.path.join(str(tmp_path), ".workflow_loop")
    prompt_path = os.path.join(
        workflow_dir, "Template_Repository", "reproduce", "reproduce.md",
    )
    standard_path = os.path.join(
        workflow_dir, "Standardized_Repository", "reproduce", "reproduce.md",
    )

    with open(prompt_path) as f:
        prompt = f.read()
    with open(standard_path) as f:
        standard = f.read()

    assert "缺陷复现文档模板" in prompt
    assert "根因状态：已确认" in prompt
    assert "bug/index.md" in prompt
    assert "真实环境、真实输入" in standard
    assert "程序不能判断证据是否伪造" in standard


def test_install_project_separates_acceptance_templates_and_code_gated_final_stages(tmp_path):
    install_project(str(tmp_path))
    workflow_dir = os.path.join(str(tmp_path), ".workflow_loop")
    template_dir = os.path.join(workflow_dir, "Template_Repository")
    standardized_dir = os.path.join(workflow_dir, "Standardized_Repository")

    assert os.path.exists(os.path.join(template_dir, "acceptance", "acceptance_plan.md"))
    assert os.path.exists(os.path.join(standardized_dir, "acceptance", "acceptance_plan.md"))
    assert not os.path.exists(os.path.join(template_dir, "qa", "acceptance_plan.md"))
    assert not os.path.exists(os.path.join(standardized_dir, "qa", "acceptance_plan.md"))

    assert not os.path.exists(os.path.join(standardized_dir, "qa", "final_regression.md"))
    assert not os.path.exists(os.path.join(standardized_dir, "qa", "overall_acceptance.md"))
    assert not os.path.exists(os.path.join(
        standardized_dir, "acceptance", "overall_acceptance.md",
    ))
    assert os.path.exists(os.path.join(standardized_dir, "qa", "test_code.md"))
    assert os.path.exists(os.path.join(
        standardized_dir, "qa", "test_code_implementation.md",
    ))


def test_install_project_separates_acceptance_document_template_and_work_standard(tmp_path):
    install_project(str(tmp_path))
    workflow_dir = os.path.join(str(tmp_path), ".workflow_loop")
    template_path = os.path.join(
        workflow_dir, "Template_Repository", "acceptance", "acceptance_plan.md",
    )
    standard_path = os.path.join(
        workflow_dir, "Standardized_Repository", "acceptance", "acceptance_plan.md",
    )
    with open(template_path) as f:
        template = f.read()
    with open(standard_path) as f:
        standard = f.read()

    assert "验收计划文档模板" in template
    assert "# 【验收主题】<主题名称>" in template
    assert "需求交付追踪表" in template
    assert "每次只讨论一个需要用户决定的问题" not in template

    assert "验收计划阶段工作规范" in standard
    assert "每次只讨论一个需要用户决定的问题" in standard
    assert "# 【验收主题】<主题名称>" not in standard

    assert not os.path.exists(os.path.join(
        workflow_dir, "Template_Repository", "acceptance", "overall_acceptance.md",
    ))
    assert not os.path.exists(os.path.join(
        workflow_dir, "Standardized_Repository", "acceptance", "overall_acceptance.md",
    ))


def test_install_project_installs_confirmed_test_execution_materials(tmp_path):
    install_project(str(tmp_path))
    workflow_dir = os.path.join(str(tmp_path), ".workflow_loop")
    template_path = os.path.join(
        workflow_dir, "Template_Repository", "qa", "test.md",
    )
    standard_path = os.path.join(
        workflow_dir, "Standardized_Repository", "qa", "test.md",
    )
    with open(template_path) as f:
        template = f.read()
    with open(standard_path) as f:
        standard = f.read()

    assert "# 主题测试结果文档模板" in template
    assert "自动化测试结果：通过" in template
    assert "人工验收状态" in template
    assert "# 主题测试执行阶段工作规范" in standard
    assert "workflow test prepare" in standard
    assert "workflow test run" in standard
    assert "待讨论" not in template
    assert "待讨论" not in standard

    # impl 是当前流程的正式模板，不能再被当成“尚未讨论”的占位文件。
    for parts in [
        ("Template_Repository", "impl", "impl.md"),
        ("Standardized_Repository", "impl", "impl.md"),
    ]:
        path = os.path.join(workflow_dir, *parts)
        with open(path) as f:
            content = f.read()
        assert "实施前计划" in content
        assert "实施后记录" in content
        assert "待讨论" not in content

    template_path = os.path.join(
        workflow_dir, "Template_Repository", "qa", "test_plan.md",
    )
    standard_path = os.path.join(
        workflow_dir, "Standardized_Repository", "qa", "test_plan.md",
    )
    with open(template_path) as f:
        template = f.read()
    with open(standard_path) as f:
        standard = f.read()

    # Template_Repository 是最终测试计划文档模板，不是测试计划阶段工作规范。
    assert "测试计划文档模板" in template
    assert "qa/<topic>_plan.md" in template
    assert "# <主题>测试计划" in template
    assert "全局覆盖审查" not in template
    assert "待讨论" not in template

    # Standardized_Repository 才负责测试计划阶段怎样调查和讨论。
    assert "测试计划阶段规范提示词" in standard
    assert "全局检查顺序" in standard
    assert "阶段职责" in standard
    assert "测试计划文档结构" in standard
    assert "待讨论" not in standard


# 测试 install_project 覆盖 AGENTS.md（首次安装写入 workflow_loop 契约）
def test_install_project_writes_agents_md(tmp_path):
    # 准备一个旧的 AGENTS.md 内容
    custom_agents = "# Custom\n\nOld content that should be overwritten.\n"
    # 写入旧内容
    with open(os.path.join(str(tmp_path), "AGENTS.md"), "w") as f:
        f.write(custom_agents)
    # 执行安装（应覆盖）
    install_project(str(tmp_path))
    # 读回 AGENTS.md
    with open(os.path.join(str(tmp_path), "AGENTS.md")) as f:
        content = f.read()
    # 验证新内容包含 workflow_loop 关键字
    assert "workflow_loop" in content
    # 验证新内容包含 workflow start 命令提示
    assert "workflow start" in content
    # 验证聊天和正式文档从安装后就受核心表达要求约束
    assert "表达要求" in content
    assert "能用直白话就不用抽象词" in content
    assert "删除空泛、重复" in content
    # 验证旧内容被覆盖（不再包含 Custom）
    assert "Custom" not in content


# 测试 install_project 不创建 state.json 和 journal.jsonl（这些是 Run 时产物，不是安装产物）
def test_install_project_no_state_json(tmp_path):
    # 执行安装
    install_project(str(tmp_path))
    # 验证 state.json 不存在（Run 启动后才创建）
    assert not os.path.exists(os.path.join(str(tmp_path), ".workflow_loop", "state.json"))
    # 验证 journal.jsonl 不存在
    assert not os.path.exists(os.path.join(str(tmp_path), ".workflow_loop", "journal.jsonl"))


# 测试 install_project 不创建产品目录（spec/acceptance 等是 Run 时产物）
def test_install_project_no_product_dirs(tmp_path):
    # 执行安装
    install_project(str(tmp_path))
    # 遍历所有产品目录名
    for d in ["spec", "acceptance", "qa", "impl", "bug"]:
        # 验证产品目录不存在
        assert not os.path.exists(os.path.join(str(tmp_path), d))


# 测试重复安装不修改已存在的 AGENTS.md（保护用户自定义内容）
def test_repeat_install_no_modify(tmp_path):
    # 首次安装
    install_project(str(tmp_path))
    # 读回首次安装的 project
    project = load_project(str(tmp_path))
    # 记录原始 installed_at
    original_installed_at = project.installed_at
    # 拼出 AGENTS.md 路径
    agents_path = os.path.join(str(tmp_path), "AGENTS.md")
    # 用户自定义 AGENTS.md 内容
    with open(agents_path, "w") as f:
        f.write("# Modified\n\nUser customized content.\n")
    # 再次安装（应不覆盖已存在的 AGENTS.md）
    code = install_project(str(tmp_path))
    # 验证返回码 0
    assert code == 0
    # 读回 AGENTS.md
    with open(agents_path) as f:
        content = f.read()
    # 验证用户自定义内容保留（未被覆盖）
    assert "Modified" in content
