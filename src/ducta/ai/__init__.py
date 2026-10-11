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

AI-assisted pipeline building.

A model — local (Ollama, LM Studio, vLLM, llama.cpp) or behind an API key
(Anthropic, OpenAI or any OpenAI-compatible endpoint) — drafts a format-2
pipeline from a request in plain language. The draft is checked by the same
validation the UI runs on unsaved edits; its problems go back to the model
until it passes or the attempts run out. Nothing is written until the user
accepts the draft, and nothing is ever run or committed.

The provider is a per-machine choice, so it lives in ``~/.ducta/ai.toml`` (see
:mod:`ducta.ai.config`), never in the project; an API key lives in an
environment variable or the OS keychain (:mod:`ducta.ai.secrets`).
"""

from ducta.ai.config import AIConfig, load_config
from ducta.ai.errors import AIError

__all__ = ["AIConfig", "AIError", "load_config"]
