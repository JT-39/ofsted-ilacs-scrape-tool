# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A proof-of-concept web scraper that rebuilds the ADCS "ILACS Summary" (Ofsted Children's Social Care inspection results for all English Local Authorities) directly from `reports.ofsted.gov.uk`, on-demand rather than waiting for the periodic ADCS publication. It's a single-script pipeline, not an application with a framework — code readability/hackability was prioritised over architecture, and the script has grown organically to handle inconsistencies in the source data.

Published output: https://data-to-insight.github.io/ofsted-ilacs-scrape-tool/

## Running the tool

```bash
./setup.sh                    # installs requirements.txt + graphviz (system dep) + VS Code python ext
# or, since this repo also has a uv-managed pyproject.toml/uv.lock:
uv sync

python ofsted_ilacs_scrape.py # runs the entire scrape -> extract -> enrich -> export pipeline
```

There is no test suite, linter, or build step in this repo — `main.py` is an unrelated uv-scaffold placeholder ("Hello from ofsted-ilacs-scrape-tool!") and is not part of the actual pipeline. Validation of changes is done by running the full script and inspecting `output.log`, the console debug output (`🔍 DEBUG:`/`📊 DEBUG:` prefixed lines), and the generated `index.html` / `.xlsx`.

**System requirement**: `tabula-py` (PDF table extraction) needs a Java runtime (`default-jre`) on PATH — this is installed explicitly in the GitHub Actions workflow and should be present in Codespaces/devcontainer images.

**Runtime**: the script takes ~1m20s with `pdf_data_capture = False` (link-list only) vs ~4m10s with `pdf_data_capture = True` (full per-PDF grade/date extraction) — see the config block at the top of `ofsted_ilacs_scrape.py`.

## Architecture / pipeline flow

Everything lives in **`ofsted_ilacs_scrape.py`**, a single ~1760-line top-to-bottom script (config → imports → function defs → sequential execution at module scope — there's no `if __name__ == "__main__"` guard or class structure). Reading it top-to-bottom is reading the pipeline:

1. **Config block (top of file, lines ~1-60)** — output filenames, folder paths (`export_data/`, `import_data/`), the `pdf_data_capture` speed/completeness toggle, inspection duration thresholds used to classify short vs. standard inspections, and the Ofsted search URL/pagination params. Change behaviour here first before touching function bodies.

2. **Scrape** (`get_soup`, `handle_pagination`) — paginates `reports.ofsted.gov.uk` search results (max 100 results/page) to collect every LA provider link.

3. **Per-provider extraction** (`process_provider_links`) — for each LA provider page, finds all published inspection PDFs, identifies "children's services inspection" reports via the link's accessible/nonvisual text (fragile: depends on Ofsted's current markup/wording), downloads the **most recent** PDF's bytes, and writes it under `export_data/inspection_reports/<urn>_<la_name>/`.

4. **PDF parsing** (`extract_inspection_data_update`, `fix_invalid_judgement_table_structure`, `fix_misalligned_judgement_table`, `extract_inspection_grade`) — this is the messiest and most change-prone part: pulls inspection dates, inspector name, framework type, and the judgement grades (overall effectiveness, impact of leaders, help & protection, in care, care leavers) out of inconsistently-formatted PDF tables via `tabula`/`PyPDF2`. Ofsted's report layout has changed over time (notably a Jan 2023 summary restructuring — `in_care_grade`/`care_leavers_grade` replace the older combined `care_and_care_leavers_grade`), so this code has version-specific branching and known per-LA extraction bugs (see README "Known Bugs" — southend-on-sea, nottingham, redcar and cleveland, knowsley, stoke-on-trent).

5. **Assemble** — results collected into `data` (list of dicts) then `ilacs_inspection_summary_df` (pandas DataFrame). This DataFrame is the pipeline's central object for the rest of the script.

6. **Enrich from flat files** (`import_csv_from_folder`, `merge_and_select_columns`, `reposition_columns`) — joins in `import_data/la_lookup/Provider_data_lookup.csv` (historic LA codes, ONS region identifiers, CMS system) keyed on `urn`. Geospatial enrichment (`read_json_to_dataframe`, `import_data/geospatial/*.json`, for choropleth/map use) exists but is **commented out / in progress** — LA boundary data doesn't cleanly map to ONS codes yet.

7. **Sentiment analysis** (`get_sentiment_and_topics`, `get_sentiment_category`, `plot_filtered_topics`, etc.) — an **on-hold/experimental enrichment**, mostly commented out of the active run. Where present in output it's Excel-only (excluded from the HTML page as not yet trustworthy). Don't rely on `textblob`/`gensim`/`nltk`/`sklearn` imports actually running — they're guarded by `try/except ModuleNotFoundError` and largely unused in the current pipeline.

8. **Export** (`save_data_update`, `save_to_html`) — writes:
   - `ofsted_csc_ilacs_overview.xlsx` at repo root (full dataset, via `xlsxwriter`, with the `local_link_to_all_inspections` column as an active hyperlink to that LA's downloaded PDFs).
   - `index.html` at repo root (a reduced `column_order` subset for the public GitHub Pages site — see the `column_order` list near the end of the script if adding/removing web-visible fields).

## Output data — what's actually in the table

One row per Local Authority (153 rows currently), keyed on `urn`, describing that LA's **most recent published** ILACS inspection. The `.xlsx` is the full table (20 columns); `index.html` shows a trimmed, presentation-formatted subset (see `column_order`, `ofsted_ilacs_scrape.py:1750`) with hyperlinked report/URN columns and title-cased text.

| Column | Source | Meaning |
|---|---|---|
| `urn` | scrape | Ofsted's unique provider reference — primary key |
| `la_code`, `region_code`, `ltla23cd` | `Provider_data_lookup.csv` (step 6) | historic LA number, ONS region code, ONS local-authority-district code |
| `stat_neighbours`, `stat_neighbour_judgement` | `Provider_data_lookup.csv` + `map_neighbour_grades` | that LA's statistical neighbour LA codes, and each neighbour's most recent overall grade — for peer comparison |
| `local_authority` | scrape (`clean_provider_name`) | normalised LA name |
| `inspection_link` | scrape | direct URL to the source PDF on `files.ofsted.gov.uk` (the underlying inspection report) |
| `overall_effectiveness_grade`, `impact_of_leaders_grade`, `help_and_protection_grade`, `in_care_grade`, `care_leavers_grade` | PDF extraction (step 4) | the ILACS judgement grades (`outstanding`/`good`/`requires improvement`/`inadequate`) — `in_care_grade`/`care_leavers_grade` replace the older pre-Jan-2023 combined `care_and_care_leavers_grade` |
| `inspection_framework` | PDF extraction | `short` or `standard`, derived from inspection duration vs. the config thresholds |
| `inspector_name` | PDF extraction | lead inspector, lower-cased/whitespace-normalised for grouping |
| `inspectors_inspections_count` | computed | how many LAs in this run that same inspector has led — a rough workload/coverage indicator, not from the PDF |
| `inspection_start_date`, `inspection_end_date` | PDF extraction | on-site inspection dates |
| `publication_date` | scrape (parsed from the PDF filename) | when Ofsted published the report |
| `local_link_to_all_inspections` | scrape | filesystem path to that LA's folder under `export_data/inspection_reports/` — an active hyperlink in the `.xlsx` only (dropped from `index.html`, since the full PDF archive isn't published to GitHub Pages) |

Sentiment/topic columns (`sentiment_score`, `sentiment_summary`, `main_inspection_topics`, `inspectors_median_sentiment_score`) exist in the code but are currently commented out of the active run (see step 7) — don't expect them in current output.

## Key external links

- **Ofsted reports search** (scrape entry point) — `https://reports.ofsted.gov.uk/` — `search_url`/`pagination_param` in the config block build the "Local Authority Children's Services" filtered search URL this script paginates.
- **Individual inspection report PDFs** — served from `https://files.ofsted.gov.uk/v1/file/<id>`; this is what `inspection_link` points to and what gets downloaded into `export_data/inspection_reports/`.
- **ADCS ILACS Outcomes Summary** (the periodic publication this project re-creates on-demand) — `https://adcs.org.uk/inspection/article/ilacs-outcomes-summary`.
- **Published output (GitHub Pages)** — https://data-to-insight.github.io/ofsted-ilacs-scrape-tool/.
- **Smart Cities Concept Model** reference (background for `sccm.yml`) — `https://www.smartcityconceptmodel.com`.

These appear as literal strings in `save_to_html`'s `intro_text`/`disclaimer_text` (`ofsted_ilacs_scrape.py:1189-1204`) and in the config block (`ofsted_ilacs_scrape.py:41`) — update both places if a source URL changes.

### Key data conventions
- **`urn`** (Ofsted's unique provider reference) is the primary join key throughout — always coerced to `int64`/numeric before merges.
- **`la_code`** is the older/historic LA number, brought in via the lookup CSV for backwards-compatible use cases.
- Local authority names are normalised through `clean_provider_name` (lowercased, council/borough/district boilerplate stripped) — apply the same cleaning if adding new name-based joins, or names won't match.
- Per-LA PDF export directories are named `<urn>_<cleaned_la_name>` under `export_data/inspection_reports/`.

### Supporting files (not part of the main pipeline)
- **`admin/generate_sccm_graph.py`** — regenerates `sccm_graph_static.svg` from `sccm.yml` (the Smart City Concept Model entity/relationship graph shown in the README) using `networkx`/`graphviz`. Run manually, not part of the scrape.
- **`sccm.yml`** — source of truth for the SCCM entities/relationships; edit this, then regenerate the SVG, if the conceptual model changes.

## CI / deployment

`.github/workflows/gh_refresh_gpage.yml` ("Daily ILACS Scrape & Deploy") is intended to run the scraper daily (`cron: '0 5 * * *'`), commit the refreshed `index.html` + `.xlsx` back to `main`, and deploy `index.html` to GitHub Pages. **Per the README, the scheduled auto-run is not currently working reliably** — the script is being run manually (via Codespaces + `./setup.sh` + running the script + push) as a workaround. If asked to fix "the daily refresh isn't happening," this workflow/schedule is the place to look, not the scrape logic itself.

Between the scrape step and the commit-back step, the workflow runs `admin/validate_scrape_output.py` — a stdlib-only sanity check (row count, required columns, file sizes) that fails the job rather than publishing an obviously broken scrape to `main`. Run it manually with `python admin/validate_scrape_output.py` after a local run if you want the same check.

Manual run instructions for non-admin users are in the README ("Script admin notes"): open a Codespace on `main`, run `./setup.sh` (`chmod +x setup.sh` first if permission denied), run `ofsted_ilacs_scrape.py`, download the refreshed `.xlsx`.

## Known limitations to keep in mind

- The Ofsted site's HTML structure and PDF report layout are moving targets outside this project's control — scrape/parse logic is inherently brittle and may need re-tuning (see the "In progress Ofsted site/search link refactoring" notes near the top of the script for a partially-started URL param refactor).
- Some LAs have PDF encoding/formatting quirks causing specific columns to fail extraction (see README "Known Bugs"); when fixing one, check whether the fix regresses the others, as several fixes have been layered defensively (`fix_invalid_judgement_table_structure`, `fix_misalligned_judgement_table`).
- Geospatial/choropleth mapping and sentiment analysis are both explicitly unfinished — don't assume commented-out code nearby is dead; it's often paused work-in-progress referenced in the README's "Future work" section.
