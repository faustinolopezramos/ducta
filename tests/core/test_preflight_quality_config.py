"""Regression: preflight passed configs that were plainly wrong.

`QualityCheckEntrySchema` and `NodeSchema` are `extra="allow"` on purpose —
plugin checks registered through `register_check` define their own parameters,
and streaming nodes carry inline connector configs no fixed schema can
enumerate. The cost was that misspellings inside those blocks validated clean
and then changed behaviour in silence:

  * `row_cont:` instead of `row_count:` — `ducta config validate` reported
    "✓ etl: OK", and the run then failed as *"Quality gate blocked: 1 ERROR
    failure"*, which reads as a problem with the data rather than with a config
    that was never a valid check.
  * `row_count: {minimum: 400}` — the key is dropped, so the check runs with no
    minimum and passes on any row count at all.
  * `behavior: halt_everything` — falls back to `skip_downstream` at runtime.
  * `dependencie:` — the ordering it was meant to declare is simply lost.

`extra="allow"` stays; the validation lives in preflight, where it can know the
registry.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta.check.core import QUALITY_CHECKS_REGISTRY, BaseQualityCheck
from ducta.core.preflight import validate_pipeline


def _context(node_config, global_config=None):
    return SimpleNamespace(
        pipelines={"etl": {"type": "batch", "nodes": ["transform"], "requires_dates": False}},
        nodes_config={"transform": node_config},
        input_config={},
        output_config={},
        global_config=global_config or {},
    )


def _node(**overrides):
    node = {"module": "m", "function": "f", "input": [], "output": []}
    node.update(overrides)
    return node


#: These fixtures use a placeholder module, so `_check_node_function` always
#: reports it as unloadable. That is a different concern, covered elsewhere;
#: filtering it out keeps `== []` assertions here about the config validation
#: under test rather than about the fixture.
_UNRELATED = "cannot load function"


def _errors(context):
    return [e for e in validate_pipeline(context, "etl").errors if _UNRELATED not in e]


def _warnings(context):
    return validate_pipeline(context, "etl").warnings


class TestCheckNames:
    def test_an_unregistered_check_name_is_an_error(self):
        context = _context(_node(data_quality={"checks": {"row_cont": {"min": 1}}}))

        errors = _errors(context)

        assert any("row_cont" in e for e in errors)
        # It must name the failure mode, not just the symptom.
        assert any("registered check" in e for e in errors)

    def test_the_error_lists_what_is_available(self):
        context = _context(_node(data_quality={"checks": {"row_cont": {}}}))

        error = next(e for e in _errors(context) if "row_cont" in e)

        assert "row_count" in error

    def test_a_valid_check_passes(self):
        context = _context(_node(data_quality={"checks": {"row_count": {"min": 400}}}))

        assert _errors(context) == []

    def test_type_names_the_check_when_the_entry_is_a_custom_label(self):
        """`{type: row_count}` is how a node runs two instances of one check."""
        context = _context(
            _node(data_quality={"checks": {"at_least_400": {"type": "row_count", "min": 400}}})
        )

        assert _errors(context) == []

    def test_a_bad_type_is_reported_against_the_type_not_the_label(self):
        context = _context(
            _node(data_quality={"checks": {"at_least_400": {"type": "row_cont", "min": 400}}})
        )

        error = next(e for e in _errors(context) if "row_cont" in e)

        assert "type" in error

    def test_sanity_checks_are_validated_too(self):
        context = _context(_node(sanity_checks={"checks": {"empty_datasett": {}}}))

        assert any("empty_datasett" in e for e in _errors(context))

    def test_shared_quality_profiles_are_validated(self):
        context = _context(
            _node(),
            global_config={"quality": {"profiles": {"default": {"checks": {"row_cont": {}}}}}},
        )

        errors = _errors(context)

        assert any("row_cont" in e and "profile" in e.lower() for e in errors)


class TestCheckParameters:
    def test_an_unknown_parameter_is_an_error(self):
        context = _context(_node(data_quality={"checks": {"row_count": {"minimum": 400}}}))

        error = next(e for e in _errors(context) if "minimum" in e)

        assert "row_count" in error
        assert "min" in error  # the accepted keys are listed

    def test_common_keys_are_accepted_on_every_check(self):
        context = _context(
            _node(
                data_quality={
                    "checks": {"row_count": {"min": 1, "enabled": True, "severity": "warning"}}
                }
            )
        )

        assert _errors(context) == []

    def test_engine_injected_keys_are_not_user_configuration(self):
        """`_baseline`/`_history` are put there by the engine, not the author."""
        context = _context(
            _node(data_quality={"checks": {"anomaly_detection": {"_baseline": {}, "columns": []}}})
        )

        assert _errors(context) == []

    def test_a_check_that_declares_nothing_is_left_alone(self):
        """A plugin check may not declare CONFIG_PARAMS; its params aren't guessed."""

        class UndeclaredCheck(BaseQualityCheck):
            def __init__(self):
                super().__init__("undeclared_probe")

            def run(self, df, config, adapter, context_datasets=None):  # pragma: no cover
                raise NotImplementedError

        QUALITY_CHECKS_REGISTRY["undeclared_probe"] = UndeclaredCheck
        try:
            assert UndeclaredCheck.CONFIG_PARAMS is None
            context = _context(
                _node(data_quality={"checks": {"undeclared_probe": {"whatever": 1}}})
            )
            assert _errors(context) == []
        finally:
            del QUALITY_CHECKS_REGISTRY["undeclared_probe"]

    @pytest.mark.parametrize("name", sorted(QUALITY_CHECKS_REGISTRY))
    def test_every_built_in_check_declares_its_parameters(self, name):
        """Otherwise this validation quietly stops covering that check."""
        assert QUALITY_CHECKS_REGISTRY[name].CONFIG_PARAMS is not None


class TestQualityGateBehavior:
    def test_an_unknown_behavior_is_an_error(self):
        context = _context(
            _node(data_quality={"checks": {}, "quality_gate": {"behavior": "halt_everything"}})
        )

        error = next(e for e in _errors(context) if "halt_everything" in e)

        assert "skip_downstream" in error  # says what it would silently become

    @pytest.mark.parametrize(
        "behavior", ["skip_downstream", "stop_all", "warn_only", "block", "warn"]
    )
    def test_valid_behaviors_and_their_aliases_pass(self, behavior):
        context = _context(
            _node(data_quality={"checks": {}, "quality_gate": {"behavior": behavior}})
        )

        assert _errors(context) == []


class TestUnknownNodeKeys:
    def test_a_misspelled_node_key_is_warned_about(self):
        context = _context(_node(dependencie=["extract"]))

        warning = next(w for w in _warnings(context) if "dependencie" in w)

        assert "ignored" in warning

    def test_it_is_a_warning_not_an_error(self):
        """An unknown key may be a forward-compatible extension; don't block the run."""
        context = _context(_node(dependencie=["extract"]))

        assert _errors(context) == []

    def test_known_keys_produce_no_warning(self):
        context = _context(_node(dependencies=[], retry=2, description="d", type="batch"))

        assert _warnings(context) == []
