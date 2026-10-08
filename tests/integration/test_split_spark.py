"""split_dataframe on a Spark DataFrame: same guarantees as pandas, without collecting."""

from __future__ import annotations

import datetime as dt

import pytest

from ducta.mlrun.split import SplitError, kfold_splits, split_dataframe


@pytest.fixture
def rows(spark):
    data = [
        (i, f"user{i % 50}", i % 4 == 0, dt.datetime(2026, 1, 1) + dt.timedelta(hours=i))
        for i in range(2000)
    ]
    return spark.createDataFrame(data, "id INT, user STRING, label BOOLEAN, ts TIMESTAMP")


def _ids(df):
    return {r.id for r in df.select("id").collect()}


def test_random_keeps_every_row_once_in_about_the_requested_share(rows):
    train, test = split_dataframe(rows, {"method": "random", "test_size": 0.2, "seed": 7})
    a, b = _ids(train), _ids(test)
    assert not a & b and len(a | b) == 2000
    assert 0.15 < len(b) / 2000 < 0.25


def test_the_same_seed_gives_the_same_rows_whatever_the_partitioning(rows):
    cfg = {"method": "random", "test_size": 0.2, "seed": 7}
    _, first = split_dataframe(rows, cfg)
    _, again = split_dataframe(rows.repartition(7), cfg)
    _, other = split_dataframe(rows, {**cfg, "seed": 8})
    assert _ids(first) == _ids(again) != _ids(other)


def test_a_group_never_spans_train_and_test(rows):
    train, test = split_dataframe(rows, {"method": "group", "group_col": "user", "seed": 1})
    users = lambda df: {r.user for r in df.select("user").distinct().collect()}  # noqa: E731
    assert not users(train) & users(test)


def test_stratified_takes_the_share_of_each_class(rows):
    train, test = split_dataframe(
        rows, {"method": "stratified", "stratify_col": "label", "test_size": 0.25, "seed": 3}
    )
    positives = test.filter("label").count()
    assert positives == pytest.approx(500 * 0.25, abs=2)
    assert test.filter("NOT label").count() == pytest.approx(1500 * 0.25, abs=2)
    assert train.count() + test.count() == 2000


def test_temporal_trains_on_the_past(rows):
    train, val, test = split_dataframe(
        rows, {"method": "temporal", "time_col": "ts", "test_size": 0.2, "val_size": 0.1}
    )
    last = lambda df, fn: df.agg({"ts": fn}).collect()[0][0]  # noqa: E731
    assert last(train, "max") < last(val, "min") <= last(val, "max") < last(test, "min")
    assert test.count() == pytest.approx(400, abs=5)


def test_the_node_is_marked_as_having_applied_it(rows):
    ctx = {"split_applied": False}
    split_dataframe(rows, {"method": "random", "seed": 1}, ml_context=ctx)
    assert ctx["split_applied"] is True


def test_an_empty_partition_is_refused(spark):
    two_users = spark.createDataFrame([(1, "a"), (2, "a")], "id INT, user STRING")
    with pytest.raises(SplitError, match="empty partition"):
        split_dataframe(two_users, {"method": "group", "group_col": "user", "seed": 1})


def test_kfold_still_needs_pandas_and_says_how(rows):
    with pytest.raises(SplitError, match="kfold_splits operates on pandas.*toPandas"):
        kfold_splits(rows, {"method": "random"})
