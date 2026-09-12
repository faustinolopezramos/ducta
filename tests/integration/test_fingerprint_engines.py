"""The same fingerprint guarantees, asserted against every engine.

This file exists because the previous fingerprint suite was pandas-only — zero
references to Spark across `tests/mlrun/test_fingerprint.py` and
`tests/gate/test_fingerprinting.py`. One of its tests
(`TestTailCorruptionDetectedByFastMode`) asserted, in so many words, that a
change past the sample window is detected. It passed. On Spark, which is the
only engine that executes a pipeline, none of that held:

  * `row_count` was always None (`df.shape[0]` does not exist on Spark)
  * "fast" collapsed to `head(n)` — a corrupted last row went unnoticed
  * "full" hashed `str(df)`, i.e. the *schema repr*, so any two frames sharing a
    schema were identical — making "full" weaker than "fast"

A single-engine suite could not have caught any of it. So the properties below
are written once and parametrized over engines: whatever we promise, we promise
everywhere, and adding an engine means making these pass rather than writing a
new file that quietly omits the hard cases.
"""

from __future__ import annotations

import pytest

from ducta.mlrun.fingerprint import (
    ALGO_PANDAS_EXACT,
    ALGO_SPARK_EXACT,
    ALGO_SPARK_EXACT_CRYPTO,
    DataFingerprint,
    comparable,
)

pytestmark = pytest.mark.spark  # the spark param needs a real session

#: (id, amount, name) — 5000 rows is comfortably past the 100-row sample window,
#: which is the whole point: the interesting failures hide past it.
SCHEMA = "id INT, amount DOUBLE, name STRING"
BASE = [(i, float(i), f"n{i}") for i in range(5000)]


@pytest.fixture(params=["pandas", "spark"])
def make_df(request, spark):
    """Return a callable that builds a DataFrame of *rows* for one engine."""
    engine = request.param

    if engine == "pandas":
        pd = pytest.importorskip("pandas")

        def _build(rows, partitions=1):
            return pd.DataFrame(rows, columns=["id", "amount", "name"])

    else:

        def _build(rows, partitions=2):
            # Repartitioning shuffles physical row order, which is exactly the
            # thing the digest must be insensitive to.
            return spark.createDataFrame(rows, SCHEMA).repartition(partitions)

    _build.engine = engine
    return _build


def fp(df, mode="exact"):
    return DataFingerprint.from_file_and_df("ds", "/does/not/exist", df, mode=mode)


class TestExactModeDetectsContentChange:
    """`exact` must notice any change to the data, wherever it sits."""

    def test_row_count_is_real(self, make_df):
        # Was None on Spark forever, while the README advertised it.
        assert fp(make_df(BASE)).row_count == 5000

    def test_identical_data_is_identical(self, make_df):
        assert fp(make_df(BASE)).fingerprint == fp(make_df(BASE)).fingerprint

    def test_physical_reordering_is_not_a_data_change(self, make_df):
        import random

        shuffled = list(BASE)
        random.Random(7).shuffle(shuffled)
        assert fp(make_df(shuffled, partitions=5)).fingerprint == fp(make_df(BASE)).fingerprint

    @pytest.mark.parametrize("index", [0, 2500, 4999], ids=["first", "middle", "last"])
    def test_a_single_changed_cell_is_detected_anywhere(self, make_df, index):
        # `last` is the regression: it was invisible on Spark in both old modes.
        mutated = list(BASE)
        mutated[index] = (mutated[index][0], -999999.0, mutated[index][2])
        assert fp(make_df(mutated)).fingerprint != fp(make_df(BASE)).fingerprint

    def test_a_duplicated_row_is_detected(self, make_df):
        # Guards the reason the digest is not a bare bit_xor: identical rows XOR
        # to zero, so an even number of some duplicate would cancel out and read
        # as unchanged.
        assert fp(make_df(BASE + [BASE[123]])).fingerprint != fp(make_df(BASE)).fingerprint

    def test_a_deleted_row_is_detected(self, make_df):
        assert fp(make_df(BASE[:-1])).fingerprint != fp(make_df(BASE)).fingerprint

    def test_null_is_not_the_empty_string(self, make_df):
        # A `concat_ws`-based digest would collide these; a type/null-aware row
        # hash must not.
        with_null = fp(make_df([(1, 1.0, None)]))
        with_empty = fp(make_df([(1, 1.0, "")]))
        assert with_null.fingerprint != with_empty.fingerprint


class TestSelfDescription:
    """A fingerprint has to say what it measured, or it cannot be trusted later."""

    def test_records_engine_and_algorithm(self, make_df):
        f = fp(make_df(BASE))
        assert f.engine == make_df.engine
        assert f.algorithm == (ALGO_SPARK_EXACT if make_df.engine == "spark" else ALGO_PANDAS_EXACT)
        assert f.content_hash

    def test_sample_mode_admits_what_it_covered(self, make_df):
        f = fp(make_df(BASE), mode="sample")
        assert f.details["sample_rows_covered"] <= 100
        # Spark's sample selects by row hash, not `limit`; it must say so.
        if make_df.engine == "spark":
            assert f.details["sampling"] == "deterministic-min-rowhash"

    def test_sample_mode_is_reproducible(self, make_df):
        """The same rows, sampled twice, must give the same hash.

        `limit(n)` has no defined order on a distributed DataFrame, so the old
        head-only sample could hash different rows on two runs over identical
        data — and `certify verify --reproduce` would call that a divergence.
        """
        first = fp(make_df(BASE), mode="sample")
        second = fp(make_df(BASE), mode="sample")
        assert first.sample_hash == second.sample_hash
        assert first.fingerprint == second.fingerprint

    def test_schema_mode_carries_no_content_claim(self, make_df):
        f = fp(make_df(BASE), mode="schema")
        assert f.content_hash is None
        assert f.row_count == 5000


class TestComparability:
    """An algorithm change is not a data change."""

    def test_same_algorithm_compares(self, make_df):
        a, b = fp(make_df(BASE)), fp(make_df(BASE))
        assert comparable(a.to_dict(), b.to_dict()) == (True, None)

    def test_across_modes_is_refused(self, make_df):
        exact, sampled = fp(make_df(BASE)), fp(make_df(BASE), mode="sample")
        ok, reason = comparable(exact.to_dict(), sampled.to_dict())
        assert ok is False
        assert "algorithm differs" in reason

    def test_against_a_legacy_fingerprint_is_refused(self, make_df):
        # Certificates written before v2 must not be reported as "the data
        # changed" the first time someone upgrades.
        ok, reason = comparable(fp(make_df(BASE)).to_dict(), {"algorithm": None})
        assert ok is False
        assert "legacy/v1" in reason

    def test_schema_only_never_claims_content_equality(self, make_df):
        a, b = fp(make_df(BASE), mode="schema"), fp(make_df(BASE), mode="schema")
        ok, reason = comparable(a.to_dict(), b.to_dict())
        assert ok is False
        assert "no content evidence" in reason


class TestExactCryptoMode:
    """`exact` aggregates xxhash64 row hashes with count+sum+xor.

    That is an excellent accidental-change detector, but xxhash64 is not a
    cryptographic hash: someone who can write the dataset can build rows with
    chosen hash values and land on the same digest with different content —
    which is precisely the adversary the HMAC signature exists for.
    `exact_crypto` swaps the row hash for SHA-256 and keeps the aggregate
    order-independent and distributed.
    """

    def test_it_keeps_every_property_exact_has(self, make_df):
        import random

        base = fp(make_df(BASE), mode="exact_crypto")
        assert base.row_count == 5000
        assert base.content_hash

        # identical data → identical digest
        assert fp(make_df(BASE), mode="exact_crypto").fingerprint == base.fingerprint

        # physical reordering is not a data change
        shuffled = list(BASE)
        random.Random(7).shuffle(shuffled)
        assert (
            fp(make_df(shuffled, partitions=5), mode="exact_crypto").fingerprint == base.fingerprint
        )

    @pytest.mark.parametrize("index", [0, 2500, 4999], ids=["first", "middle", "last"])
    def test_a_single_changed_cell_is_detected_anywhere(self, make_df, index):
        mutated = list(BASE)
        mutated[index] = (mutated[index][0], -999999.0, mutated[index][2])
        assert (
            fp(make_df(mutated), mode="exact_crypto").fingerprint
            != fp(make_df(BASE), mode="exact_crypto").fingerprint
        )

    def test_a_duplicated_row_is_detected(self, make_df):
        """Addition, not XOR: a repeated row must not cancel out."""
        duplicated = list(BASE) + [BASE[0]]
        assert (
            fp(make_df(duplicated), mode="exact_crypto").fingerprint
            != fp(make_df(BASE), mode="exact_crypto").fingerprint
        )

    def test_it_reports_its_own_algorithm_on_spark(self, make_df):
        f = fp(make_df(BASE), mode="exact_crypto")
        expected = ALGO_SPARK_EXACT_CRYPTO if make_df.engine == "spark" else ALGO_PANDAS_EXACT
        assert f.algorithm == expected

    def test_it_is_not_comparable_with_plain_exact_on_spark(self, make_df):
        """Different measure, different answer — never a silent "data changed"."""
        if make_df.engine != "spark":
            pytest.skip("pandas computes both modes identically, by design")
        crypto = fp(make_df(BASE), mode="exact_crypto").to_dict()
        plain = fp(make_df(BASE), mode="exact").to_dict()
        ok, reason = comparable(crypto, plain)
        assert ok is False
        assert reason
