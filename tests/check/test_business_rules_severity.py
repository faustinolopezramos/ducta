"""Regression: BusinessRulesCheck downgraded a rule that couldn't even
execute (not just one that ran and found violations) to WARNING severity —
backwards, since "we don't know if this data violates the rule" is not a
milder case than a known assertion failure.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from ducta.check.checks.business import BusinessRulesCheck
from ducta.check.core import CheckSeverity, DFAdapter


class TestBusinessRulesExecutionErrorSeverity:
    def test_rule_execution_error_is_error_severity_not_warning(self):
        check = BusinessRulesCheck()
        df = pd.DataFrame({"amount": [1, 2, 3]})
        adapter = DFAdapter(df)
        config = SimpleNamespace(
            rules=["amount > 0"],
            rule_type="sql",  # SQL rules require a Spark adapter; this one is pandas.
            max_failures_allowed=100,  # high enough that violations alone wouldn't fail
        )

        result = check.run(df=df, config=config, adapter=adapter)

        assert result.passed is False
        assert result.severity == CheckSeverity.ERROR
        assert result.details["rule_errors_count"] == 1
