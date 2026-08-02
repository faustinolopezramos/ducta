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

from abc import ABC, abstractmethod
from typing import Any, Dict

from ducta.gate.constants import SupportedFormats
from ducta.gate.exceptions import FormatNotSupportedError


class BaseFactory(ABC):
    """Base factory class with common registry management."""

    def __init__(self, context: Any):
        self.context = context
        self._registry: Dict[str, Any] = {}  # format -> handler *class*
        self._instances: Dict[str, Any] = {}  # format -> handler *instance* (lazy)
        self._cache_context: Dict[str, Any] = {}  # format -> context used at cache time
        self._register_handlers()

    @abstractmethod
    def _register_handlers(self) -> None:
        """Register available handler classes. Must be implemented by subclasses."""
        ...

    def get_handler(self, format_name: str) -> Any:
        """Get (or lazily create) handler for the specified format."""
        format_key = format_name.lower()
        if format_key not in self._registry:
            raise FormatNotSupportedError(f"Format '{format_name}' not supported")
        if (
            format_key not in self._instances
            or self._cache_context.get(format_key) is not self.context
        ):
            self._instances[format_key] = self._registry[format_key](self.context)
            self._cache_context[format_key] = self.context
        return self._instances[format_key]

    def register(self, name: str, handler_cls: Any) -> None:
        """Register (or override) a handler class for `name` on this factory instance.

        Instance-scoped: does not affect other factory instances. If `name` was
        already registered, the cached instance is dropped so the next
        get_handler() call re-instantiates using the new class.
        """
        key = name.lower()
        self._registry[key] = handler_cls
        self._instances.pop(key, None)
        self._cache_context.pop(key, None)


class ReaderFactory(BaseFactory):
    """Factory for creating data readers."""

    def _register_handlers(self) -> None:
        """Register available readers."""
        from .readers import (
            AvroReader,
            CSVReader,
            DeltaReader,
            JSONReader,
            ORCReader,
            ParquetReader,
            PickleReader,
            QueryReader,
            XMLReader,
        )

        self._registry = {
            SupportedFormats.PARQUET.value: ParquetReader,
            SupportedFormats.JSON.value: JSONReader,
            SupportedFormats.CSV.value: CSVReader,
            SupportedFormats.DELTA.value: DeltaReader,
            SupportedFormats.PICKLE.value: PickleReader,
            SupportedFormats.AVRO.value: AvroReader,
            SupportedFormats.ORC.value: ORCReader,
            SupportedFormats.XML.value: XMLReader,
            SupportedFormats.QUERY.value: QueryReader,
        }

    def get_reader(self, format_name: str) -> Any:
        """Get reader for specified format."""
        return self.get_handler(format_name)

    def register_reader(self, name: str, reader_cls: Any) -> None:
        """Register (or override) a reader class for `name` on this instance."""
        self.register(name, reader_cls)


class WriterFactory(BaseFactory):
    """Factory for creating data writers."""

    def _register_handlers(self) -> None:
        """Register available writers."""
        from .writers import CSVWriter, DeltaWriter, JSONWriter, ORCWriter, ParquetWriter

        self._registry = {
            SupportedFormats.DELTA.value: DeltaWriter,
            SupportedFormats.PARQUET.value: ParquetWriter,
            SupportedFormats.CSV.value: CSVWriter,
            SupportedFormats.JSON.value: JSONWriter,
            SupportedFormats.ORC.value: ORCWriter,
        }

    def get_writer(self, format_name: str) -> Any:
        """Get writer for specified format."""
        return self.get_handler(format_name)

    def register_writer(self, name: str, writer_cls: Any) -> None:
        """Register (or override) a writer class for `name` on this instance."""
        self.register(name, writer_cls)
