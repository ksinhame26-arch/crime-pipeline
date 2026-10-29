"""validate.py - data quality checks (sanity checks) on the raw extract.

Fail loudly (raise) when the data cannot be trusted at all:
  - expected columns missing
  - date_time not ISO 8601
  - missing values in required columns
Fail softly for non-numeric ids: mark them NaN, transform.py drops them.
"""
from datetime import datetime

import pandas as pd
from prefect import task

SCHEMA_COLS = ["date_time", "id", "type", "subtype", "location", "last_updated", "description"]
REQUIRED_COLS = ["date_time", "id", "type", "location"]


def check_valid_schema(df: pd.DataFrame) -> pd.DataFrame:
    """All expected columns must be present. Unexpected extra columns are
    dropped with a warning (the teacher's version fails on any difference;
    this is slightly more tolerant if the portal adds a column)."""
    missing = set(SCHEMA_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"Schema mismatch - missing columns: {sorted(missing)}")
    extra = set(df.columns) - set(SCHEMA_COLS)
    if extra:
        print(f"WARNING: dropping unexpected columns: {sorted(extra)}")
    return df[SCHEMA_COLS].copy()


def check_numeric_id(df: pd.DataFrame) -> pd.DataFrame:
    df["id"] = pd.to_numeric(df["id"], errors="coerce")  # non-numeric -> NaN
    bad = int(df["id"].isna().sum())
    if bad:
        print(f"WARNING: {bad} rows have non-numeric id (will be removed in transform)")
    return df


def verify_datetime(df: pd.DataFrame) -> None:
    for value in df["date_time"].dropna():
        datetime.fromisoformat(value)  # raises ValueError if not ISO 8601


def check_missing_values(df: pd.DataFrame) -> None:
    for col in REQUIRED_COLS:
        n = int(df[col].isna().sum())
        if n:
            raise ValueError(f"{n} missing values in required column '{col}'")


@task
def validate_data(df: pd.DataFrame) -> pd.DataFrame:
    df = check_valid_schema(df)
    check_missing_values(df)  # BEFORE id coercion: a truly empty id is an error,
    df = check_numeric_id(df)  # a non-numeric id only becomes NaN (dropped later)
    verify_datetime(df)
    print(f"Validation passed for {len(df)} rows")
    return df
