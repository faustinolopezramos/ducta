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

Adapters for the hosted git forges a workspace can be backed by.

Named ``vcs`` rather than ``repository`` because ``ducta.api.repositories``
already exists and means something entirely different — the data-access layer
over configs, nodes, pipelines and projects. Two packages one plural apart, with
no overlap in purpose, is a typo that imports cleanly and fails somewhere else.
"""

from ducta.api.vcs.aws import AWSAdapter
from ducta.api.vcs.azure import AzureAdapter
from ducta.api.vcs.base import RepositoryAdapter
from ducta.api.vcs.github import GitHubAdapter
from ducta.api.vcs.local import LocalAdapter

__all__ = [
    "RepositoryAdapter",
    "LocalAdapter",
    "GitHubAdapter",
    "AzureAdapter",
    "AWSAdapter",
]
