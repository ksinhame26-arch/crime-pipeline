"""extract.py - E of ETL.

Fetch the Cambridge (MA) Police Department Daily Police Log from the
Socrata Open Data API and return it as a pandas DataFrame.
"""
import os

import pandas as pd
from dotenv import load_dotenv
from prefect import task
from sodapy import Socrata

DOMAIN = "data.cambridgema.gov"
DATASET_ID = "3gki-wyrb"  # Daily Police Log


@task(retries=3, retry_delay_seconds=[10, 10, 10])  # API calls can fail transiently -> retry
def extract_data() -> pd.DataFrame:
    load_dotenv()
    app_token = os.getenv("SOCRATA_APP_TOKEN")  # avoids throttling; kept out of source code
    if not app_token:
        print("WARNING: SOCRATA_APP_TOKEN not set - requests may be throttled.")

    # timeout 30s instead of the 10s default: fetching every page can be slow
    with Socrata(DOMAIN, app_token, timeout=30) as client:
        results = client.get_all(DATASET_ID)  # generator that paginates over all rows
        df = pd.DataFrame.from_records(list(results))

    print(f"Extracted {len(df)} rows, columns: {list(df.columns)}")
    return df
