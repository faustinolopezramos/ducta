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

Quality checks subpackage. Auto-discovers and registers checks.
"""

from ducta.check.core import QUALITY_CHECKS_REGISTRY, register_check

from .business import BusinessRulesCheck
from .cross_table import CrossTableReferentialIntegrityCheck, DatasetCompletenessCheck
from .distribution import DriftDetectionCheck, StatisticalCheck

# Import all modules to trigger auto-registration
from .structural import (
    DuplicateCheck,
    EmptyDatasetCheck,
    NullRateCheck,
    RangeCheck,
    ReferentialIntegrityCheck,
    RowCountCheck,
    SchemaCheck,
    SchemaDriftCheck,
)
from .temporal import AnomalyDetectionCheck, FreshnessCheck, IncrementalVolumeCheck

__all__ = [
    "QUALITY_CHECKS_REGISTRY",
    "register_check",
    # Structural (8)
    "EmptyDatasetCheck",
    "NullRateCheck",
    "SchemaCheck",
    "SchemaDriftCheck",
    "RowCountCheck",
    "DuplicateCheck",
    "RangeCheck",
    "ReferentialIntegrityCheck",
    # Temporal (3)
    "AnomalyDetectionCheck",
    "IncrementalVolumeCheck",
    "FreshnessCheck",
    # Distribution (2)
    "DriftDetectionCheck",
    "StatisticalCheck",
    # Cross-table (2)
    "CrossTableReferentialIntegrityCheck",
    "DatasetCompletenessCheck",
    # Business rules (1)
    "BusinessRulesCheck",
]
