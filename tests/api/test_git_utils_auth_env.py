"""Regression tests for `http_auth_env` (ducta.api.utils.git_utils).

The GitHub/AWS/Azure repository adapters used to embed credentials directly
in the git remote URL (`user:token@host`), which git passes straight through
to its subprocess's argv — readable by any local user via `ps aux` (or
`/proc/<pid>/cmdline`) for as long as clone/push/pull runs. `http_auth_env`
injects the same credential via `GIT_CONFIG_*` env vars (`http.extraHeader`)
instead, which git only reads for its own subcommands and never appears in
argv.
"""

from __future__ import annotations

import base64

from ducta.api.utils.git_utils import http_auth_env


class TestHttpAuthEnv:
    def test_returns_git_config_env_vars_not_a_url(self):
        env = http_auth_env("x-oauth-basic", "ghp_supersecret")
        assert env == {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": (
                "Authorization: Basic "
                + base64.b64encode(b"x-oauth-basic:ghp_supersecret").decode()
            ),
        }

    def test_token_never_appears_in_plain_text(self):
        token = "ghp_supersecret"
        env = http_auth_env("x-oauth-basic", token)
        assert token not in env["GIT_CONFIG_VALUE_0"]
        assert token not in env["GIT_CONFIG_KEY_0"]

    def test_empty_username_supported_for_pat_only_auth(self):
        # Azure DevOps PAT auth uses an empty username.
        env = http_auth_env("", "my-pat")
        expected = base64.b64encode(b":my-pat").decode()
        assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {expected}"

    def test_decodes_back_to_username_colon_token(self):
        env = http_auth_env("bob", "s3cr3t")
        b64 = env["GIT_CONFIG_VALUE_0"].removeprefix("Authorization: Basic ")
        assert base64.b64decode(b64).decode() == "bob:s3cr3t"
