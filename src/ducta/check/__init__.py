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
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------
from ducta.check.advisor import ThresholdAdvisor

# ---------------------------------------------------------------------------
# Quality checks (auto-registered)
# ---------------------------------------------------------------------------
from ducta.check.checks import (
    AnomalyDetectionCheck,
    BusinessRulesCheck,
    CrossTableReferentialIntegrityCheck,
    DatasetCompletenessCheck,
    DriftDetectionCheck,
    DuplicateCheck,
    EmptyDatasetCheck,
    FreshnessCheck,
    IncrementalVolumeCheck,
    NullRateCheck,
    RangeCheck,
    ReferentialIntegrityCheck,
    RowCountCheck,
    SchemaCheck,
    SchemaDriftCheck,
    StatisticalCheck,
)

# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------
from ducta.check.core import (
    QUALITY_CHECKS_REGISTRY,
    BaseQualityCheck,
    CheckResult,
    CheckSeverity,
    DFAdapter,
    QualityCheckError,
    QualityChecksFailed,
    QualityConfigError,
    QualityEngineError,
    QualityError,
    QualityGateBlocked,
    QualityReport,
    load_quality_extensions,
    register_check,
)

# ---------------------------------------------------------------------------
# Engine / runners
# ---------------------------------------------------------------------------
from ducta.check.engine import (
    DQReporter,
    DQRunner,
    QualityReporter,
    SanityCheckReport,
    SanityCheckRunner,
    SanityPhaseRunner,
    SanityReporter,
    ValidationPhaseRunner,
)

# ---------------------------------------------------------------------------
# Gate evaluator
# ---------------------------------------------------------------------------
from ducta.check.gate import GateAction, GateBehavior, GateResult, QualityGateEvaluator

# ---------------------------------------------------------------------------
# Output management
# ---------------------------------------------------------------------------
from ducta.check.output_manager import QualityOutputConfig, QualityOutputManager, QualityOutputPath

# ---------------------------------------------------------------------------
# Quality profiles
# ---------------------------------------------------------------------------
from ducta.check.profiles import (
    QualityProfile,
    apply_auto_tune,
    load_profiles,
    resolve_checks_config,
)

# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
from ducta.check.serialization import GateResultSerializer, QualityReportSerializer

# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
from ducta.check.service import QualityService

# ---------------------------------------------------------------------------
# Storage backends
# ---------------------------------------------------------------------------
from ducta.check.storage import ContextAwareStorageBackend, FileStorageBackend, StorageBackend

__all__ = [
    # Core types
    "QUALITY_CHECKS_REGISTRY",
    "BaseQualityCheck",
    "CheckResult",
    "CheckSeverity",
    "DFAdapter",
    "QualityCheckError",
    "QualityChecksFailed",
    "QualityConfigError",
    "QualityEngineError",
    "QualityError",
    "QualityGateBlocked",
    "QualityReport",
    "load_quality_extensions",
    "register_check",
    # Engine / runners
    "DQReporter",
    "DQRunner",
    "QualityReporter",
    "SanityCheckReport",
    "SanityCheckRunner",
    "SanityPhaseRunner",
    "SanityReporter",
    "ValidationPhaseRunner",
    # Gate
    "GateAction",
    "GateBehavior",
    "GateResult",
    "QualityGateEvaluator",
    # Profiles
    "QualityProfile",
    "apply_auto_tune",
    "load_profiles",
    "resolve_checks_config",
    # Service
    "QualityService",
    # Output
    "QualityOutputConfig",
    "QualityOutputManager",
    "QualityOutputPath",
    # Serialization
    "GateResultSerializer",
    "QualityReportSerializer",
    # Storage
    "ContextAwareStorageBackend",
    "FileStorageBackend",
    "StorageBackend",
    # Advisor
    "ThresholdAdvisor",
    # Checks
    "AnomalyDetectionCheck",
    "BusinessRulesCheck",
    "CrossTableReferentialIntegrityCheck",
    "DatasetCompletenessCheck",
    "DriftDetectionCheck",
    "DuplicateCheck",
    "EmptyDatasetCheck",
    "FreshnessCheck",
    "IncrementalVolumeCheck",
    "NullRateCheck",
    "RangeCheck",
    "ReferentialIntegrityCheck",
    "RowCountCheck",
    "SchemaCheck",
    "SchemaDriftCheck",
    "StatisticalCheck",
]
