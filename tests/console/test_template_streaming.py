"""The streaming scaffold has to produce a project that actually starts.

Streaming is the pipeline type whose configuration is least guessable, and it
was the one with no scaffold. Three shapes in particular are easy to get wrong
and fail late, each of them caught by writing this template against the running
engine rather than from the docs:

* the trigger is ``{type, interval}``, not Spark's ``{processingTime: ...}``;
* a transform is referenced by ``function.key``, not ``function.name``;
* ``file_stream`` takes ``file_format`` and a top-level ``schema``, with the
  path under ``options`` — a schema nested in ``options`` is passed to Spark,
  ignored, and surfaces as "Schema must be specified when creating a streaming
  source DataFrame".

These assert the shapes against the code that consumes them, so a template that
drifts from the engine fails here rather than in a user's first run.
"""

from __future__ import annotations

import pytest

from ducta.console.core import ConfigFormat
from ducta.console.template import (
    StreamingBasicTemplate,
    TemplateFactory,
    TemplateType,
)
from ducta.stream.validators import StreamingValidator


@pytest.fixture
def template() -> StreamingBasicTemplate:
    return StreamingBasicTemplate("demo", ConfigFormat.YAML)


class TestRegisteredWithTheFactory:
    def test_it_can_be_created_by_type(self):
        created = TemplateFactory.create_template(TemplateType.STREAMING_BASIC, "demo")

        assert isinstance(created, StreamingBasicTemplate)

    def test_it_is_listed(self):
        listed = {t["type"] for t in TemplateFactory.list_available_templates()}

        assert "streaming_basic" in listed
        assert "medallion_basic" in listed, "the original template must still be offered"


class TestGeneratedConfigPassesTheRealValidator:
    """The check that matters: the engine's own validator accepts this config."""

    def test_the_pipeline_validates(self, template):
        pipelines = template.generate_pipelines_config()
        nodes = template.generate_nodes_config()
        pipeline = dict(pipelines["events_stream"])
        pipeline["nodes"] = [{**nodes[name], "name": name} for name in pipeline["nodes"]]

        StreamingValidator().validate_streaming_pipeline_config(pipeline)

    def test_every_node_validates(self, template):
        for name, node in template.generate_nodes_config().items():
            StreamingValidator().validate_streaming_node_config({**node, "name": name})


class TestShapesTheEngineActuallyReads:
    def test_trigger_uses_type_and_interval(self, template):
        """`{processingTime: "5 seconds"}` is Spark's spelling and is rejected."""
        for node in template.generate_nodes_config().values():
            trigger = node["streaming"]["trigger"]
            assert "type" in trigger
            if trigger["type"] in ("processing_time", "continuous"):
                assert trigger.get("interval"), "these trigger types require an interval"

    def test_transform_is_referenced_by_key(self, template):
        """StreamingQueryManager._get_transform_function reads `key`."""
        clean = template.generate_nodes_config()["clean_events"]

        assert clean["function"]["key"] == "clean_events"
        assert "name" not in clean["function"]

    def test_file_stream_puts_schema_and_format_where_the_reader_looks(self, template):
        """FileStreamReader reads `schema`/`file_format` at the top level and
        `path` from options; a schema under options reaches Spark and is dropped."""
        for node in template.generate_nodes_config().values():
            input_config = node["input"]
            if input_config.get("format") != "file_stream":
                continue
            assert input_config.get("schema"), "a stream cannot infer its schema"
            assert input_config.get("file_format")
            assert input_config["options"].get("path")
            assert "schema" not in input_config["options"]
            assert "format" not in input_config["options"]

    def test_each_node_has_its_own_checkpoint(self, template):
        """Two nodes sharing a checkpoint corrupt each other's offsets."""
        locations = [
            node["streaming"]["checkpoint_location"]
            for node in template.generate_nodes_config().values()
        ]

        assert all(locations), "every streaming node needs a checkpoint_location"
        assert len(set(locations)) == len(locations), "checkpoints must not be shared"

    def test_ordering_uses_dependencies_like_batch_nodes(self, template):
        clean = template.generate_nodes_config()["clean_events"]

        assert clean["dependencies"] == ["ingest_events"]
        assert "depends_on" not in clean

    def test_transforms_module_is_auto_registered(self, template):
        """Without this the user must pass --transforms-modules on every run."""
        settings = template.generate_global_config()

        assert template.SAMPLE_MODULE in settings["streaming_transform_modules"]


class TestGeneratedArtefacts:
    def test_the_pipeline_is_not_date_ranged(self, template):
        assert template.generate_pipelines_config()["events_stream"]["requires_dates"] is False

    def test_it_ships_a_transforms_module_defining_register_transforms(self, template):
        code = template.generate_sample_code()

        assert code is not None
        assert "def register_transforms(" in code
        assert "def clean_events(" in code

    def test_it_seeds_events_including_ones_the_transform_drops(self, template):
        """Bronze and silver must visibly differ, or the demo proves nothing."""
        assert template.SAMPLE_EVENTS
        assert any('"amount": null' in event for event in template.SAMPLE_EVENTS)

    def test_it_has_its_own_readme(self, template):
        readme = template.generate_readme_v2()

        assert "ducta stream run" in readme
        assert "checkpoint" in readme.lower()
