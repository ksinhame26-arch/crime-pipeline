"""metabase_bootstrap.py - configure Metabase automatically (no clicking).

Creates the admin user, connects the cpd_db PostgreSQL database, (re)builds the
"Cambridge Crime Trends" dashboard and creates a PUBLIC sharing link.

The dashboard shows everything the cpd_incidents data supports (profiled on the
real data, Oct 2026): 8 tabs - Overview, Daily, Trends, Time patterns,
Types & offences, Locations, Incident log, Data freshness & quality - and four
filters (Date, Type, Subtype, Location) that apply to every card.

Re-running is safe: an existing dashboard with the same name is rebuilt in place,
so its id and public link stay the same.

Reads settings from ../.env.  Usage:
    python3 deploy/metabase_bootstrap.py [--url http://localhost:3000] [--public-base http://IP:3000]
Writes the public link to PUBLIC_DASHBOARD_LINK.txt in the project folder.
Standard library only.
"""
import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH_NAME = "Cambridge Crime Trends"
F = "{{date}} AND {{type}} AND {{subtype}} AND {{location}}"   # all four filters (empty = no filter)
TYPES = ["INCIDENT", "ARREST", "TRAFFIC", "SP", "ASSIST", "USE", "INVESTIGATIONS"]  # observed in the data


def type_cols():
    cols = ", ".join(f"COUNT(*) FILTER (WHERE type = '{t}') AS \"{t.lower()}\"" for t in TYPES)
    known = ", ".join(f"'{t}'" for t in TYPES)
    return cols + f", COUNT(*) FILTER (WHERE type NOT IN ({known})) AS other"


WEEKDAY_MATRIX = "SELECT hour, " + ", ".join(
    f"COUNT(*) FILTER (WHERE EXTRACT(ISODOW FROM date_time) = {i}) AS \"{d}\""
    for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], start=1)
) + f", COUNT(*) AS total FROM cpd_incidents WHERE {F} GROUP BY hour ORDER BY hour"

LAG = "EXTRACT(EPOCH FROM (last_updated - date_time)) / 86400.0"

# (tab, name, display, sql, x-col(s), y-col, width, height, extra viz settings)
TEXT = "text"
CARDS = [
    # ---------------- Overview ----------------
    ("Overview", TEXT, "text", "**Cambridge (MA) Police Department - Daily Police Log**, loaded by the PAI-102 ETL pipeline "
     "(Socrata API -> Prefect -> PostgreSQL). Every card responds to the **Date, Type, Subtype and Location** filters above. "
     "Note: the police publish incidents with a delay (see *Data freshness & quality*), so the most recent days are usually empty.", None, None, 24, 2, None),
    ("Overview", "Total incidents", "scalar", f"SELECT COUNT(*) AS incidents FROM cpd_incidents WHERE {F}", None, None, 6, 3, None),
    ("Overview", "Days with incidents", "scalar", f"SELECT COUNT(DISTINCT date_time::date) AS days FROM cpd_incidents WHERE {F}", None, None, 6, 3, None),
    ("Overview", "Average incidents per day", "scalar",
     f"SELECT ROUND(COUNT(*)::numeric / NULLIF(COUNT(DISTINCT date_time::date), 0), 1) AS per_day FROM cpd_incidents WHERE {F}", None, None, 6, 3, None),
    ("Overview", "Distinct locations", "scalar", f"SELECT COUNT(DISTINCT location) AS locations FROM cpd_incidents WHERE {F}", None, None, 6, 3, None),
    ("Overview", "Date range covered", "table",
     f"SELECT MIN(date_time) AS first_incident, MAX(date_time) AS last_incident, COUNT(DISTINCT type) AS types, COUNT(DISTINCT subtype) AS subtypes FROM cpd_incidents WHERE {F}",
     None, None, 24, 2, None),
    ("Overview", "Incidents per month", "line",
     f"SELECT DATE_TRUNC('month', date_time)::date AS month, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY 1 ORDER BY 1",
     "month", "incidents", 16, 6, None),
    ("Overview", "Incidents by type", "row",
     f"SELECT type, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY type ORDER BY incidents DESC", "type", "incidents", 8, 6, None),

    # ---------------- Daily ----------------
    ("Daily", TEXT, "text", "**Day-by-day view.** Use the *Date* filter (e.g. *Previous 7 days*, a single date, or a range) to see any day separately.", None, None, 24, 1, None),
    ("Daily", "Incidents per day", "bar",
     f"SELECT date_time::date AS day, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY 1 ORDER BY 1", "day", "incidents", 24, 6, None),
    ("Daily", "Daily breakdown by type (newest first)", "table",
     f"SELECT date_time::date AS day, TO_CHAR(date_time::date, 'Dy') AS weekday, COUNT(*) AS incidents, {type_cols()} "
     f"FROM cpd_incidents WHERE {F} GROUP BY 1, 2 ORDER BY 1 DESC", None, None, 24, 8, None),
    ("Daily", "Incidents per week", "bar",
     f"SELECT DATE_TRUNC('week', date_time)::date AS week_start, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY 1 ORDER BY 1",
     "week_start", "incidents", 24, 6, None),

    # ---------------- Trends ----------------
    ("Trends", "Monthly incidents by type", "line",
     f"SELECT DATE_TRUNC('month', date_time)::date AS month, type, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY 1, 2 ORDER BY 1",
     ["month", "type"], "incidents", 24, 7, None),
    ("Trends", "Year-over-year by month", "line",
     f"SELECT EXTRACT(MONTH FROM date_time)::int AS month_no, year::text AS year, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY 1, 2 ORDER BY 1",
     ["month_no", "year"], "incidents", 16, 6, None),
    ("Trends", "Incidents per year", "bar",
     f"SELECT year::text AS year, COUNT(*) AS incidents, COUNT(DISTINCT date_time::date) AS days, ROUND(COUNT(*)::numeric / COUNT(DISTINCT date_time::date), 1) AS per_day "
     f"FROM cpd_incidents WHERE {F} GROUP BY 1 ORDER BY 1", "year", "incidents", 8, 6, None),

    # ---------------- Time patterns ----------------
    ("Time patterns", "Incidents by hour of day", "bar",
     f"SELECT hour, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY hour ORDER BY hour", "hour", "incidents", 12, 6, None),
    ("Time patterns", "Incidents by day of week", "bar",
     f"SELECT EXTRACT(ISODOW FROM date_time)::int AS dow_no, TO_CHAR(date_time, 'Dy') AS day, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY 1, 2 ORDER BY 1",
     "day", "incidents", 12, 6, None),
    ("Time patterns", "Hour x weekday matrix", "table", WEEKDAY_MATRIX, None, None, 16, 9,
     {"table.column_formatting": [{"columns": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "type": "range",
                                   "colors": ["white", "#509EE3"], "min_type": None, "max_type": None, "operator": "=",
                                   "value": "", "color": "#509EE3", "highlight_row": False}]}),
    ("Time patterns", "Incidents by day of month", "bar",
     f"SELECT day AS day_of_month, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY day ORDER BY day",
     "day_of_month", "incidents", 8, 9, None),

    # ---------------- Types & offences ----------------
    ("Types & offences", "Type summary", "table",
     f"SELECT type, COUNT(*) AS incidents, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total, COUNT(DISTINCT subtype) AS subtypes, "
     f"MIN(date_time)::date AS first_seen, MAX(date_time)::date AS last_seen FROM cpd_incidents WHERE {F} GROUP BY type ORDER BY incidents DESC",
     None, None, 24, 4, None),
    ("Types & offences", "Top 20 offences (subtype)", "row",
     f"SELECT COALESCE(subtype, '(missing)') AS subtype, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY 1 ORDER BY incidents DESC LIMIT 20",
     "subtype", "incidents", 24, 9, None),
    ("Types & offences", "All offences (subtype) with counts", "table",
     f"SELECT type, COALESCE(subtype, '(missing)') AS subtype, COUNT(*) AS incidents, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total, "
     f"MIN(date_time)::date AS first_seen, MAX(date_time)::date AS last_seen FROM cpd_incidents WHERE {F} GROUP BY 1, 2 ORDER BY incidents DESC",
     None, None, 24, 9, None),

    # ---------------- Locations ----------------
    ("Locations", "Top 20 locations", "row",
     f"SELECT location, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} GROUP BY location ORDER BY incidents DESC LIMIT 20",
     "location", "incidents", 12, 9, None),
    ("Locations", "Top 15 intersections (location contains &)", "row",
     f"SELECT location, COUNT(*) AS incidents FROM cpd_incidents WHERE {F} AND location LIKE '%&%' GROUP BY location ORDER BY incidents DESC LIMIT 15",
     "location", "incidents", 12, 9, None),
    ("Locations", "All locations", "table",
     f"SELECT location, COUNT(*) AS incidents, MODE() WITHIN GROUP (ORDER BY type) AS most_common_type, "
     f"MODE() WITHIN GROUP (ORDER BY subtype) AS most_common_offence, MIN(date_time)::date AS first_seen, MAX(date_time)::date AS last_seen "
     f"FROM cpd_incidents WHERE {F} GROUP BY location ORDER BY incidents DESC", None, None, 24, 9, None),

    # ---------------- Incident log ----------------
    ("Incident log", "Incident log (every record, newest first)", "table",
     f"SELECT date_time, id, type, subtype, location, description, last_updated FROM cpd_incidents WHERE {F} ORDER BY date_time DESC",
     None, None, 24, 14, None),

    # ---------------- Data freshness & quality ----------------
    ("Data freshness & quality", TEXT, "text",
     "`last_updated` is when the police published or last updated a record. Records reach the source **days after** the incident, "
     "so this tab shows how fresh the data is and when records arrived.", None, None, 24, 2, None),
    ("Data freshness & quality", "Latest incident in the data", "scalar", "SELECT MAX(date_time) AS latest_incident FROM cpd_incidents", None, None, 8, 3, None),
    ("Data freshness & quality", "Latest source update", "scalar", "SELECT MAX(last_updated) AS latest_update FROM cpd_incidents", None, None, 8, 3, None),
    ("Data freshness & quality", "Median publication lag (days)", "scalar",
     f"SELECT ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {LAG})::numeric, 1) AS median_lag_days FROM cpd_incidents WHERE {F}", None, None, 8, 3, None),
    ("Data freshness & quality", "Records by source update date (when data arrived)", "bar",
     f"SELECT last_updated::date AS update_date, COUNT(*) AS records FROM cpd_incidents WHERE {F} GROUP BY 1 ORDER BY 1",
     "update_date", "records", 24, 6, None),
    ("Data freshness & quality", "Publication lag (days from incident to last update)", "bar",
     f"SELECT CASE WHEN {LAG} < 2 THEN '0-1' WHEN {LAG} < 4 THEN '2-3' WHEN {LAG} < 8 THEN '4-7' WHEN {LAG} < 15 THEN '8-14' "
     f"WHEN {LAG} < 31 THEN '15-30' WHEN {LAG} < 61 THEN '31-60' ELSE '61+' END AS lag_days, "
     f"MIN({LAG}) AS sort_key, COUNT(*) AS records FROM cpd_incidents WHERE {F} GROUP BY 1 ORDER BY sort_key",
     "lag_days", "records", 12, 6, None),
    ("Data freshness & quality", "Publication lag by type", "table",
     f"SELECT type, COUNT(*) AS records, ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {LAG})::numeric, 1) AS median_lag_days, "
     f"ROUND(MAX({LAG})::numeric, 1) AS max_lag_days FROM cpd_incidents WHERE {F} GROUP BY type ORDER BY records DESC",
     None, None, 12, 6, None),
    ("Data freshness & quality", "Missing values per column", "table",
     "SELECT 'date_time' AS column_name, COUNT(*) - COUNT(date_time) AS missing FROM cpd_incidents UNION ALL "
     "SELECT 'type', COUNT(*) - COUNT(type) FROM cpd_incidents UNION ALL SELECT 'subtype', COUNT(*) - COUNT(subtype) FROM cpd_incidents UNION ALL "
     "SELECT 'location', COUNT(*) - COUNT(location) FROM cpd_incidents UNION ALL SELECT 'description', COUNT(*) - COUNT(description) FROM cpd_incidents UNION ALL "
     "SELECT 'last_updated', COUNT(*) - COUNT(last_updated) FROM cpd_incidents", None, None, 8, 6, None),
    ("Data freshness & quality", "Time precision: minute of the hour", "bar",
     f"SELECT minute, COUNT(*) AS records FROM cpd_incidents WHERE {F} GROUP BY minute ORDER BY minute", "minute", "records", 10, 6, None),
    ("Data freshness & quality", "Records with non-zero seconds", "scalar",
     "SELECT COUNT(*) FILTER (WHERE second <> 0) AS non_zero_seconds FROM cpd_incidents", None, None, 6, 6, None),
]

TABS = ["Overview", "Daily", "Trends", "Time patterns", "Types & offences", "Locations", "Incident log", "Data freshness & quality"]
PARAMS = [  # (slug, display name, dashboard param type, column, widget type)
    ("date", "Date", "date/all-options", "date_time", "date/all-options"),
    ("type", "Type", "string/=", "type", "string/="),
    ("subtype", "Subtype", "string/=", "subtype", "string/="),
    ("location", "Location", "string/=", "location", "string/="),
]


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
        self.session = None

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.session:
            req.add_header("X-Metabase-Session", self.session)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                txt = r.read().decode()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:400]}")
        return json.loads(txt) if txt.strip().startswith(("{", "[")) else txt


def template_tags(sql, field_ids):
    tags = {}
    for slug, display, _ptype, col, widget in PARAMS:
        if "{{" + slug + "}}" in sql:
            tags[slug] = {"id": str(uuid.uuid4()), "name": slug, "display-name": display, "type": "dimension",
                          "dimension": ["field", field_ids[col], None], "widget-type": widget}
    return tags


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
    db = next((d for d in dbs if (d.get("details") or {}).get("dbname") == "cpd_db"), None)
    if not db:
        print("Connecting cpd_db...")
        db = mb.call("POST", "/api/database", {
            "engine": "postgres", "name": "Cambridge Crime DB", "is_full_sync": True,
            "details": {"host": "postgres_cpd", "port": 5432, "dbname": "cpd_db",
                        "user": env["POSTGRES_USER"], "password": env["POSTGRES_PASSWORD"], "ssl": False}})
    db_id = db["id"]

    print("Waiting for table metadata (cpd_incidents)...")
    field_ids = {}
    for i in range(60):
        meta = mb.call("GET", f"/api/database/{db_id}/metadata")
        table = next((t for t in meta.get("tables", []) if t["name"] == "cpd_incidents"), None)
        if table:
            field_ids = {f["name"]: f["id"] for f in table.get("fields", [])}
            if all(p[3] in field_ids for p in PARAMS):
                break
        if i % 6 == 0:
            mb.call("POST", f"/api/database/{db_id}/sync_schema")
        time.sleep(5)
    missing = [p[3] for p in PARAMS if p[3] not in field_ids]
    if missing:
        raise RuntimeError(f"Metabase has not synced columns {missing} yet - run the script again in a minute")

    dashes = mb.call("GET", "/api/dashboard/")
    dash = next((d for d in dashes if d["name"] == DASH_NAME and not d.get("archived")), None)
    if dash:
        print(f"Rebuilding existing dashboard {dash['id']} (public link is kept)...")
        old = mb.call("GET", f"/api/dashboard/{dash['id']}")
        old_cards = [dc["card_id"] for dc in old.get("dashcards", []) if dc.get("card_id")]
    else:
        print("Creating dashboard...")
        dash = mb.call("POST", "/api/dashboard", {"name": DASH_NAME})
        old_cards = []

    parameters = [{"id": f"p_{slug}", "name": name, "slug": slug, "type": ptype,
                   "sectionId": "date" if ptype.startswith("date") else "string"}
                  for slug, name, ptype, _c, _w in PARAMS]
    tab_ids = {name: -(i + 1) for i, name in enumerate(TABS)}
    next_row = {name: 0 for name in TABS}
    next_col = {name: 0 for name in TABS}
    row_height = {name: 0 for name in TABS}
    dashcards = []
    for n, (tab, name, display, sql, x, y, w, h, extra) in enumerate(CARDS):
        if next_col[tab] + w > 24:  # wrap to a new row
            next_row[tab] += row_height[tab]
            next_col[tab], row_height[tab] = 0, 0
        pos = {"col": next_col[tab], "row": next_row[tab], "size_x": w, "size_y": h}
        next_col[tab] += w
        row_height[tab] = max(row_height[tab], h)
        dc = {"id": -(n + 1), "dashboard_tab_id": tab_ids[tab], "parameter_mappings": [], **pos}
        if name == TEXT:
            dc.update({"card_id": None, "visualization_settings": {
                "virtual_card": {"name": None, "display": "text", "visualization_settings": {}, "dataset_query": {}, "archived": False},
                "text": display_text(display, sql)}})
        else:
            viz = {}
            if x:
                viz = {"graph.dimensions": x if isinstance(x, list) else [x], "graph.metrics": [y]}
            if extra:
                viz.update(extra)
            tags = template_tags(sql, field_ids)
            card = mb.call("POST", "/api/card", {
                "name": name, "display": display, "visualization_settings": viz, "collection_id": None,
                "dataset_query": {"database": db_id, "type": "native", "native": {"query": sql, "template-tags": tags}}})
            dc.update({"card_id": card["id"], "visualization_settings": {}, "parameter_mappings": [
                {"parameter_id": f"p_{slug}", "card_id": card["id"], "target": ["dimension", ["template-tag", slug]]}
                for slug in tags]})
        dashcards.append(dc)

    mb.call("PUT", f"/api/dashboard/{dash['id']}", {
        "description": "Cambridge (MA) Police Daily Log loaded daily by the PAI-102 ETL pipeline. Filters: Date, Type, Subtype, Location.",
        "parameters": parameters,
        "tabs": [{"id": tab_ids[t], "name": t} for t in TABS],
        "dashcards": dashcards})
    for cid in old_cards:  # previous version's cards are no longer on the dashboard
        try:
            mb.call("PUT", f"/api/card/{cid}", {"archived": True})
        except RuntimeError as e:
            print("  could not archive old card", cid, e)
    print(f"Dashboard {dash['id']}: {len(TABS)} tabs, {sum(1 for c in CARDS if c[1] != TEXT)} cards, {len(PARAMS)} filters")

    print("Enabling public sharing...")
    mb.call("PUT", "/api/setting/enable-public-sharing", {"value": True})
    pub = mb.call("GET", f"/api/dashboard/{dash['id']}").get("public_uuid")
    if not pub:
        pub = mb.call("POST", f"/api/dashboard/{dash['id']}/public_link")["uuid"]
    base = (args.public_base or args.url).rstrip("/")
    link = f"{base}/public/dashboard/{pub}"
    (ROOT / "PUBLIC_DASHBOARD_LINK.txt").write_text(link + "\n", encoding="utf-8")
    print("PUBLIC DASHBOARD LINK:", link)


def display_text(display, sql):
    """Text cards store their markdown in the 'sql' slot of the CARDS tuple."""
    return sql if display == "text" else ""


if __name__ == "__main__":
    main()
