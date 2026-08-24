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


class TestValidateLambdaExpressionComputationalCost:
    """A short expression can still be computationally expensive once eval'd
    — the AST node-count cap bounds shape, not cost. `2**100000000` has only
    a handful of nodes but can burn CPU/memory disproportionately."""

    def test_power_operator_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression("lambda row: 2**100000000")

    def test_power_operator_rejected_even_with_small_looking_operands(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression("lambda row: row['x'] ** 99999999")

    def test_huge_numeric_literal_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_lambda_expression(
                "lambda row: row['amount'] > 99999999999999"
            )

    def test_ordinary_numeric_literal_and_comparison_accepted(self):
        BusinessRulesCheck._validate_lambda_expression("lambda row: row['amount'] > 1000")


class TestValidateSqlRuleSecurity:
    """rule_type='sql' predicates are interpolated into a raw spark.sql()
    call (DFAdapter.filter_where) — unlike the Python-lambda path above,
    this had no sandboxing at all before this test file covered it."""

    def test_ordinary_predicate_is_accepted(self):
        BusinessRulesCheck._validate_sql_rule("amount > 0")

    def test_string_literal_containing_select_substring_is_not_a_false_positive(self):
        BusinessRulesCheck._validate_sql_rule("status = 'selected'")

    def test_subquery_to_another_table_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_sql_rule(
                "1=1 OR (SELECT COUNT(*) FROM sensitive_table) > 0"
            )

    def test_union_based_exfiltration_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_sql_rule("a=1 UNION SELECT password FROM users")

    def test_stacked_statement_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_sql_rule("1=1; DROP TABLE users; --")

    def test_dangerous_keyword_rejected(self):
        with pytest.raises(ValueError):
            BusinessRulesCheck._validate_sql_rule(
                "1=1 OR EXISTS (SELECT * FROM information_schema.tables)"
            )
