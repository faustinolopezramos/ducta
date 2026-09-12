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

from typing import Any, Dict, List, Tuple, Type

from loguru import logger  # type: ignore

from ducta.stream.exceptions import StreamingError, StreamingFormatNotSupportedError


class StreamingHandlerFactory:
    """Generic lazy-instantiating, cache-on-first-use factory for streaming
    readers/writers.
    """

    _KIND: str = "handler"
    _BASE_CLASS: Type[Any] = object

    def __init__(self, context: Any):
        self.context = context
        # format_name -> instantiated handler (populated on first access)
        self._instances: Dict[str, Any] = {}
        # format_name -> (cls, extra_args, extra_kwargs), so *args/**kwargs
        # passed to register_custom() are forwarded at first instantiation.
        self._classes: Dict[str, Tuple[type, tuple, dict]] = {}
        self._register_builtin_classes()
        logger.info(
            f"Streaming{self._KIND.capitalize()}Factory ready with formats: "
            f"{list(self._classes.keys())}"
        )

    def _register_builtin_classes(self) -> None:
        """Populate ``self._classes`` with the built-in handler classes.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def _get_or_create(self, format_key: str) -> Any:
        """Lazily instantiate and cache a handler for the given format key."""
        if format_key not in self._instances:
            cls, extra_args, extra_kwargs = self._classes[format_key]
            try:
                self._instances[format_key] = cls(self.context, *extra_args, **extra_kwargs)
            except Exception as e:
                raise StreamingError(
                    f"Failed to instantiate {self._KIND} for format '{format_key}': {str(e)}",
                    cause=e,
                ) from e
        return self._instances[format_key]

    def get(self, format_name: str) -> Any:
        """Get the handler for the specified format."""
        try:
            if not format_name or not isinstance(format_name, str):
                raise StreamingError("Format name must be a non-empty string")

            format_key = format_name.lower()
            if format_key not in self._classes:
                supported = list(self._classes.keys())
                raise StreamingFormatNotSupportedError(
                    f"Streaming format '{format_name}' not supported. Supported formats: {supported}"
                )
            return self._get_or_create(format_key)
        except Exception as e:
            logger.error(f"Error getting {self._KIND} for format '{format_name}': {str(e)}")
            raise

    def list_supported_formats(self) -> List[str]:
        """List all supported streaming formats."""
        return list(self._classes.keys())

    def register_custom(self, format_name: str, handler_class: type, *args: Any, **kwargs: Any):
        """Register a custom handler class.

        ``*args``/``**kwargs`` are stored and forwarded to the handler
        constructor on its first use, alongside the mandatory ``context`` arg.
        """
        try:
            if not issubclass(handler_class, self._BASE_CLASS):
                raise StreamingError(
                    f"Custom {self._KIND} must inherit from {self._BASE_CLASS.__name__}"
                )
            key = format_name.lower()
            self._classes[key] = (handler_class, args, kwargs)
            # If already cached, invalidate so the new class is used
            self._instances.pop(key, None)
            logger.info(f"Registered custom {self._KIND} '{format_name}'")
        except Exception as e:
            logger.error(f"Error registering custom {self._KIND} '{format_name}': {str(e)}")
            raise StreamingError(f"Failed to register custom {self._KIND}: {str(e)}")
