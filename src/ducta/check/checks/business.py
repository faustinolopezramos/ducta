"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0

Business rule quality checks.
"""

import ast
from typing import Any, ClassVar, Dict, FrozenSet, Optional

from loguru import logger

from ducta.check.core import (
    BaseQualityCheck,
    CheckResult,
    CheckSeverity,
    DFAdapter,
    register_check,
)


@register_check("business_rules")
class BusinessRulesCheck(BaseQualityCheck):
    """Validates custom business rules on data (SQL WHERE clauses or Python lambdas)."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset(
        {"max_failures_allowed", "max_rows", "rule_type", "rules"}
    )

    def __init__(self) -> None:
        super().__init__("business_rules", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute business rules check."""
        if not getattr(config, "enabled", True):
            return self._create_result(True, "Check disabled")

        rules = config.rules if hasattr(config, "rules") else []
        rule_type = config.rule_type if hasattr(config, "rule_type") else "sql"
        try:
            max_failures_allowed = int(getattr(config, "max_failures_allowed", 0) or 0)
        except (TypeError, ValueError):
            max_failures_allowed = 0

        if not rules:
            return self._create_result(True, "No rules configured", {})

        if rule_type not in ("sql", "python"):
            # `continue`-ing past every rule reported "All business rules passed (0
            # violations)" for `rule_type: pyhton`: nothing had been checked.
            return self._create_result(
                False,
                f"Unknown rule_type {rule_type!r}: no rule was checked. Use 'sql' or 'python'.",
                {"rule_type": rule_type, "rules_unchecked": len(rules)},
                severity=CheckSeverity.ERROR,
            )

        violations_by_rule = {}
        rule_errors = {}
        total_violations = 0

        rows = None
        if rule_type == "python":
            # Collected once for every rule, and only when the driver can hold it.
            rows = self._rows_for_python_rules(adapter, getattr(config, "max_rows", None))
            if isinstance(rows, CheckResult):
                return rows

        for rule in rules:
            try:
                if rule_type == "sql":
                    violations = self._execute_sql_rule(adapter, rule)
                else:
                    violations = self._execute_python_rule(adapter, rule, pdf=rows)

                violations_by_rule[rule] = violations
                total_violations += int(violations)

            except Exception as e:
                logger.warning(f"Error executing rule '{rule}': {e}")
                rule_errors[rule] = str(e)

        details = {
            "violations_by_rule": violations_by_rule,
            "rule_errors": rule_errors,
            "rule_errors_count": len(rule_errors),
            "total_violations": total_violations,
            "max_failures_allowed": max_failures_allowed,
        }

        violations_exceeded = total_violations > max_failures_allowed

        if rule_errors and violations_exceeded:
            return self._create_result(
                False,
                f"Business rules validation failed: {total_violations} violation(s) "
                f"> {max_failures_allowed} allowed, and {len(rule_errors)} rule(s) "
                f"failed to execute",
                details,
            )

        if rule_errors:
            # A rule that couldn't even execute (SQL syntax error, an
            # exception in a Python lambda, ...) is an unverified rule,
            # not a milder case than one that ran and found violations —
            # WARNING here would silently downgrade "we don't know if
            # this data violates the rule" below a known assertion
            # failure, which is backwards.
            return self._create_result(
                False,
                f"Business rules completed with {len(rule_errors)} rule execution error(s)",
                details,
                severity=CheckSeverity.ERROR,
            )

        if violations_exceeded:
            return self._create_result(
                False,
                f"Business rules validation failed: {total_violations} violation(s) "
                f"> {max_failures_allowed} allowed",
                details,
            )

        return self._create_result(
            True,
            f"All business rules passed ({total_violations} violation(s) within threshold)",
            details,
        )

    @staticmethod
    def _execute_sql_rule(adapter: DFAdapter, rule: str) -> int:
        """Execute a SQL WHERE rule and count violations.

        A row violates the rule unless the rule is TRUE for it. ``NOT (rule)`` alone drops
        the rows where the rule is NULL (``amount > 0`` with a null amount), so a null
        passed here while the Python rule type counts it as a violation.
        """
        if adapter.engine != "spark":
            raise ValueError(
                f"SQL rules only supported for Spark engine, got '{adapter.engine}'. "
                "Use rule_type='python' for Pandas/Polars engines."
            )

        BusinessRulesCheck._validate_sql_rule(rule)

        try:
            violations = adapter.filter_where(f"NOT COALESCE(({rule}), FALSE)")
            return violations
        except Exception as e:
            raise ValueError(f"SQL rule execution failed for rule '{rule}': {e}")

    @staticmethod
    def _validate_sql_rule(rule: str) -> None:
        """Reject a rule that is more than a plain predicate (see :func:`ducta.gate.sql.validate_predicate`)."""
        from ducta.gate.sql import validate_predicate

        validate_predicate(rule)

    _SAFE_BUILTINS: Dict[str, Any] = {
        name: getattr(__import__("builtins"), name)
        for name in (
            "abs",
            "bool",
            "dict",
            "float",
            "int",
            "len",
            "list",
            "max",
            "min",
            "round",
            "set",
            "str",
            "sum",
            "tuple",
        )
    }

    def _rows_for_python_rules(self, adapter: DFAdapter, max_rows: Any) -> Any:
        """The data as pandas for Python rules, or a failed result when it is too big.

        A Python rule runs row by row on the driver, so a Spark frame is collected
        whole: with no guard a large table took the driver down (an OOM, not a
        failed check). The limit is the one vectorized nodes use.
        """
        from ducta.core.commands import DEFAULT_VECTORIZED_MAX_ROWS

        try:
            limit = int(max_rows) if max_rows else DEFAULT_VECTORIZED_MAX_ROWS
        except (TypeError, ValueError):
            limit = DEFAULT_VECTORIZED_MAX_ROWS
        if adapter.engine == "spark" and adapter.df.limit(limit + 1).count() > limit:
            return self._create_result(
                False,
                f"Python rules need the whole dataset on the driver, and it has more than "
                f"{limit:,} rows: no rule was checked. Use rule_type: sql, or raise "
                "max_rows if the driver can hold it.",
                {"max_rows": limit},
                severity=CheckSeverity.ERROR,
            )
        try:
            return adapter.to_pandas()
        except Exception as e:  # noqa: BLE001 — each rule then reports the failure itself
            logger.debug("Could not collect the data for Python rules: {}", e)
            return None

    @staticmethod
    def _execute_python_rule(adapter: DFAdapter, rule: str, pdf: Any = None) -> int:
        """Execute a Python lambda rule and count violations.

        The lambda receives each DataFrame row (as a pandas Series) so rules can
        reference any column: ``lambda row: row['amount'] > 0``.
        """
        try:
            BusinessRulesCheck._validate_lambda_expression(rule)
            if pdf is None:
                pdf = adapter.to_pandas()
            if pdf.empty:
                return 0

            lambda_func = eval(  # noqa: S307  # validated by _validate_lambda_expression
                rule,
                {"__builtins__": BusinessRulesCheck._SAFE_BUILTINS},
            )
            # Apply to each row so rules can reference any column
            violations = (~pdf.apply(lambda_func, axis=1)).sum()

            return int(violations)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Python rule execution failed for rule '{rule}': {e}")

    _MAX_AST_NODES = 200
    _MAX_NUMERIC_LITERAL = 1_000_000

    @staticmethod
    def _validate_lambda_expression(expression: str) -> None:
        """Validate lambda expression for security."""
        # Forbidden identifier names (builtins and common attack vectors)
        _FORBIDDEN_NAMES = frozenset(
            {
                "__import__",
                "__builtins__",
                "__class__",
                "__base__",
                "__subclasses__",
                "__globals__",
                "__locals__",
                "__code__",
                "__dict__",
                "__mro__",
                "eval",
                "exec",
                "compile",
                "open",
                "input",
                "getattr",
                "setattr",
                "delattr",
                "hasattr",
                "globals",
                "locals",
                "vars",
                "dir",
            }
        )

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid lambda expression: {e}")

        if not isinstance(tree.body, ast.Lambda):
            raise ValueError("Expression must be a lambda, not an arbitrary expression")

        # Allowed function call targets inside a lambda (matches _SAFE_BUILTINS keys)
        _ALLOWED_CALLS = frozenset(
            {
                "abs",
                "bool",
                "dict",
                "float",
                "int",
                "len",
                "list",
                "max",
                "min",
                "round",
                "set",
                "str",
                "sum",
                "tuple",
            }
        )

        _ALLOWED_ATTRIBUTES = frozenset(
            {
                "year",
                "month",
                "day",
                "hour",
                "minute",
                "second",
                "microsecond",
                "nanosecond",
                "date",
                "time",
                "tzinfo",
            }
        )

        node_count = sum(1 for _ in ast.walk(tree))
        if node_count > BusinessRulesCheck._MAX_AST_NODES:
            raise ValueError(
                f"Lambda expression is too complex ({node_count} AST nodes, "
                f"max {BusinessRulesCheck._MAX_AST_NODES})"
            )

        for node in ast.walk(tree):
            # Block import statements
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                raise ValueError("Imports not allowed in lambda expressions")

            # Block forbidden names
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
                raise ValueError(f"Forbidden identifier in lambda: {node.id!r}")

            # The AST node cap above bounds *shape*, not *cost*: an
            # expression as short as `2**100000000` has only a handful of
            # nodes but can burn CPU/memory disproportionately once eval'd.
            # `**` isn't needed for business-rule predicates, so block it
            # outright rather than try to bound "safe" exponents.
            if isinstance(node, ast.Pow):
                raise ValueError("The '**' (power) operator is not allowed in lambda expressions")

            # Cap numeric literal magnitude too — guards against huge
            # literals feeding other costly operations (e.g. giant
            # multiplications or repeated string construction) that don't
            # go through Pow.
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if abs(node.value) > BusinessRulesCheck._MAX_NUMERIC_LITERAL:
                    raise ValueError(
                        f"Numeric literal {node.value!r} exceeds the maximum allowed "
                        f"magnitude ({BusinessRulesCheck._MAX_NUMERIC_LITERAL}) in "
                        "lambda expressions"
                    )

            # Block attribute access except for the allowed whitelist
            if isinstance(node, ast.Attribute):
                if node.attr not in _ALLOWED_ATTRIBUTES:
                    raise ValueError(
                        f"Attribute access to {node.attr!r} not allowed in lambda expressions"
                    )

            if isinstance(node, ast.Call):
                callee = node.func
                if not isinstance(callee, ast.Name):
                    raise ValueError(
                        "Only direct function calls to allowed builtins are "
                        "permitted in lambda expressions"
                    )
                if callee.id not in _ALLOWED_CALLS:
                    raise ValueError(
                        f"Function call to {callee.id!r} is not allowed in lambda expressions"
                    )
