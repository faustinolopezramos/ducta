"""What the model is told about a project: bounded, examples first, no secrets."""

from __future__ import annotations

from ducta.ai.context import build_context, redact
from tests.ai.test_builder import _project


def test_a_large_project_keeps_its_examples_and_says_what_it_left_out(tmp_path):
    root = _project(tmp_path)
    helpers = root / "src" / "helpers"
    helpers.mkdir()
    for i in range(300):
        body = "\n".join(f"def public_{j}(a, b, c):\n    pass" for j in range(10))
        (helpers / f"h{i}.py").write_text(body)
    text = build_context(root).render(max_chars=20_000)
    assert len(text) <= 20_000
    assert "# Example node function from this project" in text
    assert "# Example pipeline file from this project" in text
    assert "more not listed" in text and "context truncated" not in text


def test_a_small_project_lists_every_function(tmp_path):
    ctx = build_context(_project(tmp_path))
    assert ctx.functions == ["- src.m:clean(orders)"]
    assert "- src.m:clean(orders)" in ctx.render()


def test_skipped_and_hidden_folders_are_not_read(tmp_path):
    root = _project(tmp_path)
    for folder in ("data/part=1", "venv/x", ".cache", "node_modules/y"):
        (root / folder).mkdir(parents=True)
        (root / folder / "noise.py").write_text("def noise():\n    pass\n")
    assert not any("noise" in f for f in build_context(root).functions)


def test_catalog_defaults_show_only_the_format(tmp_path):
    root = _project(tmp_path)
    (root / "ducta.yaml").write_text(
        "version: 2\nproject: p\npaths: {input: d, output: d}\n"
        "defaults:\n  catalog:\n    'silver.*': {format: delta, path: abfss://lake@acct/silver}\n"
    )
    text = build_context(root).render()
    assert "silver.*: format delta" in text
    assert "abfss://" not in text


def test_a_cut_never_leaves_a_fence_open(tmp_path):
    text = build_context(_project(tmp_path)).render(max_chars=300)
    assert text.count("```") % 2 == 0 and text.endswith("(context truncated)")


def test_redact_masks_common_credentials():
    text = redact(
        "jdbc:sqlserver://h;password=p4ss; url=https://u:tok@host/x "
        "Authorization: Bearer abc.def api_key='k1' sig=zzz rows=10"
    )
    for secret in ("p4ss", "tok@", "abc.def", "k1", "zzz"):
        assert secret not in text
    assert "rows=10" in text and "https://u:***@host/x" in text
