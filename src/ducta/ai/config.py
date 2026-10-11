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

Which model Ducta talks to: ``~/.ducta/ai.toml``, then ``DUCTA_AI_*`` variables.

The file holds a provider, a model and where to reach it — never a key. Which
model runs is a property of the machine (a laptop with Ollama, a CI runner with
an API key), not of the project, so nothing here is read from ``ducta.yaml``::

    provider = "ollama"
    model = "qwen2.5-coder:14b"

``DUCTA_HOME`` moves the directory; ``DUCTA_AI_PROVIDER``, ``DUCTA_AI_MODEL``
and ``DUCTA_AI_BASE_URL`` override the file for one shell.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from ducta.ai.errors import AIConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover — 3.10
    import tomli as tomllib

#: The two wire protocols a provider speaks.
OPENAI_COMPATIBLE = "openai_compatible"
ANTHROPIC = "anthropic"


@dataclass(frozen=True)
class Preset:
    kind: str
    base_url: Optional[str]
    api_key_env: Optional[str]
    model: Optional[str] = None
    label: str = ""


#: What ``provider = "<name>"`` means. A local preset needs no key.
PRESETS: Dict[str, Preset] = {
    "ollama": Preset(OPENAI_COMPATIBLE, "http://localhost:11434/v1", None, label="Ollama (local)"),
    "lmstudio": Preset(
        OPENAI_COMPATIBLE, "http://localhost:1234/v1", None, label="LM Studio (local)"
    ),
    "openai": Preset(
        OPENAI_COMPATIBLE, "https://api.openai.com/v1", "OPENAI_API_KEY", label="OpenAI"
    ),
    "anthropic": Preset(
        ANTHROPIC, None, "ANTHROPIC_API_KEY", model="claude-opus-5-5", label="Anthropic (Claude)"
    ),
    # Anything else that serves /v1/chat/completions: vLLM, llama.cpp, a gateway.
    OPENAI_COMPATIBLE: Preset(OPENAI_COMPATIBLE, None, None, label="OpenAI-compatible endpoint"),
}

EFFORTS = ("low", "medium", "high", "xhigh", "max")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def ducta_home() -> Path:
    return Path(os.environ.get("DUCTA_HOME") or Path.home() / ".ducta").expanduser()


def config_path() -> Path:
    return ducta_home() / "ai.toml"


@dataclass
class AIConfig:
    provider: str
    model: Optional[str] = None
    base_url: Optional[str] = None
    #: The *name* of the variable holding the key, e.g. ``ANTHROPIC_API_KEY``.
    api_key_env: Optional[str] = None
    #: Anthropic only: ``output_config.effort``. Unset: ``high`` on the models
    #: that take it (see :mod:`ducta.ai.providers`).
    effort: Optional[str] = None
    timeout_seconds: float = 300.0
    max_attempts: int = 3
    #: Ollama only: the context window to ask for. Its default (2–4k tokens)
    #: silently cuts a project's context short.
    context_tokens: int = 16384
    #: Keys the file had that this version does not know — kept on save.
    extra: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def preset(self) -> Preset:
        return PRESETS[self.provider]

    @property
    def kind(self) -> str:
        return self.preset.kind

    @property
    def label(self) -> str:
        return self.preset.label

    @property
    def is_local(self) -> bool:
        """True when requests stay on this machine (or its Docker host)."""
        if self.kind != OPENAI_COMPATIBLE or not self.base_url:
            return False
        return (urlparse(self.base_url).hostname or "") in _LOCAL_HOSTS

    @property
    def custom_endpoint(self) -> bool:
        """True when requests go somewhere other than the preset's own endpoint."""
        return bool(self.base_url) and self.base_url != (self.preset.base_url or "").rstrip("/")

    @property
    def endpoint(self) -> str:
        """Where requests go, for messages: never includes a key."""
        if self.kind == ANTHROPIC:
            return self.base_url or "https://api.anthropic.com"
        return self.base_url or "?"

    def validate(self) -> "AIConfig":
        if self.provider not in PRESETS:
            raise AIConfigError(
                f"Unknown AI provider '{self.provider}'. "
                f"Choose one of: {', '.join(PRESETS)} (ducta ai setup --provider ...)"
            )
        if self.kind == OPENAI_COMPATIBLE and not self.base_url:
            raise AIConfigError(
                f"Provider '{self.provider}' needs a base URL "
                "(ducta ai setup --provider openai_compatible --base-url http://host:port/v1)"
            )
        if self.base_url:
            parsed = urlparse(self.base_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise AIConfigError(f"'{self.base_url}' is not an http(s) URL")
        if self.effort is not None and self.effort not in EFFORTS:
            raise AIConfigError(f"Unknown effort '{self.effort}' (one of: {', '.join(EFFORTS)})")
        if self.max_attempts < 1:
            raise AIConfigError("max_attempts must be at least 1")
        return self

    def require_model(self) -> str:
        if not self.model:
            raise AIConfigError(
                f"No model is set for {self.label}. Run `ducta ai doctor` to list the "
                "models it serves, then `ducta ai setup --provider "
                f"{self.provider} --model <name>`."
            )
        return self.model

    def to_toml_dict(self) -> Dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if k != "extra" and v is not None}
        # A preset's own value is not written: changing the preset changes it.
        preset = self.preset
        for key, default in (
            ("base_url", preset.base_url),
            ("api_key_env", preset.api_key_env),
            ("timeout_seconds", 300.0),
            ("max_attempts", 3),
            ("context_tokens", 16384),
        ):
            if key in data and data[key] == default:
                del data[key]
        return {**self.extra, **data}


def _from_mapping(data: Dict[str, Any]) -> AIConfig:
    provider = str(data.get("provider") or "")
    if provider not in PRESETS:
        AIConfig(provider=provider).validate()  # raises with the list of choices
    preset = PRESETS[provider]
    known = {f for f in AIConfig.__dataclass_fields__ if f != "extra"}
    try:
        config = AIConfig(
            provider=provider,
            model=data.get("model") or preset.model,
            base_url=(data.get("base_url") or preset.base_url),
            api_key_env=data.get("api_key_env") or preset.api_key_env,
            effort=data.get("effort"),
            timeout_seconds=float(data.get("timeout_seconds", 300.0)),
            max_attempts=int(data.get("max_attempts", 3)),
            context_tokens=int(data.get("context_tokens", 16384)),
            extra={k: v for k, v in data.items() if k not in known},
        )
    except (TypeError, ValueError) as e:
        raise AIConfigError(f"{config_path()}: {e}") from e
    if config.base_url:
        config.base_url = config.base_url.rstrip("/")
    return config.validate()


def _read_file(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise AIConfigError(f"Cannot read {path}: {e}") from e


def load_config(
    path: Optional[Path] = None, *, env: Optional[Mapping[str, str]] = None
) -> AIConfig:
    """The configured provider, with ``DUCTA_AI_*`` overrides applied."""
    env = os.environ if env is None else env
    path = path or config_path()
    data = _read_file(path)
    if env.get("DUCTA_AI_PROVIDER"):
        if env["DUCTA_AI_PROVIDER"] != data.get("provider"):
            # Another provider: the file's model and URL belong to the old one.
            data = {"provider": env["DUCTA_AI_PROVIDER"]}
    if env.get("DUCTA_AI_MODEL"):
        data["model"] = env["DUCTA_AI_MODEL"]
    if env.get("DUCTA_AI_BASE_URL"):
        data["base_url"] = env["DUCTA_AI_BASE_URL"]
    if not data.get("provider"):
        raise AIConfigError(
            "No AI provider is configured. For a local model: "
            "`ducta ai setup --provider ollama`; with an API key: "
            "`ducta ai setup --provider anthropic` (or openai)."
        )
    return _from_mapping(data)


def save_config(config: AIConfig, path: Optional[Path] = None) -> Path:
    import tomli_w

    config.validate()
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(config.to_toml_dict()), encoding="utf-8")
    return path


#: What belongs to one provider: switching provider drops these from the file.
_PER_PROVIDER = ("model", "base_url", "api_key_env", "effort")
#: Field names a caller may update (``extra`` is never set through here).
_FIELDS = (*_PER_PROVIDER, "timeout_seconds", "max_attempts", "context_tokens")


def update_config(
    provider: str, changes: Mapping[str, Any], path: Optional[Path] = None
) -> AIConfig:
    """The file's config with *changes* over it — what is not in *changes* is kept.

    A key in *changes* set to ``None`` goes back to the preset's value. Switching
    provider drops the old provider's model, URL, key variable and effort, and
    keeps the rest (timeouts, attempts, context window, unknown keys).
    """
    unknown = set(changes) - set(_FIELDS)
    if unknown:
        raise AIConfigError(f"Unknown AI setting(s): {', '.join(sorted(unknown))}")
    data = _read_file(path or config_path())
    if data.get("provider") != provider:
        data = {k: v for k, v in data.items() if k not in _PER_PROVIDER}
    data["provider"] = provider
    for key, value in changes.items():
        if value is None or value == "":
            data.pop(key, None)
        else:
            data[key] = value
    return _from_mapping(data)


def build_config(
    provider: str,
    *,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key_env: Optional[str] = None,
    effort: Optional[str] = None,
) -> AIConfig:
    """A config for ``ducta ai setup``: the preset, with what was given over it."""
    data: Dict[str, Any] = {"provider": provider}
    for key, value in (
        ("model", model),
        ("base_url", base_url),
        ("api_key_env", api_key_env),
        ("effort", effort),
    ):
        if value:
            data[key] = value
    return _from_mapping(data)
