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

import math
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from ducta.mlrun.exceptions import (
    ErrorCode,
    InvalidMetricError,
    InvalidParameterError,
    MLOpsException,
)

# Valid characters for model/experiment names
VALID_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
MIN_NAME_LENGTH = 1
MAX_NAME_LENGTH = 255


class ValidationError(MLOpsException, ValueError):
    """Base validation error.
    """

    error_code = ErrorCode.VALIDATION_FAILED

    def __init__(self, message: str, **kwargs):
        super().__init__(message=message, **kwargs)


class PathValidator:
    """Validator for file paths"""

    @staticmethod
    def validate_path(path: str, base_path: Optional[Path] = None) -> Path:
        """
        Validate and sanitize a path with improved security.
        C5: Better path validation prevents traversal attacks.
        """
        if not path or not isinstance(path, str):
            raise ValidationError("Path must be non-empty string")

        path_obj = Path(path)
        if path_obj.is_absolute():
            raise ValidationError(f"Absolute paths not allowed: {path}")

        if ".." in path or "~" in path:
            raise ValidationError(f"Directory traversal not allowed: {path}")

        if base_path:
            # Ensure base_path is a Path object and resolve it to absolute
            if isinstance(base_path, str):
                base_resolved = Path(base_path).resolve()
            else:
                base_resolved = base_path.resolve()

            # Resolve path relative to base, then check it's still within base
            full_path = (base_resolved / path).resolve()

            # Verify resolved path is within base directory
            try:
                full_path.relative_to(base_resolved)
            except ValueError as e:
                raise ValidationError(
                    f"Path '{path}' resolves to '{full_path}' which is outside "
                    f"base directory '{base_resolved}'. Original error: {e}"
                )

            return full_path

        return path_obj

    @staticmethod
    def validate_file_exists(path: Path) -> Path:
        """Validate that file/directory exists"""
        if not path.exists():
            raise ValidationError(f"Path does not exist: {path}")

        return path

    @staticmethod
    def validate_is_file_or_dir(path: Path) -> Path:
        """Validate that path is file or directory"""
        if not path.is_file() and not path.is_dir():
            raise ValidationError(f"Path must be file or directory: {path}")

        return path


class NameValidator:
    """Validator for model/experiment names"""

    @staticmethod
    def validate_name(name: str, entity_type: str = "entity") -> str:
        """
        Validate a name (model, experiment, run, etc).
        """
        if not name or not isinstance(name, str):
            raise ValidationError(
                f"{entity_type} name must be non-empty string, got {type(name).__name__}"
            )

        if len(name) < MIN_NAME_LENGTH or len(name) > MAX_NAME_LENGTH:
            raise ValidationError(
                f"{entity_type} name must be {MIN_NAME_LENGTH}-{MAX_NAME_LENGTH} characters, "
                f"got {len(name)}"
            )

        if not VALID_NAME_PATTERN.match(name):
            raise ValidationError(
                f"{entity_type} name '{name}' contains invalid characters. "
                f"Only alphanumeric, underscore, dash, and dot allowed."
            )

        if not name[0].isalnum():
            raise ValidationError(f"{entity_type} name '{name}' must start with letter or number")

        return name


class MetricValidator:
    """Validator for metric values"""

    @staticmethod
    def validate_metric_value(key: str, value: Any) -> float:
        """
        Validate a metric value.
        """
        if not isinstance(value, (int, float)):
            raise InvalidMetricError(
                key, value, f"Metrics must be numeric (int or float), got {type(value).__name__}"
            )

        try:
            if math.isnan(value):
                raise InvalidMetricError(key, value, "Metrics cannot be NaN")
        except (TypeError, ValueError):
            pass

        # warn but allow infinity
        try:
            if math.isinf(value):
                logger.warning(
                    f"Metric '{key}' has infinite value. This may cause issues with visualization."
                )
        except (TypeError, ValueError):
            pass

        return float(value)

    @staticmethod
    def validate_metrics(
        metrics: Optional[Dict[str, Any]], max_items: int = 1000
    ) -> Optional[Dict[str, float]]:
        """Validate a whole metrics dict, value by value.
        """
        if metrics is None:
            return None

        if not isinstance(metrics, dict):
            raise ValidationError(f"Metrics must be dict or None, got {type(metrics).__name__}")

        if len(metrics) > max_items:
            raise ValidationError(f"Too many metrics ({len(metrics)} > {max_items})")

        validated: Dict[str, float] = {}
        for key, value in metrics.items():
            if not isinstance(key, str) or not key.strip():
                raise ValidationError(f"Metric name must be a non-empty string, got {key!r}")
            validated[key] = MetricValidator.validate_metric_value(key, value)
        return validated

    @staticmethod
    def validate_step(step: Any) -> int:
        """Validate step value"""
        if not isinstance(step, int):
            raise ValidationError(f"Step must be integer, got {type(step).__name__}")

        if step < 0:
            raise ValidationError(f"Step must be non-negative, got {step}")

        return step


class ParameterValidator:
    """Validator for hyperparameters"""

    SUPPORTED_TYPES = {str, int, float, bool, type(None)}

    @staticmethod
    def _validate_key(key: Any) -> str:
        """Helper to validate a parameter key"""
        if not isinstance(key, str):
            raise InvalidParameterError(
                key, f"Parameter name must be string, got {type(key).__name__}"
            )
        if not key.strip():
            raise InvalidParameterError(key, "Parameter name cannot be empty")
        return key

    @staticmethod
    def _validate_value(key: str, value: Any) -> Any:
        """Helper to validate a parameter value"""
        if type(value) not in ParameterValidator.SUPPORTED_TYPES:
            raise InvalidParameterError(
                key,
                f"Parameter value type {type(value).__name__} not supported. "
                f"Supported: {ParameterValidator.SUPPORTED_TYPES}",
            )
        if isinstance(value, float):
            if math.isnan(value):
                raise InvalidParameterError(key, "Parameter value cannot be NaN")
            if math.isinf(value):
                logger.warning(f"Parameter '{key}' has infinite value")
        return value

    @staticmethod
    def validate_parameters(
        parameters: Optional[Dict[str, Any]], max_items: int = 1000
    ) -> Optional[Dict[str, Any]]:
        """
        Validate hyperparameters dict.
        """
        if parameters is None:
            return None

        if not isinstance(parameters, dict):
            raise InvalidParameterError(
                "parameters", f"Parameters must be dict or None, got {type(parameters).__name__}"
            )

        if len(parameters) > max_items:
            raise InvalidParameterError(
                "parameters", f"Too many parameters ({len(parameters)} > {max_items})"
            )

        for key, value in parameters.items():
            ParameterValidator._validate_key(key)
            ParameterValidator._validate_value(key, value)

        return parameters


class MetadataValidator:
    """Validator for metadata dicts (tags, etc)"""

    @staticmethod
    def validate_tags(
        tags: Optional[Dict[str, str]], max_items: int = 100
    ) -> Optional[Dict[str, str]]:
        """
        Validate tags dict.
        """
        if tags is None:
            return None

        if not isinstance(tags, dict):
            raise ValidationError(f"Tags must be dict or None, got {type(tags).__name__}")

        if len(tags) > max_items:
            raise ValidationError(f"Too many tags ({len(tags)} > {max_items})")

        # Validate each tag
        for key, value in tags.items():
            if not isinstance(key, str):
                raise ValidationError(f"Tag key must be string, got {type(key).__name__}")

            if not isinstance(value, str):
                raise ValidationError(f"Tag value must be string, got {type(value).__name__}")

        return tags

    @staticmethod
    def validate_description(description: Optional[str]) -> Optional[str]:
        """Validate description"""
        if description is None:
            return None

        if not isinstance(description, str):
            raise ValidationError(f"Description must be string, got {type(description).__name__}")

        if len(description) > 10000:
            raise ValidationError(f"Description too long ({len(description)} > 10000)")

        return description


class FrameworkValidator:
    """Validator for ML framework names"""

    SUPPORTED_FRAMEWORKS = {
        "scikit-learn",
        "sklearn",
        "xgboost",
        "lightgbm",
        "catboost",
        "pytorch",
        "tensorflow",
        "keras",
        "jax",
        "onnx",
        "mxnet",
        "spark-mllib",
        "custom",
    }
    _frameworks_lock = threading.Lock()

    @staticmethod
    def validate_framework(framework: str, allow_custom: bool = True) -> str:
        """
        Validate framework name.
        """
        if not isinstance(framework, str):
            raise ValidationError(f"Framework must be string, got {type(framework).__name__}")

        framework_lower = framework.lower().strip()

        # Allow custom or supported
        if framework_lower == "custom":
            if not allow_custom:
                raise ValidationError("'custom' framework not allowed in this context")
            return "custom"

        if framework_lower not in FrameworkValidator.SUPPORTED_FRAMEWORKS:
            raise ValidationError(
                f"Unsupported framework: {framework}. "
                f"Supported: {FrameworkValidator.SUPPORTED_FRAMEWORKS}"
            )

        return framework_lower

    @staticmethod
    def add_supported_framework(framework: str):
        """Add a new supported framework"""
        with FrameworkValidator._frameworks_lock:
            FrameworkValidator.SUPPORTED_FRAMEWORKS.add(framework.lower())


# Convenience functions
def validate_model_name(name: str) -> str:
    """Validate model name"""
    return NameValidator.validate_name(name, "Model")


def validate_experiment_name(name: str) -> str:
    """Validate experiment name"""
    return NameValidator.validate_name(name, "Experiment")


def validate_run_name(name: str) -> str:
    """Validate run name"""
    return NameValidator.validate_name(name, "Run")


def validate_framework(framework: str, allow_custom: bool = True) -> str:
    """Validate framework name"""
    return FrameworkValidator.validate_framework(framework, allow_custom)


def validate_artifact_type(artifact_type: str) -> str:
    """Validate artifact type"""
    return ArtifactValidator.validate_artifact_type(artifact_type)


def validate_metric_value(key: str, value: Any) -> float:
    """Validate metric value"""
    return MetricValidator.validate_metric_value(key, value)


def validate_metrics(metrics: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Validate a metrics dict (every value numeric and not NaN)"""
    return MetricValidator.validate_metrics(metrics)


def validate_parameters(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate parameters"""
    return ParameterValidator.validate_parameters(params)


def validate_tags(tags: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Validate tags"""
    return MetadataValidator.validate_tags(tags)


def validate_description(description: Optional[str]) -> Optional[str]:
    """Validate description"""
    return MetadataValidator.validate_description(description)


class ArtifactValidator:
    """Validator for model artifacts — validates type strings and ensures artifacts can be loaded."""

    @staticmethod
    def validate_artifact_type(artifact_type: str) -> str:
        """
        Validate artifact type string.
        """
        if not artifact_type or not isinstance(artifact_type, str):
            raise ValidationError(
                f"Artifact type must be non-empty string, got {type(artifact_type).__name__}"
            )

        artifact_type = artifact_type.lower().strip()

        if not re.match(r"^[a-z0-9_\-]+$", artifact_type):
            raise ValidationError(
                f"Artifact type '{artifact_type}' contains invalid characters. "
                f"Only lowercase alphanumeric, underscore, and dash allowed."
            )

        return artifact_type

    SUPPORTED_FRAMEWORKS = {
        "sklearn": ["pkl", "joblib"],
        "xgboost": ["pkl", "json", "ubj"],
        "lightgbm": ["pkl", "txt"],
        "pytorch": ["pt", "pth"],
        "tensorflow": ["h5", "pb", "keras"],
        "onnx": ["onnx", "pb"],
        "pickle": ["pkl"],
        "joblib": ["joblib"],
        "custom": ["pkl", "bin"],
    }

    # Frameworks whose loader is pickle/joblib-based, i.e. "validating" them
    # means executing arbitrary code embedded in the artifact. These are only
    # actually deserialized when the caller passes trust_artifact_source=True
    # — the same trust boundary PickleReader.allow_untrusted_pickle enforces
    # in ducta.gate.readers.
    _PICKLE_BASED_FRAMEWORKS = {"sklearn", "scikit-learn", "pickle", "joblib", "custom"}

    @staticmethod
    def validate_artifact(
        artifact_path: str,
        framework: str,
        trust_artifact_source: bool = False,
    ) -> None:
        """
        Validate that artifact exists and, when the framework's loader is
        pickle-based, only actually deserialize it if trust_artifact_source
        is True.
        """
        artifact_path_obj = Path(artifact_path)

        if not artifact_path_obj.exists():
            raise ValidationError(f"Artifact not found at {artifact_path}")

        if not artifact_path_obj.is_file() and not artifact_path_obj.is_dir():
            raise ValidationError(f"Artifact path must be a file or directory: {artifact_path}")

        size_bytes = artifact_path_obj.stat().st_size if artifact_path_obj.is_file() else 0
        if size_bytes > 1_000_000_000:  # 1GB
            logger.warning(
                f"Artifact is very large: {size_bytes / 1e9:.2f}GB. "
                f"Consider using external storage."
            )

        # 3. Try to load based on framework
        try:
            ArtifactValidator._validate_loadable(
                artifact_path_obj, framework, trust_artifact_source
            )
        except Exception as e:
            raise ValidationError(f"Cannot load artifact with framework '{framework}': {e}")

    @staticmethod
    def _lightweight_validate(artifact_path: Path, framework: str) -> None:
        """
        Non-deserializing check used for pickle-based frameworks when
        trust_artifact_source is False: existence was already confirmed by
        the caller, so this only checks size and extension.
        """
        size_bytes = artifact_path.stat().st_size
        if size_bytes == 0:
            raise ValidationError(f"Artifact at {artifact_path} is empty")

        allowed_extensions = ArtifactValidator.SUPPORTED_FRAMEWORKS.get(framework.lower(), [])
        suffix = artifact_path.suffix.lstrip(".").lower()
        if allowed_extensions and suffix not in allowed_extensions:
            logger.warning(
                f"Artifact extension '.{suffix}' is unusual for framework '{framework}' "
                f"(expected one of {allowed_extensions})."
            )

    @staticmethod
    def _validate_loadable(
        artifact_path: Path, framework: str, trust_artifact_source: bool = False
    ) -> None:
        """
        Attempt to load artifact to verify it's not corrupted.
        Dispatches to framework-specific loader helpers to keep complexity low.
        """
        framework_key = framework.lower()

        if framework_key in ArtifactValidator._PICKLE_BASED_FRAMEWORKS and not trust_artifact_source:
            logger.warning(
                f"Skipping deserialization of '{framework}' artifact at {artifact_path}: "
                "loading a pickle/joblib artifact executes it, so this requires "
                "trust_artifact_source=True. Falling back to a lightweight check."
            )
            ArtifactValidator._lightweight_validate(artifact_path, framework)
            return

        loaders = {
            "sklearn": ArtifactValidator._load_pickle,
            "scikit-learn": ArtifactValidator._load_pickle,
            "xgboost": lambda p: ArtifactValidator._load_xgboost(p, trust_artifact_source),
            "lightgbm": lambda p: ArtifactValidator._load_lightgbm(p, trust_artifact_source),
            "pytorch": ArtifactValidator._load_pytorch,
            "tensorflow": ArtifactValidator._load_tensorflow,
            "onnx": ArtifactValidator._load_onnx,
            "pickle": ArtifactValidator._load_pickle_joblib,
            "joblib": ArtifactValidator._load_pickle_joblib,
            "custom": ArtifactValidator._load_pickle_joblib,
        }

        loader = loaders.get(framework_key)
        if loader:
            # Let loader raise non-ImportError exceptions to indicate real failures
            try:
                loader(artifact_path)
            except ImportError:
                # Maintain previous behavior: log and skip validation when library not installed
                logger.warning(f"{framework} runtime not installed, skipping validation")
            return

        logger.warning(
            f"Unknown framework '{framework_key}', skipping artifact validation. "
            f"Supported: {', '.join(ArtifactValidator.SUPPORTED_FRAMEWORKS.keys())}"
        )

    @staticmethod
    def _load_pickle(artifact_path: Path) -> None:
        import pickle

        with open(artifact_path, "rb") as f:
            pickle.load(f)

    @staticmethod
    def _load_xgboost(artifact_path: Path, trust_artifact_source: bool = False) -> None:
        try:
            import xgboost as xgb  # type: ignore
        except ImportError as e:
            logger.warning("xgboost runtime not installed, cannot validate xgboost artifacts")
            raise ImportError("xgboost library is required to validate xgboost artifacts") from e
        # Try JSON booster first (native format, safe); otherwise the only
        # remaining option is the pickle fallback, which requires trust.
        if str(artifact_path).endswith(".json"):
            xgb.Booster(model_file=str(artifact_path))
        elif trust_artifact_source:
            ArtifactValidator._load_pickle(artifact_path)
        else:
            logger.warning(
                f"Skipping pickle-based validation of xgboost artifact at {artifact_path}: "
                "requires trust_artifact_source=True."
            )
            ArtifactValidator._lightweight_validate(artifact_path, "xgboost")

    @staticmethod
    def _load_lightgbm(artifact_path: Path, trust_artifact_source: bool = False) -> None:
        try:
            import lightgbm as lgb  # type: ignore
        except ImportError as e:
            logger.warning("lightgbm runtime not installed, cannot validate lightgbm artifacts")
            raise ImportError("lightgbm library is required to validate lightgbm artifacts") from e
        if str(artifact_path).endswith(".txt"):
            lgb.Booster(model_file=str(artifact_path))
        elif trust_artifact_source:
            ArtifactValidator._load_pickle(artifact_path)
        else:
            logger.warning(
                f"Skipping pickle-based validation of lightgbm artifact at {artifact_path}: "
                "requires trust_artifact_source=True."
            )
            ArtifactValidator._lightweight_validate(artifact_path, "lightgbm")

    @staticmethod
    def _load_pytorch(artifact_path: Path) -> None:
        try:
            import torch  # type: ignore
        except ImportError as e:
            logger.warning("pytorch runtime not installed, cannot validate pytorch artifacts")
            raise ImportError("pytorch library is required to validate pytorch artifacts") from e
        state = torch.load(artifact_path, map_location="cpu", weights_only=True)
        if not isinstance(state, dict):
            raise ValueError(f"Expected dict, got {type(state)}")

    @staticmethod
    def _load_tensorflow(artifact_path: Path) -> None:
        try:
            import tensorflow as tf  # type: ignore
        except ImportError as e:
            logger.warning("tensorflow runtime not installed, cannot validate tensorflow artifacts")
            raise ImportError(
                "tensorflow library is required to validate tensorflow artifacts"
            ) from e
        path_str = str(artifact_path)
        if path_str.endswith(".h5") or path_str.endswith(".keras"):
            tf.keras.models.load_model(artifact_path)
        elif path_str.endswith((".pb", ".pbtxt")):
            tf.saved_model.load(artifact_path)
        else:
            tf.keras.models.load_model(artifact_path)

    @staticmethod
    def _load_onnx(artifact_path: Path) -> None:
        try:
            import onnx  # type: ignore
        except ImportError as e:
            logger.warning("onnx runtime not installed, cannot validate onnx artifacts")
            raise ImportError("onnx library is required to validate onnx artifacts") from e
        model = onnx.load(str(artifact_path))
        onnx.checker.check_model(model)

    @staticmethod
    def _load_pickle_joblib(artifact_path: Path) -> None:
        # Try pickle first, then joblib; raise ValueError if both fail
        try:
            ArtifactValidator._load_pickle(artifact_path)
            return
        except Exception:
            pass

        try:
            import joblib  # type: ignore
        except ImportError:
            raise ValueError("Cannot load as pickle and joblib not available")

        try:
            joblib.load(artifact_path)
        except Exception as e:
            raise ValueError(f"Cannot load as pickle or joblib: {e}")
