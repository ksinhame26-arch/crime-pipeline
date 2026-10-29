"""Day 1 check: can we reach the Socrata API with our token? (fetches 5 rows only)"""
import os

import pandas as pd
from dotenv import load_dotenv
from sodapy import Socrata

load_dotenv()
token = os.getenv("SOCRATA_APP_TOKEN")
print("Token found in .env:", bool(token))
with Socrata("data.cambridgema.gov", token, timeout=30) as client:
    rows = client.get("3gki-wyrb", limit=5)
df = pd.DataFrame.from_records(rows)
print(df)
print("Columns:", list(df.columns))
print("API OK")
