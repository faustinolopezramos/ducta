"""Adversarial regression tests for BusinessRulesCheck's Python-lambda sandbox.

No bypass was found during manual review of `_validate_lambda_expression`
(AST allowlist on names/attributes/calls, node-count cap, import blocking) —
these tests convert that reasoning into an executable safety net for the
specific escape vectors considered, rather than trusting the allowlist by
inspection alone.
"""

from __future__ import annotations

import pytest

from ducta.check.checks.business import BusinessRulesCheck


class TestValidateLambdaExpressionSecurity:
    def test_valid_lambda_is_accepted(self):
        BusinessRulesCheck._validate_lambda_expression("lambda row: row['amount'] > 0")

    def test_non_lambda_expression_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression("__import__('os').system('id')")

    def test_forbidden_name_in_body_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression(
                "lambda row: __import__('os').system('id')"
            )

    def test_attribute_access_outside_whitelist_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression("lambda row: row.__class__")

    def test_call_to_non_whitelisted_name_rejected(self):
        # Blocks method-call-like escapes and self-application recursion alike,
        # since only bare calls to a small builtin allowlist are permitted.
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression(
                "lambda row: (lambda f: f(f))(lambda f: f(f))"
            )

    def test_forbidden_name_in_default_argument_rejected(self):
        # Default argument values are evaluated at lambda-definition time (i.e.
        # inside eval() itself), not at call time — the AST walk must still
        # catch dangerous code hidden there.
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression(
                "lambda row, x=__import__('os').system('id'): True"
            )

    def test_import_statement_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression("lambda row: __import__('os')")

    def test_open_call_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression("lambda row: open('/etc/passwd')")

    def test_overly_complex_expression_rejected(self):
        deeply_nested = "lambda row: " + "abs(" * 250 + "1" + ")" * 250
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression(deeply_nested)
