# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A proof-of-concept web scraper that rebuilds the ADCS "ILACS Summary" (Ofsted Children's Social Care inspection results for all English Local Authorities) directly from `reports.ofsted.gov.uk`, on-demand rather than waiting for the periodic ADCS publication. It's a single-script pipeline, not an application with a framework — code readability/hackability was prioritised over architecture, and the script has grown organically to handle inconsistencies in the source data.

Published output: https://data-to-insight.github.io/ofsted-ilacs-scrape-tool/

## Running the tool

`pyproject.toml`/`uv.lock` is the single source of truth for Python dependencies (there is no separate `requirements.txt` to keep in sync).

```bash
./setup.sh                    # uv sync + graphviz (system dep) + VS Code python ext
# or directly:
uv sync

uv run python ofsted_ilacs_scrape.py # runs the entire scrape -> extract -> enrich -> export pipeline
```

There is no test suite, linter, or build step in this repo — `main.py` is an unrelated uv-scaffold placeholder ("Hello from ofsted-ilacs-scrape-tool!") and is not part of the actual pipeline. Validation of changes is done by running the full script and inspecting `output.log`, the console debug output (`🔍 DEBUG:`/`📊 DEBUG:` prefixed lines), and the generated `index.html` / `.xlsx`.

**System requirement**: `tabula-py` (PDF table extraction) needs a Java runtime (`default-jre`) on PATH — this is installed explicitly in the GitHub Actions workflow and should be present in Codespaces/devcontainer images.

**Runtime**: the script takes ~4m10s for a full run (every LA's most recent PDF is downloaded and parsed for grades/dates). There used to be a `pdf_data_capture` config flag for a faster link-list-only mode, but it was removed — it produced a DataFrame missing columns (`inspector_name`, the grade columns) that the rest of the pipeline (steps 5-8 below) unconditionally assumed existed, so it crashed rather than actually working, and nothing wired it up as a real option (no CLI flag/env var, just a hardcoded constant). If a faster local dev loop is needed again, prefer capping `max_results` (process fewer LAs through the *same* full pipeline) over skipping PDF parsing.

## Architecture / pipeline flow

Everything lives in **`ofsted_ilacs_scrape.py`**, a single ~1510-line top-to-bottom script (config → imports → function defs → sequential execution at module scope — there's no `if __name__ == "__main__"` guard or class structure). Reading it top-to-bottom is reading the pipeline:

1. **Config block (top of file, lines ~1-50)** — output filenames, folder paths (`export_data/`, `import_data/`), inspection duration thresholds used to classify short vs. standard inspections, and the Ofsted search URL/pagination params. Change behaviour here first before touching function bodies.

2. **Scrape** (`get_soup`, `handle_pagination`) — paginates `reports.ofsted.gov.uk` search results (max 100 results/page) to collect every LA provider link.

3. **Per-provider extraction** (`process_provider_links`) — for each LA provider page, finds all published inspection PDFs, identifies "children's services inspection" reports via the link's accessible/nonvisual text (fragile: depends on Ofsted's current markup/wording), downloads the **most recent** PDF's bytes, and writes it under `export_data/inspection_reports/<urn>_<la_name>/`. The call into PDF parsing (step 4) is wrapped in `try/except` — if extraction throws for one LA's PDF, that LA gets logged (`logging.error`, with URN/name/filename) and placeholder `"data_unreadable"` values instead of aborting the whole run.

4. **PDF parsing** (`extract_inspection_data_update`, `fix_invalid_judgement_table_structure`, `fix_misalligned_judgement_table`) — this is the messiest and most change-prone part: pulls inspection dates, inspector name, framework type, and the judgement grades (overall effectiveness, impact of leaders, help & protection, in care, care leavers) out of inconsistently-formatted PDF tables via `tabula`/`PyPDF2`. Ofsted's report layout has changed over time (notably a Jan 2023 summary restructuring — `in_care_grade`/`care_leavers_grade` replace the older combined `care_and_care_leavers_grade`), so this code has version-specific branching and known per-LA extraction bugs (see README "Known Bugs" — southend-on-sea, nottingham, redcar and cleveland, knowsley, stoke-on-trent). If `tabula` finds no table at all, or a report yields fewer grade rows than expected, this degrades to placeholder `"data_unreadable"`/`NaN` values (logged via `logging.warning`) rather than raising — see the `known_judgements`-based placeholder pattern shared across these functions.

5. **Assemble** — results collected into `data` (list of dicts) then `ilacs_inspection_summary_df` (pandas DataFrame). This DataFrame is the pipeline's central object for the rest of the script.

6. **Enrich from flat files** (`import_csv_from_folder`, `merge_and_select_columns`, `reposition_columns`) — joins in `import_data/la_lookup/Provider_data_lookup.csv` (historic LA codes, ONS region identifiers, CMS system) keyed on `urn`. `merge_and_select_columns` left-joins by default and logs (`logging.warning`) any `urn`s with no lookup match, rather than silently dropping them. Geospatial enrichment (`read_json_to_dataframe`, `import_data/geospatial/*.json`, for choropleth/map use) exists but is **commented out / in progress** — LA boundary data doesn't cleanly map to ONS codes yet.

7. **Sentiment analysis** — not part of the active pipeline at all. The functions (`get_sentiment_and_topics`, `get_sentiment_category`, `plot_filtered_topics`, etc.) live in **`admin/sentiment_experiment.py`**, moved out of the main script since they were dead code there (unreachable — every call site was commented out — and would `NameError` on `textblob`/`nltk`/`gensim`, none of which are installed). Kept as reference material for the README's "Future work" section, not imported or run by anything.

8. **Export** (`save_data_update`, `save_to_html`) — writes:
   - `ofsted_csc_ilacs_overview.xlsx` at repo root (full dataset, via `xlsxwriter`, with the `local_link_to_all_inspections` column as an active hyperlink to that LA's downloaded PDFs).
   - `index.html` at repo root (a reduced `column_order` subset for the public GitHub Pages site — see the `column_order` list near the end of the script if adding/removing web-visible fields).

## Output data — what's actually in the table

One row per Local Authority (153 rows currently), keyed on `urn`, describing that LA's **most recent published** ILACS inspection. The `.xlsx` is the full table (20 columns); `index.html` shows a trimmed, presentation-formatted subset (see `column_order`, `ofsted_ilacs_scrape.py:1499`) with hyperlinked report/URN columns and title-cased text.

| Column | Source | Meaning |
|---|---|---|
| `urn` | scrape | Ofsted's unique provider reference — primary key |
| `la_code`, `region_code`, `la_code_new` | `Provider_data_lookup.csv` (step 6) | historic LA number, ONS region code, current ONS/GSS local authority code |
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

Sentiment/topic columns (`sentiment_score`, `sentiment_summary`, `main_inspection_topics`, `inspectors_median_sentiment_score`) are referenced by small commented-out breadcrumbs in the main script (marking where the `admin/sentiment_experiment.py` functions would plug back in, see step 7) but are not produced by anything currently — don't expect them in output.

## Key external links

- **Ofsted reports search** (scrape entry point) — `https://reports.ofsted.gov.uk/` — `search_url`/`pagination_param` in the config block build the "Local Authority Children's Services" filtered search URL this script paginates.
- **Individual inspection report PDFs** — served from `https://files.ofsted.gov.uk/v1/file/<id>`; this is what `inspection_link` points to and what gets downloaded into `export_data/inspection_reports/`.
- **ADCS ILACS Outcomes Summary** (the periodic publication this project re-creates on-demand) — `https://adcs.org.uk/inspection/article/ilacs-outcomes-summary`.
- **Published output (GitHub Pages)** — https://data-to-insight.github.io/ofsted-ilacs-scrape-tool/.
- **Smart Cities Concept Model** reference (background for `sccm.yml`) — `https://www.smartcityconceptmodel.com`.

These appear as literal strings in `save_to_html`'s `intro_text`/`disclaimer_text` (`ofsted_ilacs_scrape.py:1165-1180`) and in the config block (`ofsted_ilacs_scrape.py:33`) — update both places if a source URL changes.

### Key data conventions
- **`urn`** (Ofsted's unique provider reference) is the primary join key throughout — always coerced to `int64`/numeric before merges.
- **`la_code`** is the older/historic LA number, brought in via the lookup CSV for backwards-compatible use cases.
- **`la_code_new`** (from the lookup CSV) is the ONS/GSS local authority code shown in the published output (`column_order`) — "new" relative to the older numeric `la_code` scheme it succeeds, not a reference to any particular code vintage. It's kept current on a rolling basis, so it gets updated whenever an LA's code changes (e.g. Barnsley E08000016→E08000038 and Sheffield E08000019→E08000039 from the April 2025 Barnsley and Sheffield (Boundary Change) Order). It's the **sole** ONS-code column in the CSV — `lad23cd`, `ltla23cd`, and `ltla23_ons` used to duplicate the same value and were removed, since keeping several manually in sync invited exactly the kind of drift this column now tracks alone (Barnsley/Sheffield's 2025 codes were caught out of sync in one of these duplicate columns before the consolidation). `admin/check_la_code_currency.py` is a manual, non-CI check for drift against the live ONS dataset. The lookup CSV deliberately keeps rows for defunct historic LAs (e.g. Cumbria, pre-2021 Northamptonshire, Poole, all with a blank `la_code_new` since none has a single current successor code) so other LAs' `stat_neighbours_previous` references stay resolvable — these never appear in the scraped output anyway, since that's a left join keyed on currently-scraped `urn`s.
- Local authority names are normalised through `clean_provider_name` (lowercased, council/borough/district boilerplate stripped) — apply the same cleaning if adding new name-based joins, or names won't match.
- Per-LA PDF export directories are named `<urn>_<cleaned_la_name>` under `export_data/inspection_reports/`.

### Supporting files (not part of the main pipeline)
- **`admin/generate_sccm_graph.py`** — regenerates `sccm_graph_static.svg` from `sccm.yml` (the Smart City Concept Model entity/relationship graph shown in the README) using `networkx`/`graphviz`. Run manually, not part of the scrape.
- **`sccm.yml`** — source of truth for the SCCM entities/relationships; edit this, then regenerate the SVG, if the conceptual model changes.
- **`admin/validate_scrape_output.py`** — the CI sanity check described under "CI / deployment" below; also runnable manually.
- **`admin/check_la_code_currency.py`** — manual, non-CI check for `Provider_data_lookup.csv`'s `la_code_new` codes going stale against the live ONS Open Geography Portal "Local Authority Districts ... Names and Codes in England" dataset. Not wired into either GitHub Actions workflow — LA boundary changes are rare, government-order-driven events, not worth checking on every daily/PR run. Run manually with `uv run python admin/check_la_code_currency.py`.
- **`admin/sentiment_experiment.py`** — unused reference code for sentiment/topic analysis on inspection PDFs (see step 7 above); not imported by anything.

## CI / deployment

Two workflows, deliberately kept separate:

- **`.github/workflows/gh_refresh_gpage.yml`** ("Daily ILACS Scrape & Deploy") — the publish job. Triggers on `push`/`schedule`/`workflow_dispatch` against `main` (**not** `pull_request` — see below), runs the scraper, commits the refreshed `index.html` + `.xlsx` back to `main`, and deploys `index.html` to GitHub Pages. **Per the README, the scheduled auto-run is not currently working reliably** — the script is being run manually (via Codespaces + `./setup.sh` + running the script + push) as a workaround. If asked to fix "the daily refresh isn't happening," this workflow/schedule is the place to look, not the scrape logic itself.
- **`.github/workflows/pr_check.yml`** ("PR Check - Scrape & Validate") — runs on `pull_request` against `main`. Checks out the PR's own branch (unlike the daily job, which hardcodes `ref: main`), runs the same scrape + validate steps, but never commits or pushes anything. This exists so a PR that breaks the pipeline is actually caught, without touching `main`.

These used to be one workflow with `pull_request` as an extra trigger on the daily job - that always checked out and pushed to `main` regardless of which event fired it, so a PR run tested nothing (it ignored the PR's actual changes) and could race the real push-triggered run: both PR #1 and PR #2's `pull_request`-triggered runs failed with `git push` rejected (`cannot lock ref`/`fetch first`) because `main` had moved on (from the PR being merged) by the time the redundant PR-triggered scrape finished. Split into two workflows to fix this - if this regresses, check that `gh_refresh_gpage.yml` still has no `pull_request` trigger before assuming it's a new bug.

Between the scrape step and the commit-back step (in `gh_refresh_gpage.yml`) or the final step (in `pr_check.yml`), both workflows run `admin/validate_scrape_output.py` — a stdlib-only sanity check (row count, required columns, file sizes) that fails the job rather than publishing/passing an obviously broken scrape. It also checks what fraction of LAs have no real `overall_effectiveness_grade` (still `data_unreadable`/missing): over 10% fails the job (`::error::`, likely a systemic break rather than the usual handful of known per-LA quirks — see README "Known Bugs"), any failures at all emit a `::warning::` GitHub Actions annotation without blocking. Run it manually with `uv run python admin/validate_scrape_output.py` after a local run if you want the same check.

Manual run instructions for non-admin users are in the README ("Script admin notes"): open a Codespace on `main`, run `./setup.sh` (`chmod +x setup.sh` first if permission denied), run `uv run python ofsted_ilacs_scrape.py`, download the refreshed `.xlsx`.

## Known limitations to keep in mind

- The Ofsted site's HTML structure and PDF report layout are moving targets outside this project's control — scrape/parse logic is inherently brittle and may need re-tuning (see the "In progress Ofsted site/search link refactoring" notes near the top of the script for a partially-started URL param refactor).
- Some LAs have PDF encoding/formatting quirks causing specific columns to fail extraction (see README "Known Bugs"); when fixing one, check whether the fix regresses the others, as several fixes have been layered defensively (`fix_invalid_judgement_table_structure`, `fix_misalligned_judgement_table`).
- Geospatial/choropleth mapping and sentiment analysis are both explicitly unfinished — don't assume commented-out code nearby is dead; it's often paused work-in-progress referenced in the README's "Future work" section.
