"""load.py - L of ETL: load the transformed data into PostgreSQL.

Strategy: full refresh inside ONE transaction
  CREATE TABLE IF NOT EXISTS -> TRUNCATE -> INSERT (append)
Why not to_sql(if_exists="replace") like the notebook? "replace" DROPS the
table and recreates it from pandas types, so the PRIMARY KEY and our column
types are lost (and pandas adds an extra 'index' column). TRUNCATE keeps the
table definition. Because it is one transaction, a failed run rolls back and
the dashboard never sees a half-empty table. Re-running is safe (idempotent).
"""
import os

import pandas as pd
from dotenv import load_dotenv
from prefect import task
from sqlalchemy import URL, create_engine, text

TABLE = "cpd_incidents"
COLUMNS = ["date_time", "id", "type", "subtype", "location", "description", "last_updated",
           "year", "month", "day", "hour", "minute", "second"]

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    date_time    TIMESTAMP NOT NULL,
    id           BIGINT PRIMARY KEY,
    type         TEXT NOT NULL,
    subtype      TEXT,
    location     TEXT NOT NULL,
    description  TEXT,
    last_updated TIMESTAMP,
    year         INTEGER,
    month        INTEGER,
    day          INTEGER,
    hour         INTEGER,
    minute       INTEGER,
    second       INTEGER
)
"""


def get_engine():
    load_dotenv()
    url = URL.create(
        "postgresql+psycopg2",
        username=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),  # URL.create handles special characters safely
        host=os.getenv("DB_HOST", "localhost"),  # 'postgres_cpd' when running inside Docker
        port=int(os.getenv("DB_PORT", "5433")),  # 5432 inside Docker network
        database=os.getenv("POSTGRES_DB", "cpd_db"),
    )
    return create_engine(url)


@task
def load_into_postgres(df: pd.DataFrame) -> int:
    engine = get_engine()
    with engine.begin() as conn:  # BEGIN ... COMMIT (or ROLLBACK on error)
        conn.execute(text(CREATE_TABLE_SQL))
        conn.execute(text(f"TRUNCATE TABLE {TABLE}"))
        df[COLUMNS].to_sql(TABLE, conn, if_exists="append", index=False,
                           method="multi", chunksize=1000)
        count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
    engine.dispose()
    print(f"Loaded {count} rows into {TABLE}")
    return count
