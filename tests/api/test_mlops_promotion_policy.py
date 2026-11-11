"""POST /api/mlops/models/{name}/promote reads mlops.promotion_policy as the CLI does.

An invalid policy was ignored with a warning, and the version went to Production
without its gate; the CLI refused the same promotion.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta.api.exceptions import ValidationError
from ducta.api.routes.mlops import _promotion_policy
from ducta.mlrun.model_registry import ModelStage


def _scope(policy):
    mlops = {} if policy is ... else {"promotion_policy": policy}
    return SimpleNamespace(global_config={"mlops": mlops})


@pytest.mark.parametrize("policy", [["auc"], {}, {"min_delta": 0.01}, "auc"])
def test_an_invalid_policy_refuses_a_production_promotion(policy):
    with pytest.raises(ValidationError, match="promotion gate"):
        _promotion_policy(_scope(policy), ModelStage.PRODUCTION, force=False)


def test_force_promotes_without_the_gate():
    assert _promotion_policy(_scope({}), ModelStage.PRODUCTION, force=True) is None


def test_a_valid_policy_is_applied():
    policy = _promotion_policy(_scope({"metric": "auc"}), ModelStage.PRODUCTION, force=False)
    assert policy is not None and policy.metric == "auc"


def test_no_policy_and_other_stages_need_none():
    assert _promotion_policy(_scope(...), ModelStage.PRODUCTION, force=False) is None
    assert _promotion_policy(_scope({}), ModelStage.STAGING, force=False) is None
