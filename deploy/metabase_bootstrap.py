"""metabase_bootstrap.py - configure a fresh Metabase automatically (no clicking).

Creates the admin user, connects the cpd_db PostgreSQL database, builds the
"Cambridge Crime Trends" dashboard (9 cards) and creates a PUBLIC sharing link,
so the dashboard can be opened from any PC without logging in.

Reads settings from ../.env.  Usage:  python3 deploy/metabase_bootstrap.py [--url http://localhost:3000]
Writes the public link to PUBLIC_DASHBOARD_LINK.txt in the project folder.
Standard library only, safe to re-run (skips steps already done).
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CARDS = [  # (name, SQL, display, x-axis column, y-axis column)
    ("Total incidents", "SELECT COUNT(*) AS total_incidents FROM cpd_incidents", "scalar", None, None),
    ("Incidents in last 30 days of data", "SELECT COUNT(*) AS last_30_days FROM cpd_incidents WHERE date_time >= (SELECT MAX(date_time) FROM cpd_incidents) - INTERVAL '30 days'", "scalar", None, None),
    ("Distinct locations", "SELECT COUNT(DISTINCT location) AS locations FROM cpd_incidents", "scalar", None, None),
    ("Incidents per month", "SELECT DATE_TRUNC('month', date_time)::date AS month, COUNT(*) AS incidents FROM cpd_incidents GROUP BY 1 ORDER BY 1", "line", "month", "incidents"),
    ("Incidents by hour of day", "SELECT hour, COUNT(*) AS incidents FROM cpd_incidents GROUP BY hour ORDER BY hour", "bar", "hour", "incidents"),
    ("Incidents by type", "SELECT type, COUNT(*) AS incidents FROM cpd_incidents GROUP BY type ORDER BY incidents DESC", "row", "type", "incidents"),
    ("Top 10 locations", "SELECT location, COUNT(*) AS incidents FROM cpd_incidents GROUP BY location ORDER BY incidents DESC LIMIT 10", "row", "location", "incidents"),
    ("Top 10 offences (subtype)", "SELECT COALESCE(subtype,'(none)') AS subtype, COUNT(*) AS incidents FROM cpd_incidents GROUP BY 1 ORDER BY incidents DESC LIMIT 10", "row", "subtype", "incidents"),
    ("Incidents by day of week", "SELECT TO_CHAR(date_time,'ID')::int AS dow_no, TO_CHAR(date_time,'Dy') AS day, COUNT(*) AS incidents FROM cpd_incidents GROUP BY 1,2 ORDER BY 1", "bar", "day", "incidents"),
]
LAYOUT = [(0, 0, 8, 3), (8, 0, 8, 3), (16, 0, 8, 3), (0, 3, 24, 6), (0, 9, 12, 6),
          (12, 9, 12, 6), (0, 15, 12, 7), (12, 15, 12, 7), (0, 22, 24, 6)]
DASH_NAME = "Cambridge Crime Trends"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


class MB:
    def __init__(self, url):
        self.url = url.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        self.session = None

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.session:
            req.add_header("X-Metabase-Session", self.session)
        try:
            with self.opener.open(req, timeout=120) as r:
                txt = r.read().decode()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}")
        return json.loads(txt) if txt.strip().startswith(("{", "[")) else txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3000")
    ap.add_argument("--public-base", default=None, help="base URL used in the printed public link")
    args = ap.parse_args()
    env = load_env()
    mb = MB(args.url)

    print("Waiting for Metabase...")
    for _ in range(120):
        try:
            if mb.call("GET", "/api/health").get("status") == "ok":
                break
        except Exception:
            pass
        time.sleep(5)

    email, password = env["METABASE_ADMIN_EMAIL"], env["METABASE_ADMIN_PASSWORD"]
    token = mb.call("GET", "/api/session/properties").get("setup-token")
    if token:
        print("Creating admin user...")
        mb.call("POST", "/api/setup", {
            "token": token,
            "user": {"email": email, "password": password, "password_confirm": password,
                     "first_name": "Crime Pipeline", "last_name": "Admin", "site_name": "Crime Trends Pipeline"},
            "prefs": {"site_name": "Crime Trends Pipeline", "site_locale": "en", "allow_tracking": False},
        })
    mb.session = mb.call("POST", "/api/session", {"username": email, "password": password})["id"]

    dbs = mb.call("GET", "/api/database")
    dbs = dbs.get("data", dbs) if isinstance(dbs, dict) else dbs
    db = next((d for d in dbs if d.get("details", {}).get("dbname") == "cpd_db"), None)
    if not db:
        print("Connecting cpd_db...")
        db = mb.call("POST", "/api/database", {
            "engine": "postgres", "name": "Cambridge Crime DB", "is_full_sync": True,
            "details": {"host": "postgres_cpd", "port": 5432, "dbname": "cpd_db",
                        "user": env["POSTGRES_USER"], "password": env["POSTGRES_PASSWORD"], "ssl": False}})
    db_id = db["id"]

    dashes = mb.call("GET", "/api/dashboard/")
    dash = next((d for d in dashes if d["name"] == DASH_NAME), None)
    if not dash:
        print("Building dashboard...")
        card_ids = []
        for name, sql, display, x, y in CARDS:
            viz = {"graph.dimensions": [x], "graph.metrics": [y]} if x else {}
            c = mb.call("POST", "/api/card", {"name": name, "display": display, "visualization_settings": viz,
                                              "dataset_query": {"database": db_id, "type": "native", "native": {"query": sql}}})
            card_ids.append(c["id"])
        dash = mb.call("POST", "/api/dashboard", {"name": DASH_NAME,
                       "description": "Live dashboard on cpd_db.cpd_incidents, refreshed daily by the Prefect ETL pipeline (PAI-102)."})
        dashcards = [{"id": -(i + 1), "card_id": cid, "col": c, "row": r, "size_x": w, "size_y": h,
                      "parameter_mappings": [], "visualization_settings": {}}
                     for i, (cid, (c, r, w, h)) in enumerate(zip(card_ids, LAYOUT))]
        mb.call("PUT", f"/api/dashboard/{dash['id']}", {"dashcards": dashcards})

    print("Enabling public sharing...")
    mb.call("PUT", "/api/setting/enable-public-sharing", {"value": True})
    uuid = mb.call("GET", f"/api/dashboard/{dash['id']}").get("public_uuid")
    if not uuid:
        uuid = mb.call("POST", f"/api/dashboard/{dash['id']}/public_link")["uuid"]
    base = (args.public_base or args.url).rstrip("/")
    link = f"{base}/public/dashboard/{uuid}"
    (ROOT / "PUBLIC_DASHBOARD_LINK.txt").write_text(link + "\n", encoding="utf-8")
    print("PUBLIC DASHBOARD LINK:", link)


if __name__ == "__main__":
    main()
