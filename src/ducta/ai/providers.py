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

The two wire protocols behind every provider.

* **OpenAI-compatible** ``/chat/completions`` over ``httpx`` — Ollama, LM
  Studio, vLLM, llama.cpp's server, OpenAI itself and most gateways differ only
  in their base URL.
* **Anthropic** through the official ``anthropic`` SDK.

Both turn transport failures into :class:`AIError` messages that say what to
check, and neither ever logs or returns the key.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Protocol

from ducta.ai.config import ANTHROPIC, AIConfig
from ducta.ai.errors import AIEnvironmentError, AIError
from ducta.ai.secrets import require_key


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class Completion:
    text: str
    model: str
    #: The output hit the token limit and is cut short.
    truncated: bool = False
    usage: Dict[str, int] = field(default_factory=dict)


class LLMProvider(Protocol):
    config: AIConfig

    def complete(self, system: str, messages: List[ChatMessage]) -> Completion: ...

    def list_models(self) -> List[str]: ...


def _install_hint(package: str) -> AIError:
    return AIEnvironmentError(
        f"The '{package}' package is not installed. Install the AI extra: "
        "pip install 'ducta[api,ai]'"
    )


class _TemperatureRejected(Exception):
    """HTTP 400 about ``temperature``: retried once without it."""


def _detail(response: Any) -> str:
    """An error answer's message, without echoing whatever page a wrong URL returns."""
    try:
        data = response.json()
    except ValueError:
        return "(not a JSON error; check the base URL)"
    error = data.get("error") if isinstance(data, dict) else None
    message = error.get("message") if isinstance(error, dict) else error
    return str(message or data)[:300]


class OpenAICompatibleProvider:
    """``POST {base_url}/chat/completions``; a key, when there is one, as a Bearer token."""

    #: Low but not zero: valid YAML matters more than variety.
    temperature = 0.1

    def __init__(self, config: AIConfig, api_key: Optional[str] = None, client: Any = None):
        self.config = config
        self._key = api_key
        self._client = client
        #: Reasoning models (OpenAI's o-series, GPT-5) take only the default
        #: temperature; learnt from the first 400 that says so.
        self._send_temperature = True

    @contextmanager
    def _http(self) -> Iterator[Any]:
        """The injected client, or one opened for this request and closed after it.

        A draft makes a handful of requests minutes apart, so there is no pool
        worth keeping — and a server that builds a provider per request would
        otherwise leak one per call.
        """
        if self._client is not None:
            yield self._client
            return
        import httpx

        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        with httpx.Client(
            base_url=self.config.base_url or "",
            headers=headers,
            timeout=self.config.timeout_seconds,
        ) as client:
            yield client

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        try:
            import httpx
        except ImportError as e:
            raise _install_hint("httpx") from e

        where = self.config.endpoint
        try:
            with self._http() as client:
                response = client.request(method, path, **kwargs)
        except httpx.ConnectError as e:
            hint = (
                " Is the local server running (e.g. `ollama serve`)?"
                if self.config.is_local
                else ""
            )
            raise AIError(f"Cannot reach {where}.{hint}", cause=e) from e
        except httpx.TimeoutException as e:
            raise AIError(
                f"{where} did not answer within {self.config.timeout_seconds:.0f}s "
                "(raise timeout_seconds in ~/.ducta/ai.toml for a slow local model)",
                cause=e,
            ) from e
        if response.status_code in (401, 403):
            raise AIError(f"{where} rejected the API key (HTTP {response.status_code})")
        if response.status_code == 404 and path.endswith(("completions", "/api/chat")):
            raise AIError(
                f"{where} does not serve model '{self.config.model}' (HTTP 404). "
                "`ducta ai doctor` lists the models it has."
            )
        sent_temperature = "temperature" in (kwargs.get("json") or {})
        if (
            response.status_code == 400
            and sent_temperature
            and "temperature" in response.text.lower()
        ):
            raise _TemperatureRejected()
        if response.status_code >= 400:
            raise AIError(f"{where} answered HTTP {response.status_code}: {_detail(response)}")
        try:
            data: Dict[str, Any] = response.json()
            return data
        except ValueError as e:
            raise AIError(f"{where} did not answer with JSON", cause=e) from e

    def complete(self, system: str, messages: List[ChatMessage]) -> Completion:
        model = self.config.require_model()
        body: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        }
        if self._send_temperature:
            body["temperature"] = self.temperature
        try:
            data = self._request("POST", "/chat/completions", json=body)
        except _TemperatureRejected:
            self._send_temperature = False
            del body["temperature"]
            data = self._request("POST", "/chat/completions", json=body)
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise AIError(
                f"Unexpected answer from {self.config.endpoint}: {str(data)[:300]}"
            ) from e
        usage = data.get("usage") or {}
        return Completion(
            text=text,
            model=data.get("model") or model,
            truncated=choice.get("finish_reason") == "length",
            usage={
                "input_tokens": int(usage.get("prompt_tokens") or 0),
                "output_tokens": int(usage.get("completion_tokens") or 0),
            },
        )

    def list_models(self) -> List[str]:
        data = self._request("GET", "/models")
        return sorted(str(m.get("id")) for m in data.get("data") or [] if m.get("id"))


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama: listed through ``/v1``, chatted with through its native ``/api/chat``.

    The OpenAI-compatible endpoint cannot set the context window, and Ollama's
    default (2–4k tokens) silently drops most of a project's context; the native
    one takes ``num_ctx``.
    """

    def complete(self, system: str, messages: List[ChatMessage]) -> Completion:
        model = self.config.require_model()
        native = (self.config.base_url or "").rstrip("/")
        if native.endswith("/v1"):
            native = native[: -len("/v1")]
        body = {
            "model": model,
            "stream": False,
            "options": {"temperature": self.temperature, "num_ctx": self.config.context_tokens},
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        }
        data = self._request("POST", f"{native}/api/chat", json=body)
        try:
            text = data["message"]["content"] or ""
        except (KeyError, TypeError) as e:
            raise AIError(
                f"Unexpected answer from {self.config.endpoint}: {str(data)[:300]}"
            ) from e
        prompt = int(data.get("prompt_eval_count") or 0)
        if prompt >= self.config.context_tokens:
            raise AIError(
                f"The request ({prompt} tokens) fills Ollama's context window "
                f"({self.config.context_tokens}); raise context_tokens in ~/.ducta/ai.toml"
            )
        return Completion(
            text=text,
            model=data.get("model") or model,
            truncated=data.get("done_reason") == "length",
            usage={"input_tokens": prompt, "output_tokens": int(data.get("eval_count") or 0)},
        )


#: Models that take ``fallbacks: "default"`` (re-run a declined request on a
#: model the API picks) on the first-party API.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


#: Models that take ``output_config.effort`` (older ones reject it).
_EFFORT_MODELS = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-5-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
)
#: Writing project files is coding work: below ``high``, drafts fail validation
#: more often (and Opus 5.5 defaults to ``medium``).
_DEFAULT_EFFORT = "high"


class AnthropicProvider:
    """Claude through the ``anthropic`` SDK (Messages API).

    The system prompt and the first message (the project's context) are marked
    for prompt caching: each validation attempt and each revision re-sends them,
    and cached input costs a tenth.
    """

    max_tokens = 16000
    #: The SDK retries 429/5xx/connection errors; a timed-out request is
    #: retried too, so each retry can add a whole ``timeout_seconds``.
    max_retries = 1

    def __init__(self, config: AIConfig, api_key: Optional[str] = None, client: Any = None):
        self.config = config
        self._key = api_key
        self._client = client

    def _sdk(self):
        try:
            import anthropic
        except ImportError as e:
            raise _install_hint("anthropic") from e
        return anthropic

    @contextmanager
    def _anthropic(self) -> Iterator[Any]:
        """The injected client, or one opened for this call and closed after it."""
        if self._client is not None:
            yield self._client
            return
        anthropic = self._sdk()
        kwargs: Dict[str, Any] = {
            "api_key": self._key,
            "timeout": self.config.timeout_seconds,
            "max_retries": self.max_retries,
        }
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        with anthropic.Anthropic(**kwargs) as client:
            yield client

    def _call(self, fn, **kwargs: Any):
        anthropic = self._sdk()
        try:
            return fn(**kwargs)
        except anthropic.AuthenticationError as e:
            raise AIError("Anthropic rejected the API key (`ducta ai login` to replace it)") from e
        except anthropic.NotFoundError as e:
            raise AIError(
                f"Anthropic has no model '{self.config.model}'. `ducta ai doctor` lists them."
            ) from e
        except anthropic.RateLimitError as e:
            raise AIError("Anthropic rate limit reached; try again in a minute", cause=e) from e
        except anthropic.APIStatusError as e:
            raise AIError(f"Anthropic answered HTTP {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AIError(f"Cannot reach {self.config.endpoint}", cause=e) from e

    def complete(self, system: str, messages: List[ChatMessage]) -> Completion:
        model = self.config.require_model()
        cache = {"type": "ephemeral"}
        wire: List[Dict[str, Any]] = [{"role": m.role, "content": m.content} for m in messages]
        if wire:
            # The context is the long, stable part: cache up to the end of it.
            wire[0] = {
                "role": wire[0]["role"],
                "content": [{"type": "text", "text": wire[0]["content"], "cache_control": cache}],
            }
        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": cache}],
            "messages": wire,
        }
        effort = self.config.effort or (
            _DEFAULT_EFFORT if model.startswith(_EFFORT_MODELS) else None
        )
        if effort:
            kwargs["output_config"] = {"effort": effort}
        with self._anthropic() as client:
            if model in _FALLBACK_MODELS and not self.config.base_url:
                response = self._call(
                    client.beta.messages.create,
                    betas=[_FALLBACK_BETA],
                    fallbacks="default",
                    **kwargs,
                )
            else:
                response = self._call(client.messages.create, **kwargs)

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            why = getattr(details, "explanation", None) or "no reason given"
            raise AIError(f"The model declined the request ({why})")
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        usage = getattr(response, "usage", None)
        return Completion(
            text=text,
            model=getattr(response, "model", model),
            truncated=response.stop_reason == "max_tokens",
            usage={
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
                "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                "cache_creation_input_tokens": int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
            },
        )

    def list_models(self) -> List[str]:
        with self._anthropic() as client:
            # Iterating fetches the next pages, so it belongs inside the error mapping.
            ids: List[str] = self._call(lambda: [m.id for m in client.models.list()])
            return ids


def make_provider(config: AIConfig) -> LLMProvider:
    """The provider *config* names, with its key resolved (raises if one is missing)."""
    key = require_key(config)
    if config.kind == ANTHROPIC:
        return AnthropicProvider(config, key)
    if config.provider == "ollama":
        return OllamaProvider(config, key)
    return OpenAICompatibleProvider(config, key)
