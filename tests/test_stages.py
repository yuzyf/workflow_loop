from workflow_loop.stages.stages import ProjectDesignInitStage, SpecStage


def _write(path, content="ready"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_spec_stage_accepts_english_feature_filename(tmp_path):
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "feature_product_design_document_generation.md")

    ok, detail = SpecStage().code_validate(str(tmp_path))

    assert ok is True
    assert "feature_product_design_document_generation.md" in detail


def test_spec_stage_rejects_legacy_chinese_feature_filename(tmp_path):
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "功能产品文档生成.md")

    ok, detail = SpecStage().code_validate(str(tmp_path))

    assert ok is False
    assert "feature_*.md" in detail


def test_project_design_init_accepts_english_feature_filename(tmp_path):
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "feature_existing_product.md")
    _write(tmp_path / "spec" / "architecture_code_design.md")

    ok, detail = ProjectDesignInitStage().code_validate(str(tmp_path))

    assert ok is True
    assert "feature_existing_product.md" in detail


def test_project_design_init_rejects_legacy_chinese_feature_filename(tmp_path):
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "功能已有产品.md")
    _write(tmp_path / "spec" / "architecture_code_design.md")

    ok, detail = ProjectDesignInitStage().code_validate(str(tmp_path))

    assert ok is False
    assert "spec/feature_*.md" in detail


def test_project_design_init_loads_specialized_and_shared_documents():
    stage = ProjectDesignInitStage()

    assert stage.prompt_doc_path() == "Template_Repository/code_design/project_design_init.md"
    assert stage.standard_doc_path() == "Standardized_Repository/code_design/project_design_init.md"
    assert stage.additional_doc_paths() == [
        ("Template_Repository/spec/spec.md", "Standardized_Repository/spec/spec.md"),
        ("Template_Repository/code_design/code_design.md", "Standardized_Repository/code_design/code_design.md"),
    ]
    assert "必须查看代码和测试" in stage.instruction()
