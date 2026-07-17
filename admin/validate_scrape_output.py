"""
Post-scrape sanity check for the CI workflow (.github/workflows/gh_refresh_gpage.yml).

Runs after ofsted_ilacs_scrape.py and before the output is committed back to
main, so a broken/partial scrape (e.g. Ofsted's site structure changed, or a
network blip cut the run short) fails the job instead of silently publishing
a near-empty summary. Deliberately stdlib-only (no pandas/openpyxl) so it
doesn't need extra dependencies installed.

Run manually with: python admin/validate_scrape_output.py
"""

import os
import re
import sys

HTML_PATH = "index.html"
XLSX_PATH = "ofsted_csc_ilacs_overview.xlsx"

MIN_ROWS = 100  # expecting ~153 LAs (see max_results in ofsted_ilacs_scrape.py); a
                # broken scrape produces far fewer
MIN_XLSX_BYTES = 10_000
MIN_HTML_BYTES = 5_000
REQUIRED_HEADERS = [
    "URN", "Local Authority", "Inspection Link", "Overall Effectiveness Grade",
]


def check_html():
    errors = []

    if not os.path.exists(HTML_PATH):
        return [f"{HTML_PATH} was not generated"]

    size = os.path.getsize(HTML_PATH)
    if size < MIN_HTML_BYTES:
        return [f"{HTML_PATH} is only {size} bytes - looks empty/broken"]

    html = open(HTML_PATH, encoding="utf-8").read()

    for header in REQUIRED_HEADERS:
        if header not in html:
            errors.append(f"{HTML_PATH} is missing expected column '{header}'")

    tbody_match = re.search(r"<tbody>(.*?)</tbody>", html, re.DOTALL)
    row_count = len(re.findall(r"<tr", tbody_match.group(1))) if tbody_match else 0
    if row_count < MIN_ROWS:
        errors.append(f"{HTML_PATH} only has {row_count} LA rows (expected >= {MIN_ROWS})")

    return errors


def check_xlsx():
    if not os.path.exists(XLSX_PATH):
        return [f"{XLSX_PATH} was not generated"]

    size = os.path.getsize(XLSX_PATH)
    if size < MIN_XLSX_BYTES:
        return [f"{XLSX_PATH} is only {size} bytes - looks empty/broken"]

    return []


def main():
    errors = check_html() + check_xlsx()

    if errors:
        print("Scrape output failed sanity checks:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)

    print(
        f"Scrape output looks sane: {HTML_PATH} ({os.path.getsize(HTML_PATH)} bytes), "
        f"{XLSX_PATH} ({os.path.getsize(XLSX_PATH)} bytes)."
    )


if __name__ == "__main__":
    main()
