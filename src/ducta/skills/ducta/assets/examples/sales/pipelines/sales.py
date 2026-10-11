"""The functions the silver.sales pipeline runs: DataFrames in, a DataFrame out."""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def clean_orders(orders: DataFrame) -> DataFrame:
    return orders.dropDuplicates(["order_id"]).filter(F.col("amount") > 0)


def daily_revenue(orders: DataFrame) -> DataFrame:
    return orders.groupBy("order_date").agg(F.sum("amount").alias("revenue"))
