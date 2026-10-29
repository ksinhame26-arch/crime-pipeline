# Data Pipeline to Monitor Local Crime Trends (PAI-102)

An automated ETL pipeline that pulls the Cambridge (MA) Police Department
Daily Police Log every day, validates and transforms it, loads it into
PostgreSQL, and serves a Metabase dashboard that can be opened from any PC.

```
Socrata API ──► extract ──► validate ──► transform ──► load ──► PostgreSQL ──► Metabase dashboard
 (3gki-wyrb)   └──────────── Prefect flow "cpd_incident_etl", daily cron ───────────┘   (port 3000)
```

| Layer          | Tool                                   |
|----------------|----------------------------------------|
| Source         | Socrata Open Data API (`sodapy`)       |
| Processing     | Python 3.12 + pandas                   |
| Orchestration  | Prefect 3 (self-hosted server + UI in Docker; Prefect Cloud optional) |
| Storage        | PostgreSQL 16 (Docker)                 |
| Visualisation  | Metabase (Docker)                      |
| Cloud          | Azure for Students, Ubuntu VM          |

## Project structure

```
crime-pipeline/
├── docker-compose.yml   # postgres_cpd, pgadmin, postgres_mb, metabase, prefect_server, etl
├── RUN_ME_setup.bat     # Windows one-click: start stack, install deps, first load
├── start_schedule.bat   # Windows: start the daily schedule (Prefect UI opens)
├── deploy/
│   ├── azure_vm_setup.sh       # one-command cloud deployment on Ubuntu
│   ├── cloud-init.example.yaml # paste into Azure 'Custom data' for zero-touch setup
│   └── metabase_bootstrap.py   # auto-creates admin, DB connection, dashboard, public link
├── .env.example         # copy to .env and fill in secrets
├── README.md
└── etl/
    ├── extract.py       # Socrata API -> DataFrame (3 retries, 30 s timeout)
    ├── validate.py      # schema, numeric id, ISO-8601 datetime, required values
    ├── transform.py     # drop invalid ids, dedupe on id, split date_time
    ├── load.py          # CREATE IF NOT EXISTS + TRUNCATE + INSERT in one transaction
    ├── etl_pipeline.py  # Prefect flow + daily schedule
    ├── test_api.py      # quick API connectivity check
    ├── requirements.txt
    └── Dockerfile
```

## Changes from the reference notebook (and why)

1. **Load uses TRUNCATE + append instead of `to_sql(if_exists="replace")`.**
   `replace` drops the table, so the `PRIMARY KEY` and column types are lost and
   an extra `index` column appears. All of it runs in one transaction, so a
   failed run rolls back and the dashboard never shows a half-loaded table.
2. **`id` is cast to `int64`** after dropping NaN ids (the column is float after
   `to_numeric`), and stored as `BIGINT PRIMARY KEY`.
3. **Invalid rows are removed before deduplication**, so NaN ids are not
   treated as duplicates of each other.
4. **DB host/port come from `.env`** (`localhost:5433` on the laptop,
   `postgres_cpd:5432` inside Docker), so the same code runs everywhere.
5. **The f-string connection URL is replaced by `sqlalchemy.URL.create`.**
   The notebook's nested quotes fail on Python < 3.12, and passwords with
   special characters would break a URL string.
6. **Compose fixes:** healthcheck intervals have units (`15s`), the Metabase
   image is pinned, and `depends_on` waits for healthy databases. DB and
   pgAdmin ports bind to `127.0.0.1` only, and an `etl` service was added.
7. **The schedule has an explicit timezone** (midnight IST; Prefect defaults to UTC).
   Orchestration uses a **self-hosted Prefect server** in Docker (no account
   needed); Prefect Cloud can be switched on with two `.env` values.
8. **Unexpected extra columns are dropped with a warning** instead of failing.
   Missing columns still fail loudly.

## Dashboard (Metabase)

Built automatically by `deploy/metabase_bootstrap.py` (re-runnable; keeps the same public link).
Four filters apply to every card: **Date** (any day, range or relative period), **Type**, **Subtype**, **Location**.

| Tab | Contents |
|---|---|
| Overview | totals, days with incidents, average per day, distinct locations, first / last incident, types, offences, monthly trend, by type |
| Daily | incidents per day, day-by-day breakdown by type (newest first), incidents per week |
| Trends | monthly incidents by type, year-over-year by month, per-year totals |
| Time patterns | by hour, by weekday, hour x weekday matrix, by day of month |
| Types & offences | type summary, top 15 offences, all offences with counts |
| Locations | top 15 locations, top 15 intersections, all locations (most common type/offence, first/last seen) |
| Incident log | every record with description (newest first) |
| Data freshness & quality | latest incident, latest source update, records by update date, publication lag, missing values, time precision |

## Run on your own system (Windows laptop)

Prerequisites: Docker Desktop (WSL 2), Python 3.12.

1. Copy `.env.example` to `.env` and fill in passwords.
2. Double-click **`RUN_ME_setup.bat`**: it starts all containers, creates `.venv`,
   installs requirements, tests the API, runs the pipeline once and checks the DB.
3. Double-click **`start_schedule.bat`** to keep the daily schedule running
   (Prefect UI with every run: http://localhost:4200).

| Service | URL |
|---|---|
| Metabase dashboard | http://localhost:3000 |
| Prefect UI | http://localhost:4200 |
| pgAdmin | http://localhost:8081 (host `postgres_cpd`, port `5432`) |

Manual equivalent:

```powershell
docker compose up -d
python -m venv .venv; .venv\Scripts\activate
pip install -r etl\requirements.txt
python etl\etl_pipeline.py --once     # one run
python etl\etl_pipeline.py            # daily schedule
```

## Run on the cloud (Azure VM)

1. Azure for Students -> create **Ubuntu Server 24.04** VM, size **B2s**.
   Inbound ports: **22** and **3000** only.
2. Either paste `deploy/cloud-init.example.yaml` (with your values) into
   *Advanced -> Custom data* for a zero-touch setup, **or** SSH in and run:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/ksinhame26-arch/crime-pipeline/main/deploy/azure_vm_setup.sh | sudo bash
   ```
3. The script installs Docker, starts every container (including the scheduled
   `etl` service), performs the first load, builds the Metabase dashboard and
   prints a **public link** (`http://<VM-IP>:3000/public/dashboard/<uuid>`) that
   opens on any PC without login.
4. Prefect UI / pgAdmin stay private; reach them with an SSH tunnel:
   `ssh -L 4200:localhost:4200 -L 8081:localhost:8081 azureuser@<VM-IP>`

## Useful commands

```bash
docker compose logs -f etl        # pipeline logs (also visible in the Prefect UI)
docker compose down               # stop (data is kept in volumes)
docker compose down -v            # stop AND delete all data
```
