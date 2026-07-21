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
