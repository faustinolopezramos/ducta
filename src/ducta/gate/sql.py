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

import re
from typing import Any, ClassVar, List, Optional, Set

from loguru import logger  # type: ignore

from ducta.gate.exceptions import ConfigurationError

try:
    import sqlglot  # type: ignore

    SQLGLOT_AVAILABLE = True
except ImportError:
    SQLGLOT_AVAILABLE = False
    sqlglot = None


class SQLSanitizer:
    """Specialized class for secure SQL query sanitization."""

    DANGEROUS_KEYWORDS: ClassVar[Set[str]] = {
        "drop",
        "create",
        "alter",
        "truncate",
        "insert",
        "update",
        "delete",
        "merge",
        "exec",
        "execute",
        "xp_",
        "sp_",
        "call",
        "load_file",
        "into outfile",
        "into dumpfile",
        "information_schema",
        "sys.",
        "pg_",
    }

    COMMENT_PATTERNS: ClassVar[List[str]] = [
        r"--[^\r\n]*",  # Line comments --
        r"/\*[\s\S]*?\*/",  # Block comments /* */
        r"#[^\r\n]*",  # Line comments # (MySQL)
    ]

    SUSPICIOUS_PATTERNS: ClassVar[List[str]] = [
        r"0x[0-9a-f]+",  # Hexadecimal values
        r"char\s*\(",  # Suspicious char() conversions
        r"ascii\s*\(",  # Suspicious ASCII functions
        r"waitfor\s+delay",  # Timing attacks
        r"benchmark\s*\(",  # Benchmark attacks
    ]

    ALLOWED_AST_TYPES: ClassVar[Set[str]] = {
        "Select",
        "CTE",
        "With",
        "Union",
        "Intersect",
        "Except",
        "Subquery",
    }

    @classmethod
    def sanitize_query(cls, query: str) -> str:
        """Validate a read-only SQL query through three independent layers."""
        if not query or not isinstance(query, str):
            raise ConfigurationError("Query must be a non-empty string") from None

        original_query = query
        query = query.strip()

        if not query:
            raise ConfigurationError("Query cannot be empty after stripping whitespace") from None

        normalized_query = re.sub(r"\s+", " ", query)
        masked_for_checks = cls._mask_string_literals(normalized_query)

        cls._check_comment_safety(normalized_query)
        cls._check_multiple_statements(normalized_query)
        cls._check_suspicious_patterns(masked_for_checks)

        # Layer 2 — structural.
        if SQLGLOT_AVAILABLE:
            logger.debug("Using sqlglot AST parser for SQL validation")
            cls._validate_with_sqlglot(query)
        else:
            logger.debug("sqlglot not available, relying on lexical validation only")
            if not cls._is_select_query(normalized_query):
                raise ConfigurationError(
                    "Only SELECT and WITH queries are allowed. "
                    "Query must start with SELECT or WITH."
                ) from None

        cls._check_dangerous_keywords(masked_for_checks)

        return original_query

    @classmethod
    def _is_select_query(cls, query: str) -> bool:
        """Verify that the query is a valid SELECT."""
        clean_query = cls._remove_comments(query)
        clean_query = clean_query.strip().lower()
        return clean_query.startswith("select ") or clean_query.startswith("with ")

    @classmethod
    def _validate_with_sqlglot(cls, query: str) -> None:
        """Reject anything that is not a read-only SELECT/WITH at the AST level."""
        try:
            parsed = sqlglot.parse_one(query, read="spark")  # Use Spark dialect
        except sqlglot.ParseError as error:
            raise ConfigurationError(f"Invalid SQL syntax: {str(error)}") from error
        except Exception as error:
            logger.error("Unexpected sqlglot error during SQL validation: {}", error)
            raise ConfigurationError(f"SQL validation failed: {error}") from error

        if parsed is None:
            raise ConfigurationError("Failed to parse SQL query")

        query_type = type(parsed).__name__
        if query_type not in cls.ALLOWED_AST_TYPES:
            raise ConfigurationError(f"Only SELECT and WITH queries are allowed. Got: {query_type}")

        cls._check_ast_for_dangerous_operations(parsed)
        logger.debug("Query validated successfully using sqlglot AST parser")

    # scan behind a warning.
    DANGEROUS_EXPRESSIONS: ClassVar[List[str]] = [
        "Drop",
        "Delete",
        "Insert",
        "Update",
        "Create",
        "Alter",
        "Truncate",
        "Merge",
        "Command",  # covers EXECUTE / CALL
    ]

    @classmethod
    def _check_ast_for_dangerous_operations(cls, parsed: Any) -> None:
        """Check AST for dangerous SQL operations using sqlglot.expressions."""
        from sqlglot import expressions  # type: ignore

        for select_node in parsed.find_all(expressions.Select):
            if select_node.args.get("into"):
                raise ConfigurationError(
                    "Query contains forbidden operation: SELECT ... INTO (creates a table)"
                )

        resolved = []
        missing = []
        for name in cls.DANGEROUS_EXPRESSIONS:
            operation_class = getattr(expressions, name, None)
            if operation_class is None:
                missing.append(name)
            else:
                resolved.append((name, operation_class))

        if not resolved:
            # The whole scan is meaningless — fail closed rather than wave it through.
            raise ConfigurationError(
                "SQL AST validation unavailable: no known dangerous expression types "
                f"resolved from sqlglot (looked for {', '.join(cls.DANGEROUS_EXPRESSIONS)}). "
                "This usually means an incompatible sqlglot version."
            )
        if missing:
            logger.warning(
                "sqlglot does not expose {missing} — those node types are not scanned "
                "structurally (the lexical keyword check still covers them).",
                missing=", ".join(missing),
            )

        for name, operation_class in resolved:
            try:
                found = parsed.find(operation_class)
            except Exception as error:
                raise ConfigurationError(
                    f"SQL AST validation failed while scanning for {name}: {error}"
                ) from error
            if found:
                raise ConfigurationError(f"Query contains forbidden operation: {name}")

    @classmethod
    def _remove_comments(cls, query: str) -> str:
        """Remove SQL comments from the query."""
        for pattern in cls.COMMENT_PATTERNS:
            query = re.sub(pattern, "", query, flags=re.IGNORECASE | re.MULTILINE)
        return query

    @classmethod
    def _mask_string_literals(cls, query: str) -> str:
        """Replaces the content of string literals with spaces, preserving the quotes."""
        result: List[str] = []
        in_string = False
        quote_char = None
        char_index = 0
        while char_index < len(query):
            char = query[char_index]
            if not in_string and char in ("'", '"'):
                in_string = True
                quote_char = char
                result.append(char)
            elif in_string:
                if char == "\\" and char_index + 1 < len(query):
                    result.append(" ")
                    char_index += 1
                    result.append(" ")
                elif char == quote_char:
                    if char_index + 1 < len(query) and query[char_index + 1] == quote_char:
                        # Doubled quote: an escaped quote, still inside the literal.
                        result.append(" ")
                        result.append(" ")
                        char_index += 1
                    else:
                        in_string = False
                        quote_char = None
                        result.append(char)
                else:
                    result.append(" ")
            else:
                result.append(char)
            char_index += 1
        return "".join(result)

    @classmethod
    def _check_dangerous_keywords(cls, query: str) -> None:
        """Verify dangerous keywords."""
        query_lower = query.lower()
        for keyword in cls.DANGEROUS_KEYWORDS:
            if keyword.endswith("_"):
                pattern = r"\b" + re.escape(keyword)
            elif " " in keyword:
                pattern = r"\b" + re.sub(r"\s+", r"\\s+", re.escape(keyword)) + r"\b"
            else:
                pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, query_lower):
                raise ConfigurationError(
                    f"Query contains dangerous keyword: '{keyword}'. Only SELECT queries are allowed."
                ) from None

    @classmethod
    def _check_suspicious_patterns(cls, query: str) -> None:
        """Verify suspicious patterns that may indicate SQL injection."""
        query_lower = query.lower()
        for pattern in cls.SUSPICIOUS_PATTERNS:
            try:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    raise ConfigurationError(
                        "Query contains suspicious pattern that may indicate SQL injection attempt"
                    ) from None
            except re.error:
                continue

    @classmethod
    def _extract_comments(cls, query: str) -> List[str]:
        """Extracts the raw text of comments found in the query."""
        comments: List[str] = []
        for pattern in cls.COMMENT_PATTERNS:
            for match in re.finditer(pattern, query, flags=re.IGNORECASE | re.MULTILINE):
                comments.append(match.group(0))
        return comments

    @classmethod
    def _check_comment_safety(cls, query: str) -> None:
        """Validate that comments do not contain dangerous tokens or suspicious patterns."""
        comments = cls._extract_comments(query)
        if not comments:
            return

        for comment_text in comments:
            content_lower = cls._normalize_comment_content(comment_text)
            cls._assert_no_semicolon_in_comment(content_lower)

            dangerous_keyword = cls._find_dangerous_keyword_in_comment(content_lower)
            if dangerous_keyword:
                raise ConfigurationError(
                    f"Comments contain dangerous keyword '{dangerous_keyword}' which is not allowed"
                ) from None

            if cls._comment_contains_suspicious_pattern(content_lower):
                raise ConfigurationError(
                    "Comments contain suspicious pattern that may indicate SQL injection attempt"
                ) from None

    @classmethod
    def _normalize_comment_content(cls, comment: str) -> str:
        """Return the content of a comment normalized to lower case without delimiters."""
        if comment.startswith("--"):
            content = comment[2:]
        elif comment.startswith("#"):
            content = comment[1:]
        elif comment.startswith("/*") and comment.endswith("*/"):
            content = comment[2:-2]
        else:
            content = comment
        return content.lower()

    @classmethod
    def _assert_no_semicolon_in_comment(cls, content_lower: str) -> None:
        if ";" in content_lower:
            raise ConfigurationError(
                "Comments in query contain semicolon which could indicate multiple statements"
            ) from None

    @classmethod
    def _find_dangerous_keyword_in_comment(cls, content_lower: str):
        for keyword in cls.DANGEROUS_KEYWORDS:
            if keyword in content_lower:
                return keyword
        return None

    @classmethod
    def _comment_contains_suspicious_pattern(cls, content_lower: str) -> bool:
        for pattern in cls.SUSPICIOUS_PATTERNS:
            try:
                if re.search(pattern, content_lower, re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False

    @staticmethod
    def _is_quote_escaped(query: str, position: int) -> bool:
        """Return True if the quote at *position* is preceded by an odd number of backslashes."""
        backslash_count = 0
        index = position - 1
        while index >= 0 and query[index] == "\\":
            backslash_count += 1
            index -= 1
        return backslash_count % 2 == 1

    @classmethod
    def _count_semicolons_outside_strings(cls, query: str) -> int:
        """Count semicolons that appear outside string literals."""
        in_string = False
        quote_char = None
        count = 0
        index = 0
        while index < len(query):
            char = query[index]
            if char in ('"', "'") and not cls._is_quote_escaped(query, index):
                if not in_string:
                    in_string = True
                    quote_char = char
                elif char == quote_char:
                    if index + 1 < len(query) and query[index + 1] == quote_char:
                        index += 1  # doubled quote: consume the pair, stay inside
                    else:
                        in_string = False
                        quote_char = None
            elif char == ";" and not in_string:
                count += 1
            index += 1
        return count

    @classmethod
    def _check_multiple_statements(cls, query: str) -> None:
        """Verify that the query does not contain multiple SQL statements."""
        clean_query = cls._remove_comments(query)
        semicolon_count = cls._count_semicolons_outside_strings(clean_query)
        if semicolon_count > 1 or (semicolon_count == 1 and not clean_query.rstrip().endswith(";")):
            raise ConfigurationError(
                "Multiple SQL statements are not allowed. Only single SELECT queries are permitted."
            ) from None


class SqlSafetyMixin:
    """Mixin for SQL identifier/string-literal escaping used when building DDL."""

    @staticmethod
    def quote_identifier(name: str) -> str:
        """Quote SQL identifier safely."""
        if not name or not isinstance(name, str):
            raise ConfigurationError("Invalid identifier")
        return f"`{name.replace('`', '``')}`"

    @staticmethod
    def escape_string(value: str) -> str:
        """Escape SQL string literal (backslashes first, then single quotes)."""
        return str(value).replace("\\", "\\\\").replace("'", "''")

    def quote_table_name(self, full_name: str) -> str:
        """Quote full table name (catalog.schema.table)."""
        parts = [part.strip() for part in str(full_name).split(".") if part.strip()]
        if len(parts) != 3:
            raise ConfigurationError(f"Expected 3 parts in table name: {full_name}")
        return ".".join(self.quote_identifier(part) for part in parts)


class UnityCatalogDDL:
    """Builds the fixed set of DDL/maintenance statements UnityCatalogManager needs."""

    _safety = SqlSafetyMixin()

    @classmethod
    def catalog_exists_query(cls, catalog: str) -> str:
        escaped = cls._safety.escape_string(catalog)
        return f"SELECT 1 FROM system.information_schema.catalogs WHERE catalog_name = '{escaped}' LIMIT 1"

    @classmethod
    def schema_exists_query(cls, catalog: str, schema: str) -> str:
        escaped_catalog = cls._safety.escape_string(catalog)
        escaped_schema = cls._safety.escape_string(schema)
        return (
            "SELECT 1 FROM system.information_schema.schemata "
            f"WHERE catalog_name = '{escaped_catalog}' AND schema_name = '{escaped_schema}' LIMIT 1"
        )

    @classmethod
    def create_catalog(cls, catalog: str) -> str:
        return f"CREATE CATALOG {cls._safety.quote_identifier(catalog)}"

    @classmethod
    def create_schema(
        cls, catalog: str, schema: str, location: Optional[str] = None, managed: bool = False
    ) -> str:
        quoted_catalog = cls._safety.quote_identifier(catalog)
        quoted_schema = cls._safety.quote_identifier(schema)
        sql = f"CREATE SCHEMA IF NOT EXISTS {quoted_catalog}.{quoted_schema}"
        if location:
            location_type = "MANAGED LOCATION" if managed else "LOCATION"
            escaped_loc = cls._safety.escape_string(location)
            sql += f" {location_type} '{escaped_loc}'"
        return sql

    @classmethod
    def create_external_table(cls, full_table_name: str, location: str) -> str:
        quoted_name = cls._safety.quote_table_name(full_table_name)
        escaped_loc = cls._safety.escape_string(location)
        return f"CREATE TABLE IF NOT EXISTS {quoted_name} USING DELTA LOCATION '{escaped_loc}'"

    @classmethod
    def comment_on_table(cls, quoted_table_name: str, comment: str) -> str:
        escaped_comment = cls._safety.escape_string(comment)
        return f"COMMENT ON TABLE {quoted_table_name} IS '{escaped_comment}'"

    @classmethod
    def optimize_where(
        cls, quoted_table_name: str, column: str, start_date: str, end_date: str
    ) -> str:
        quoted_col = cls._safety.quote_identifier(column)
        start = cls._safety.escape_string(start_date)
        end = cls._safety.escape_string(end_date)
        return f"OPTIMIZE {quoted_table_name} WHERE {quoted_col} BETWEEN '{start}' AND '{end}'"

    @classmethod
    def vacuum(cls, quoted_table_name: str, hours: int) -> str:
        try:
            retain_hours = int(hours)
        except (TypeError, ValueError) as error:
            raise ConfigurationError(
                f"VACUUM retention must be a whole number of hours, got {hours!r}"
            ) from error
        return f"VACUUM {quoted_table_name} RETAIN {retain_hours} HOURS"

    @classmethod
    def replace_where_clause(cls, column: str, start_date: str, end_date: str) -> str:
        quoted_col = cls._safety.quote_identifier(column)
        start = cls._safety.escape_string(start_date)
        end = cls._safety.escape_string(end_date)
        return f"{quoted_col} BETWEEN '{start}' AND '{end}'"
