"""`alerts[].when` lists only what Ducta sends.

`stale` was accepted and never fired: a rule written for it stayed silent forever.
It is now refused when the project loads, with the kinds that do exist.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ducta.setting.project_schema import AlertRule

SLACK = [{"type": "slack", "webhook_env": "SLACK_WEBHOOK_URL"}]


@pytest.mark.parametrize("kind", ["failure", "quality_gate", "sla_miss", "slow"])
def test_the_kinds_that_are_sent(kind):
    assert AlertRule.model_validate({"when": [kind], "channels": SLACK}).when == [kind]


def test_stale_is_refused():
    with pytest.raises(ValidationError, match="sla_miss"):
        AlertRule.model_validate({"when": ["stale"], "channels": SLACK})
