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

A SQL business rule (a WHERE-clause predicate) evaluated over a pandas frame,
inside the server, without running any code the rule could shape.

The rule is parsed with sqlglot and its tree is *interpreted* here, node by
node, against a short list of what a row rule needs: columns, literals,
comparisons, AND/OR/NOT, IS [NOT] NULL, [NOT] IN, BETWEEN, [I]LIKE, arithmetic
and a few scalar functions. Anything else raises ``ValueError`` — the rule
still runs on Spark in a real or sample run; it is just not evaluated here.

sqlglot's own executor is not used: it translates SQL into Python source and
``eval``s it, and a JSON path in the rule reached that source unescaped, which
let a request body run code in the server process.
"""

from __future__ import annotations

import operator
from typing import Any, Callable, Dict

#: Longer rules are refused before parsing (a row rule is a line, not a program).
MAX_RULE_LENGTH = 4000


class _NotHere(ValueError):
    """The rule uses something this evaluator does not interpret."""


def _exp() -> Any:
    from sqlglot import exp

    return exp


def rule_mask(df: Any, rule: str) -> Any:
    """A boolean Series: True where the row breaks *rule* (the rule is FALSE for it).

    As in SQL ``WHERE NOT (rule)``, a row for which the rule is NULL does not break it.
    Raises ``ValueError`` for a rule that is not a plain predicate or uses something
    not interpreted here.
    """
    import sqlglot

    from ducta.gate.sql import validate_predicate

    text = str(rule or "").strip()
    if not text:
        raise ValueError("An empty SQL rule")
    if len(text) > MAX_RULE_LENGTH:
        raise ValueError(f"SQL rule longer than {MAX_RULE_LENGTH} characters")
    validate_predicate(text)
    try:
        tree = sqlglot.parse_one(text, read="spark")
    except sqlglot.errors.ParseError as e:
        raise ValueError(f"SQL rule '{text}' does not parse: {e}") from e
    result = _as_bool(_Evaluator(df).eval(tree), text)
    return ~result.fillna(True).astype(bool)


class _Evaluator:
    def __init__(self, df: Any) -> None:
        import pandas as pd

        self.pd = pd
        self.df = df
        self.exp = _exp()
        self.columns = {str(c).lower(): c for c in df.columns}

    # ── values ─────────────────────────────────────────────

    def series(self, value: Any) -> Any:
        pd = self.pd
        if isinstance(value, pd.Series):
            return value
        if value is None:
            return pd.Series([None] * len(self.df), index=self.df.index, dtype=object)
        return pd.Series([value] * len(self.df), index=self.df.index)

    def column(self, node: Any) -> Any:
        if node.table:
            raise _NotHere(f"Column '{node.sql()}' names a table; a row rule reads its own row")
        name = node.name
        col = self.columns.get(str(name).lower())
        if col is None:
            raise ValueError(f"No column '{name}' in the dataset")
        return self.df[col]

    def literal(self, node: Any) -> Any:
        if node.is_string:
            return str(node.this)
        text = str(node.this)
        try:
            return int(text)
        except ValueError:
            return float(text)

    # ── the tree ───────────────────────────────────────────

    def eval(self, node: Any) -> Any:  # noqa: C901 — one branch per node kind
        exp = self.exp
        if isinstance(node, exp.Paren):
            return self.eval(node.this)
        if isinstance(node, exp.Column):
            return self.column(node)
        if isinstance(node, exp.Literal):
            return self.literal(node)
        if isinstance(node, exp.Boolean):
            return bool(node.this)
        if isinstance(node, exp.Null):
            return None
        if isinstance(node, exp.Neg):
            return self.arith(operator.mul, -1, self.eval(node.this))
        for kind, op in _ARITH.items():
            if type(node) is getattr(exp, kind):
                return self.arith(op, self.eval(node.this), self.eval(node.expression))
        for kind, op in _COMPARE.items():
            if type(node) is getattr(exp, kind):
                return self.compare(op, self.eval(node.this), self.eval(node.expression))
        if isinstance(node, exp.Not):
            return ~self.boolean(self.eval(node.this))
        if isinstance(node, exp.And):
            return self.boolean(self.eval(node.this)) & self.boolean(self.eval(node.expression))
        if isinstance(node, exp.Or):
            return self.boolean(self.eval(node.this)) | self.boolean(self.eval(node.expression))
        if isinstance(node, exp.Is):
            return self.is_(node)
        if isinstance(node, exp.In):
            return self.in_(node)
        if isinstance(node, exp.Between):
            value = self.eval(node.this)
            low = self.compare(operator.ge, value, self.eval(node.args["low"]))
            high = self.compare(operator.le, value, self.eval(node.args["high"]))
            return low & high
        if isinstance(node, (exp.Like, exp.ILike)):
            out = self.like(node, ignore_case=isinstance(node, exp.ILike))
            return ~out if node.args.get("negate") else out
        return self.function(node)

    def function(self, node: Any) -> Any:
        exp = self.exp
        if isinstance(node, exp.Coalesce):
            out = self.series(self.eval(node.this))
            for other in node.expressions:
                out = out.where(out.notna(), self.series(self.eval(other)))
            return out
        for kind, fn in _STRING_FUNCTIONS.items():
            if type(node) is getattr(exp, kind, None):
                if any(v for k, v in node.args.items() if k != "this"):
                    raise _NotHere(f"{node.sql()} takes extra arguments not evaluated here")
                return self.strings(self.eval(node.this), fn)
        if isinstance(node, exp.Abs):
            return self.arith(lambda a, _b: abs(a), self.eval(node.this), 0)
        raise _NotHere(f"'{node.sql()}' is not evaluated here")

    # ── operations ─────────────────────────────────────────

    def nulls(self, *values: Any) -> Any:
        mask = self.series(False).astype(bool)
        for v in values:
            mask = mask | self.series(v).isna().to_numpy()
        return mask

    def compare(self, op: Callable[[Any, Any], Any], left: Any, right: Any) -> Any:
        pd = self.pd
        a, b = self.series(left), self.series(right)
        # As Spark: text compared with a number is read as a number (NULL when it is not one).
        # A CSV read without a schema gives every column as text.
        if _numeric(a) and _textual(b):
            b = pd.to_numeric(b, errors="coerce")
        elif _numeric(b) and _textual(a):
            a = pd.to_numeric(a, errors="coerce")
        null = self.nulls(a, b)
        out = pd.Series(pd.NA, index=self.df.index, dtype="boolean")
        ok = ~null
        if ok.any():
            try:
                out[ok] = op(a[ok], b[ok]).astype(bool)
            except TypeError as e:
                raise ValueError(f"The rule compares values of different types: {e}") from e
        return out

    def arith(self, op: Callable[[Any, Any], Any], left: Any, right: Any) -> Any:
        pd = self.pd
        a, b = self.series(left), self.series(right)
        null = self.nulls(a, b)
        try:
            a_num = pd.to_numeric(a.where(~null), errors="raise")
            b_num = pd.to_numeric(b.where(~null), errors="raise")
        except (TypeError, ValueError) as e:
            raise ValueError(f"Arithmetic on values that are not numbers: {e}") from e
        with _quiet_numpy():
            out = op(a_num.astype(float), b_num.astype(float))
        # As Spark: dividing by zero is NULL, not infinity.
        out = out.where(~null & self.pd.Series(out.abs() != float("inf"), index=out.index))
        return out

    def boolean(self, value: Any) -> Any:
        return _as_bool(self.series(value), "a condition")

    def is_(self, node: Any) -> Any:
        value = self.series(self.eval(node.this))
        target = node.expression
        if isinstance(target, self.exp.Null):
            return value.isna().astype("boolean")
        if isinstance(target, self.exp.Boolean):
            b = self.boolean(value)
            return (b == bool(target.this)).fillna(False).astype("boolean")
        raise _NotHere(f"'{node.sql()}' is not evaluated here")

    def in_(self, node: Any) -> Any:
        if node.args.get("query") or node.args.get("unnest") or node.args.get("field"):
            raise _NotHere(f"'{node.sql()}' is not evaluated here")
        value = self.eval(node.this)
        out = None
        for item in node.expressions:
            hit = self.compare(operator.eq, value, self.eval(item))
            out = hit if out is None else (out | hit)
        if out is None:
            raise ValueError("IN () with nothing in it")
        return out

    def like(self, node: Any, ignore_case: bool) -> Any:
        pattern = node.expression
        if not (isinstance(pattern, self.exp.Literal) and pattern.is_string):
            raise _NotHere("LIKE with a pattern that is not a string literal is not evaluated here")
        if node.args.get("escape"):
            raise _NotHere("LIKE ... ESCAPE is not evaluated here")
        matches = like_matcher(str(pattern.this), ignore_case)
        value = self.series(self.eval(node.this))
        return self.strings_bool(value, matches)

    def strings(self, value: Any, fn: Callable[[str], Any]) -> Any:
        s = self.series(value)
        return s.map(lambda v: None if _isnull(v) else fn(str(v)))

    def strings_bool(self, value: Any, fn: Callable[[str], bool]) -> Any:
        pd = self.pd
        out = self.strings(value, fn)
        return pd.Series(pd.array(list(out), dtype="boolean"), index=out.index)


def like_matcher(pattern: str, ignore_case: bool = False) -> Callable[[str], bool]:
    """Whether a text matches the SQL ``LIKE`` *pattern* (``%`` any run, ``_`` one character).

    Without backtracking: the pattern is cut at each ``%`` into pieces; the first must
    start the text, the last must end it, and each piece between is taken at its
    leftmost place after the previous one — leftmost leaves the most room for the rest,
    so it never needs to try another. The cost is at most len(text) × len(pattern).
    A regular expression (``.*`` for ``%``) backtracked instead: 8 ``%`` against a value
    of 60 characters took 21 seconds, and anyone allowed to read quality could send it.
    """
    fold = str.lower if ignore_case else (lambda s: s)
    pieces = fold(pattern).split("%")

    def piece_at(text: str, piece: str, at: int) -> bool:
        if at + len(piece) > len(text):
            return False
        return all(p == "_" or p == text[at + i] for i, p in enumerate(piece))

    def find(text: str, piece: str, start: int, stop: int) -> int:
        for at in range(start, stop - len(piece) + 1):
            if piece_at(text, piece, at):
                return at
        return -1

    def matches(value: str) -> bool:
        text = fold(value)
        if len(pieces) == 1:
            return len(text) == len(pieces[0]) and piece_at(text, pieces[0], 0)
        first, *middle, last = pieces
        if len(first) + len(last) > len(text):
            return False
        if not piece_at(text, first, 0) or not piece_at(text, last, len(text) - len(last)):
            return False
        at, stop = len(first), len(text) - len(last)
        for piece in middle:
            if not piece:
                continue
            found = find(text, piece, at, stop)
            if found < 0:
                return False
            at = found + len(piece)
        return True

    return matches


def _numeric(series: Any) -> bool:
    from pandas.api.types import is_bool_dtype, is_numeric_dtype

    return bool(is_numeric_dtype(series.dtype) and not is_bool_dtype(series.dtype))


def _textual(series: Any) -> bool:
    from pandas.api.types import is_object_dtype, is_string_dtype

    return bool(is_object_dtype(series.dtype) or is_string_dtype(series.dtype))


def _isnull(value: Any) -> bool:
    import pandas as pd

    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _as_bool(value: Any, what: str) -> Any:
    import pandas as pd

    if str(value.dtype) == "boolean":
        return value
    if value.dtype == bool:
        return value.astype("boolean")
    present = value.dropna()
    if all(isinstance(v, bool) or type(v).__name__ == "bool_" for v in present):
        cells = [None if _isnull(v) else bool(v) for v in value]
        return pd.Series(pd.array(cells, dtype="boolean"), index=value.index)
    raise ValueError(f"The SQL rule is not a condition ({what} is not TRUE or FALSE)")


class _quiet_numpy:
    def __enter__(self) -> None:
        import numpy as np

        self._old = np.seterr(all="ignore")

    def __exit__(self, *_: Any) -> None:
        import numpy as np

        np.seterr(**self._old)


_ARITH: Dict[str, Callable[[Any, Any], Any]] = {
    "Add": operator.add,
    "Sub": operator.sub,
    "Mul": operator.mul,
    "Div": operator.truediv,
    "Mod": operator.mod,
}
_COMPARE: Dict[str, Callable[[Any, Any], Any]] = {
    "EQ": operator.eq,
    "NEQ": operator.ne,
    "GT": operator.gt,
    "GTE": operator.ge,
    "LT": operator.lt,
    "LTE": operator.le,
}
_STRING_FUNCTIONS: Dict[str, Callable[[str], Any]] = {
    "Length": len,
    "Upper": str.upper,
    "Lower": str.lower,
    "Trim": str.strip,
}
