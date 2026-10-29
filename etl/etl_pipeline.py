"""etl_pipeline.py - the Prefect flow that ties E -> V -> T -> L together.

Run once (testing):   python etl_pipeline.py --once
Run on a schedule:    python etl_pipeline.py
  -> registers a deployment on the Prefect server (self-hosted in Docker, UI at
     http://localhost:4200, or Prefect Cloud) and keeps running, executing the
     flow on the cron schedule (process must stay alive: a terminal on the
     laptop, or the 'etl' Docker container on the cloud VM).
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()  # before Prefect is used, so PREFECT_API_URL from .env is honoured

from prefect import flow  # noqa: E402

from extract import extract_data  # noqa: E402
from load import load_into_postgres  # noqa: E402
from transform import transform_data  # noqa: E402
from validate import validate_data  # noqa: E402


@flow(name="cpd_incident_etl", log_prints=True)  # name shown in Prefect UI; prints go to Prefect logs
def etl():
    print("Extracting data...")
    raw = extract_data()
    print("Performing data quality checks...")
    valid = validate_data(raw)
    print("Performing data transformations...")
    clean = transform_data(valid)
    print("Importing data into Postgres...")
    rows = load_into_postgres(clean)
    print(f"ETL complete! {rows} rows in cpd_incidents")


if __name__ == "__main__":
    if "--once" in sys.argv:
        etl()
    else:
        # Data is updated daily -> run daily. Timezone is explicit so midnight
        # means midnight IST, not UTC (Prefect's default).
        cron = os.getenv("ETL_CRON", "0 0 * * *")
        tz = os.getenv("ETL_TIMEZONE", "Asia/Kolkata")
        name = os.getenv("DEPLOYMENT_NAME", "cpd-pipeline-deployment")
        from prefect.schedules import Cron
        etl.serve(name=name, schedules=[Cron(cron, timezone=tz)])
