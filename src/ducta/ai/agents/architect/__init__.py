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

Ducta Architect — designs and builds pipelines.

1. :func:`design.design` — the model writes a blueprint; Ducta checks it
   (:func:`design.check`, no model) and validates it rendered with stubs.
2. :func:`build.build` — Ducta writes the YAML; the model writes each
   pipeline's module; one draft comes out, applied like any other.
3. :func:`verify.verify` — the result validated, and run in dev on request.
"""
