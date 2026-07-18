"""
Manual, non-CI staleness check for import_data/la_lookup/Provider_data_lookup.csv's
'ltla23cd' column - the ONS/GSS local authority district code that ends up in the
published output (see ltla23cd in ofsted_ilacs_scrape.py's column_order).

Not run by either GitHub Actions workflow (gh_refresh_gpage.yml / pr_check.yml).
LA boundary changes are rare, government-order-driven events (e.g. the April 2025
Barnsley and Sheffield (Boundary Change) Order, which recoded Barnsley
E08000016->E08000038 and Sheffield E08000019->E08000039 - the change that prompted
this script) rather than something worth checking on every daily/PR run the way
validate_scrape_output.py checks scrape health. Run it manually/periodically instead:

    uv run python admin/check_la_code_currency.py

Compares against the ONS Open Geography Portal's "Local Authority Districts ...
Names and Codes in England" dataset - a flat names/codes lookup table, not a
boundaries/geometry file, so much cheaper to fetch than
import_data/geospatial/local_authority_districts_boundaries.json:
    https://geoportal.statistics.gov.uk/datasets/f89ec7d23b624375bcbb5c52bc2ece7e_0/explore

Matching is done by local_authority_ons_name, since Ofsted's own data has no ONS
code to join on. An LA name with no match in the live ONS dataset is treated as an
expected historic/defunct row (e.g. Cumbria, pre-2021 Northamptonshire, Poole - kept
in the lookup CSV deliberately so other LAs' stat_neighbours_previous references stay
resolvable) and skipped - this is NOT distinguished from a genuine name-matching miss
(e.g. an LA renamed on the ONS side in a way the CSV hasn't picked up), so a silent
skip here isn't proof nothing changed, just that nothing was flagged.

NOTE: this script's live-fetch path was written and reasoned about from ONS's
documented ArcGIS Hub open-data API conventions, but could not be executed or
verified against the real dataset from within the sandboxed environment it was
written in (that sandbox's network proxy blocks opendata.arcgis.com/
geoportal.statistics.gov.uk outright). Run it for real once (e.g. in a Codespace)
to confirm ONS_DATASET_URL and the column auto-detection below still match the
live dataset's current shape before relying on its output.
"""

import csv
import io
import sys

import requests

# ONS Open Geography Portal, "Local Authority Districts ... Names and Codes in England"
# (see the /explore URL in the module docstring above). ArcGIS Hub open-data items expose
# a CSV export at this URL shape - update this constant (and re-check the dataset id) if
# ONS republishes under a new vintage/id.
ONS_DATASET_URL = (
    "https://opendata.arcgis.com/api/v3/datasets/f89ec7d23b624375bcbb5c52bc2ece7e_0/"
    "downloads/data?format=csv&spatialRefId=4326"
)

LOOKUP_CSV_PATH = "import_data/la_lookup/Provider_data_lookup.csv"


def fetch_ons_la_codes():
    """Returns {la_name_lower: la_code} from the live ONS dataset, or None on failure."""
    try:
        response = requests.get(ONS_DATASET_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"ERROR: could not fetch the ONS dataset: {e}")
        print(f"  URL: {ONS_DATASET_URL}")
        return None

    reader = csv.DictReader(io.StringIO(response.text))
    fieldnames = reader.fieldnames or []
    name_col = next((c for c in fieldnames if c.upper().startswith("LAD") and c.upper().endswith("NM")), None)
    code_col = next((c for c in fieldnames if c.upper().startswith("LAD") and c.upper().endswith("CD")), None)
    if not name_col or not code_col:
        print(f"ERROR: couldn't find LAD name/code columns in the ONS dataset. Columns seen: {fieldnames}")
        return None

    return {
        row[name_col].strip().lower(): row[code_col].strip()
        for row in reader
        if row.get(name_col) and row.get(code_col)
    }


def load_lookup_rows():
    with open(LOOKUP_CSV_PATH, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    ons_codes = fetch_ons_la_codes()
    if ons_codes is None:
        sys.exit(1)

    rows = load_lookup_rows()
    mismatches = []
    for row in rows:
        name = (row.get("local_authority_ons_name") or "").strip()
        if not name:
            continue
        ons_code = ons_codes.get(name.lower())
        if ons_code is None:
            continue  # no live match - treated as an expected historic/defunct LA, not a failure
        csv_code = (row.get("ltla23cd") or "").strip()
        if csv_code != ons_code:
            mismatches.append((name, csv_code or "(blank)", ons_code))

    if mismatches:
        print(f"{len(mismatches)}/{len(rows)} LA(s) in {LOOKUP_CSV_PATH} have a stale/incorrect ltla23cd:")
        for name, csv_code, ons_code in mismatches:
            print(f"  {name}: csv has {csv_code}, ONS currently has {ons_code}")
        print(f"Update lad23cd/ltla23cd/ltla23_ons in {LOOKUP_CSV_PATH} for these rows.")
        sys.exit(1)

    print(f"OK: no stale ltla23cd codes found among {len(rows)} row(s) matched against the live ONS dataset.")


if __name__ == "__main__":
    main()
