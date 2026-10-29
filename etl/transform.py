"""transform.py - T of ETL: clean and enrich the validated data."""
import pandas as pd
from prefect import task


def remove_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop_duplicates(subset=["id"], keep="first")


def remove_invalid_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["id"]).copy()
    df["id"] = df["id"].astype("int64")  # 123.0 -> 123, matches BIGINT primary key
    return df


def split_datetime(df: pd.DataFrame) -> pd.DataFrame:
    df["date_time"] = pd.to_datetime(df["date_time"])
    df["last_updated"] = pd.to_datetime(df["last_updated"], errors="coerce")
    df["year"] = df["date_time"].dt.year
    df["month"] = df["date_time"].dt.month
    df["day"] = df["date_time"].dt.day
    df["hour"] = df["date_time"].dt.hour
    df["minute"] = df["date_time"].dt.minute
    df["second"] = df["date_time"].dt.second
    return df


@task
def transform_data(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = remove_invalid_rows(df)  # first, so NaN ids are not treated as duplicates of each other
    df = remove_duplicates(df)
    df = split_datetime(df)
    print(f"Transform: {before} -> {len(df)} rows")
    return df
