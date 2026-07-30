"""
Post-scrape sanity check for the CI workflow (.github/workflows/gh_refresh_gpage.yml).

Runs after ofsted_ilacs_scrape.py and before the output is committed back to
main, so a broken/partial scrape (e.g. Ofsted's site structure changed, or a
network blip cut the run short) fails the job instead of silently publishing
a near-empty summary. Deliberately stdlib-only (no pandas/openpyxl) so it
doesn't need extra dependencies installed.

As well as the structural checks (file sizes, required columns, row count),
this checks how many LAs have no real overall effectiveness grade (still
"data_unreadable"/missing after the extract_inspection_data_update crash-safety
fallback added for known-bad PDFs). A handful of these are expected - see the
README's "Known limitations" section - so:
  - > FAILURE_RATE_THRESHOLD of LAs failing extraction fails the job (a jump
    like that signals something systemic broke, not just an already-known
    per-LA quirk).
  - Any failures at all (even under the threshold) print a `::warning::`
    annotation - visible in the GitHub Actions/PR checks UI - without
    blocking the daily publish.

From ~April 2026, Ofsted stopped including an overall effectiveness judgement
in ILACS reports at all (confirmed against real post-reform reports - see
fix_misalligned_judgement_table's 'not_reported_post_reform' handling in
ofsted_ilacs_scrape.py). Those LAs are reported separately, informationally,
and never count towards the failure rate - unlike genuine extraction
failures, this is an expected, permanent, and growing state as more LAs get
re-inspected under the new framework, not a bug to alert on.

The inspection history CSV (all captured past inspections; also the incremental-scrape
cache) gets structural checks only - exists, parses, required columns, at least one row
per summary LA. Historic rows are best-effort parses of old report formats, so their
data quality is deliberately not judged (see README "Known limitations").

Run manually with: python admin/validate_scrape_output.py
"""

import csv
import os
import sys
from html.parser import HTMLParser

HTML_PATH = "index.html"
XLSX_PATH = "ofsted_csc_ilacs_overview.xlsx"
HISTORY_PATH = "ofsted_csc_ilacs_history.csv"

# The history CSV must at minimum identify each report and carry the headline grade -
# see history_columns in ofsted_ilacs_scrape.py for the full column set.
HISTORY_REQUIRED_COLUMNS = ["urn", "local_authority", "inspection_link", "overall_effectiveness_grade", "parser_version"]

MIN_ROWS = 100  # expecting ~153 LAs (see max_results in ofsted_ilacs_scrape.py); a
                # broken scrape produces far fewer
MIN_XLSX_BYTES = 10_000
MIN_HTML_BYTES = 5_000
REQUIRED_HEADERS = [
    "URN", "Local Authority", "Inspection Link", "Overall Effectiveness Grade",
]

# Fraction of LAs allowed to have no real overall effectiveness grade before this
# is treated as a hard failure rather than just the handful of already-known
# per-LA extraction quirks (see README "Known limitations"). Post-reform LAs (see below)
# are excluded from this entirely, so this threshold only ever fires for genuine
# extraction breakage.
FAILURE_RATE_THRESHOLD = 0.10

# How a "failed extraction" grade cell renders in index.html. save_to_html turns raw
# missing/unreadable values into a styled "No data" badge (this parser reads the badge's
# inner text); the raw values are kept in the set too so this script can still validate
# a page generated before the badge styling existed.
FAILED_GRADE_VALUES = {"", "no data", "nan", "data_unreadable", "none"}

# Ofsted stopped reporting this judgement from ~April 2026 - see
# fix_misalligned_judgement_table in ofsted_ilacs_scrape.py. Expected and
# permanent for affected LAs, not a failure - tracked separately below.
# Both the styled badge label and the raw sentinel are accepted (as above).
# NOTE: keep in sync with format_grade_badge in ofsted_ilacs_scrape.py's save_to_html.
POST_REFORM_GRADE_VALUES = {"not_reported_post_reform", "not reported (2026 framework)"}


class _TableParser(HTMLParser):
    """Minimal <table> header/row extractor for pandas' to_html() output."""

    def __init__(self):
        super().__init__()
        self.headers = []
        self.rows = []
        self._in_thead = False
        self._in_tbody = False
        self._current_row = None
        self._current_cell_parts = None

    def handle_starttag(self, tag, attrs):
        if tag == "thead":
            self._in_thead = True
        elif tag == "tbody":
            self._in_tbody = True
        elif tag == "th" and self._in_thead:
            self._current_cell_parts = []
        elif tag == "tr" and self._in_tbody:
            self._current_row = []
        elif tag == "td" and self._current_row is not None:
            self._current_cell_parts = []

    def handle_endtag(self, tag):
        if tag == "thead":
            self._in_thead = False
        elif tag == "tbody":
            self._in_tbody = False
        elif tag == "th" and self._current_cell_parts is not None:
            self.headers.append("".join(self._current_cell_parts).strip())
            self._current_cell_parts = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None
        elif tag == "td" and self._current_cell_parts is not None:
            self._current_row.append("".join(self._current_cell_parts).strip())
            self._current_cell_parts = None

    def handle_data(self, data):
        if self._current_cell_parts is not None:
            self._current_cell_parts.append(data)


def gh_annotation(level, message):
    """Print a GitHub Actions workflow-command annotation (visible in the
    Actions/PR checks UI). No-op outside GitHub Actions beyond a plain print."""
    print(f"::{level}::{message}")


def check_html():
    """Returns (errors, warnings, info, row_count) - row_count is 0 when the file is unusable."""
    errors = []
    warnings = []
    info = []

    if not os.path.exists(HTML_PATH):
        return [f"{HTML_PATH} was not generated"], [], [], 0

    size = os.path.getsize(HTML_PATH)
    if size < MIN_HTML_BYTES:
        return [f"{HTML_PATH} is only {size} bytes - looks empty/broken"], [], [], 0

    html = open(HTML_PATH, encoding="utf-8").read()

    for header in REQUIRED_HEADERS:
        if header not in html:
            errors.append(f"{HTML_PATH} is missing expected column '{header}'")

    parser = _TableParser()
    parser.feed(html)
    row_count = len(parser.rows)
    if row_count < MIN_ROWS:
        errors.append(f"{HTML_PATH} only has {row_count} LA rows (expected >= {MIN_ROWS})")

    # Extraction-failure-rate check - only meaningful if the columns we need are present
    if not errors and "Local Authority" in parser.headers and "Overall Effectiveness Grade" in parser.headers:
        la_idx = parser.headers.index("Local Authority")
        grade_idx = parser.headers.index("Overall Effectiveness Grade")

        failed_las = []
        post_reform_las = []
        for row in parser.rows:
            la = row[la_idx] if la_idx < len(row) else "<unknown>"
            value = row[grade_idx].strip().lower() if grade_idx < len(row) else ""
            if value in POST_REFORM_GRADE_VALUES:
                post_reform_las.append(la)
            elif value in FAILED_GRADE_VALUES:
                failed_las.append(la)

        if post_reform_las:
            info.append(
                f"{len(post_reform_las)}/{row_count} LAs have no overall effectiveness grade "
                f"because Ofsted stopped reporting one from ~April 2026 (not a failure): "
                f"{', '.join(post_reform_las)}"
            )

        if failed_las:
            failure_rate = len(failed_las) / row_count
            message = (
                f"{len(failed_las)}/{row_count} LAs ({failure_rate:.0%}) have no real "
                f"overall effectiveness grade: {', '.join(failed_las)}"
            )
            if failure_rate > FAILURE_RATE_THRESHOLD:
                errors.append(
                    f"{message} - exceeds the {FAILURE_RATE_THRESHOLD:.0%} threshold, "
                    f"which suggests something broke systemically rather than the usual "
                    f"handful of known per-LA quirks"
                )
            else:
                warnings.append(message)

    return errors, warnings, info, row_count


def check_history(summary_row_count):
    """
    Sanity-checks the inspection history CSV (the historic dataset + incremental-scrape
    cache written by ofsted_ilacs_scrape.py). Historic rows are best-effort parses of
    old report formats, so data quality isn't judged here - only that the file exists,
    is well-formed, and holds at least one row per LA in the summary (every LA's most
    recent inspection must be in the history by construction).
    """
    if not os.path.exists(HISTORY_PATH):
        return [f"{HISTORY_PATH} was not generated"]

    try:
        with open(HISTORY_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames or []
            row_count = sum(1 for _ in reader)
    except (csv.Error, UnicodeDecodeError) as e:
        return [f"{HISTORY_PATH} could not be parsed as CSV: {e}"]

    errors = []
    for column in HISTORY_REQUIRED_COLUMNS:
        if column not in columns:
            errors.append(f"{HISTORY_PATH} is missing expected column '{column}'")

    if summary_row_count and row_count < summary_row_count:
        errors.append(
            f"{HISTORY_PATH} only has {row_count} rows but the summary has {summary_row_count} LAs - "
            f"the history should contain at least each LA's most recent inspection"
        )

    return errors


def check_xlsx():
    if not os.path.exists(XLSX_PATH):
        return [f"{XLSX_PATH} was not generated"]

    size = os.path.getsize(XLSX_PATH)
    if size < MIN_XLSX_BYTES:
        return [f"{XLSX_PATH} is only {size} bytes - looks empty/broken"]

    return []


def main():
    html_errors, html_warnings, html_info, summary_row_count = check_html()
    errors = html_errors + check_xlsx() + check_history(summary_row_count)

    for message in html_info:
        print(f"INFO: {message}")

    for warning in html_warnings:
        gh_annotation("warning", warning)
        print(f"WARNING: {warning}")

    if errors:
        for error in errors:
            gh_annotation("error", error)
        print("Scrape output failed sanity checks:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)

    print(
        f"Scrape output looks sane: {HTML_PATH} ({os.path.getsize(HTML_PATH)} bytes), "
        f"{XLSX_PATH} ({os.path.getsize(XLSX_PATH)} bytes), "
        f"{HISTORY_PATH} ({os.path.getsize(HISTORY_PATH)} bytes)."
    )


if __name__ == "__main__":
    main()
