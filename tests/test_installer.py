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
    # 验证 Template_Repository/ 被创建（stage 模板源）
    assert os.path.exists(os.path.join(str(tmp_path), ".workflow_loop", "Template_Repository"))
    # 验证 Standardized_Repository/ 被创建（标准化产出归档）
    assert os.path.exists(os.path.join(str(tmp_path), ".workflow_loop", "Standardized_Repository"))
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
    # 验证 code_design/revise_code_design.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "code_design", "revise_code_design.md"))
    # 验证 code_design/project_design_init.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "code_design", "project_design_init.md"))
    # 验证 code_design/update_code_design.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "code_design", "update_code_design.md"))
    # 验证 spike/spike.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "spike", "spike.md"))
    # 验证 plan/plan.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "plan", "plan.md"))
    # 验证 plan/fix_plan.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "plan", "fix_plan.md"))
    # 验证 qa/acceptance_plan.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "qa", "acceptance_plan.md"))
    # 验证 qa/acceptance.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "qa", "acceptance.md"))
    # 验证 qa/test_plan.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "qa", "test_plan.md"))
    # 验证 qa/test.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "qa", "test.md"))
    # 验证 impl/impl.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "impl", "impl.md"))
    # 验证 reproduce/reproduce.md 模板存在
    assert os.path.exists(os.path.join(template_dir, "reproduce", "reproduce.md"))


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


# 测试 install_project 不创建产品目录（spec/plan/acceptance 等是 Run 时产物）
def test_install_project_no_product_dirs(tmp_path):
    # 执行安装
    install_project(str(tmp_path))
    # 遍历所有产品目录名
    for d in ["spec", "plan", "acceptance", "qa", "impl", "bug"]:
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
