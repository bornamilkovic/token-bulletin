#!/usr/bin/env python3
"""Publish new issues dropped into inbox/.

Each issue arrives as a pair in inbox/:
    tb-<year>-<week>.pdf   the paper
    tb-<year>-<week>.json  its entry: number, year, week, date, headlines

For every complete pair (lowest issue number first) this script checks it,
moves the PDF to papers/<year>/, appends the entry to papers.json and, with
--commit, makes one git commit per issue. Any problem stops everything
before a single file is changed. A file whose partner hasn't arrived yet is
left in the inbox for the next run.

Run from the repo root:  python3 scripts/publish_inbox.py [--commit]
"""

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

INBOX = Path("inbox")
PAPERS_JSON = Path("papers.json")
NAME_RE = re.compile(r"^tb-(\d{4})-(\d{2})\.(pdf|json)$")
IGNORED = {"README.md", ".gitkeep"}
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_HEADLINE_CHARS = 200
ALLOWED_KEYS = {"number", "year", "week", "date", "pdf", "headlines"}


class Problem(Exception):
    pass


def load_papers():
    papers = json.loads(PAPERS_JSON.read_text(encoding="utf-8"))
    if not isinstance(papers, list):
        raise Problem("papers.json is not a list")
    return papers


def check_entry(stem, year, week, raw, expected_number):
    """Validate one inbox JSON entry and return it in canonical form."""
    try:
        entry = json.loads(raw)
    except json.JSONDecodeError as e:
        raise Problem(f"{stem}.json is not valid JSON: {e}")
    # Accept a one-item list too, since that's how papers.json looks.
    if isinstance(entry, list) and len(entry) == 1:
        entry = entry[0]
    if not isinstance(entry, dict):
        raise Problem(f"{stem}.json must hold one issue entry (a JSON object)")

    extra = set(entry) - ALLOWED_KEYS
    if extra:
        raise Problem(f"{stem}.json has unknown fields: {', '.join(sorted(extra))}")
    for key in ("number", "year", "week", "date", "headlines"):
        if key not in entry:
            raise Problem(f"{stem}.json is missing \"{key}\"")
    for key in ("number", "year", "week"):
        if type(entry[key]) is not int:
            raise Problem(f"{stem}.json: \"{key}\" must be a whole number")

    if entry["year"] != year or entry["week"] != week:
        raise Problem(
            f"{stem}.json says year {entry['year']}, week {entry['week']}, "
            f"but the file name says year {year}, week {week}"
        )
    if entry["number"] != expected_number:
        raise Problem(
            f"{stem}.json is No. {entry['number']}, but the next issue "
            f"should be No. {expected_number}"
        )

    try:
        date = datetime.date.fromisoformat(entry["date"])
    except (TypeError, ValueError):
        raise Problem(f"{stem}.json: \"date\" must look like 2026-11-14")
    iso_year, iso_week, _ = date.isocalendar()
    if (iso_year, iso_week) != (year, week):
        raise Problem(
            f"{stem}.json: date {entry['date']} is in ISO week {iso_week} "
            f"of {iso_year}, not week {week} of {year}"
        )

    pdf_path = f"papers/{year}/{stem}.pdf"
    if "pdf" in entry and entry["pdf"] != pdf_path:
        raise Problem(f"{stem}.json: \"pdf\" should be {pdf_path}")

    headlines = entry["headlines"]
    if (
        not isinstance(headlines, list)
        or not headlines
        or not all(isinstance(h, str) and h.strip() for h in headlines)
    ):
        raise Problem(f"{stem}.json: \"headlines\" must be a list of non-empty text")
    if len(headlines) > 10 or any(len(h) > MAX_HEADLINE_CHARS for h in headlines):
        raise Problem(
            f"{stem}.json: at most 10 headlines of {MAX_HEADLINE_CHARS} characters each"
        )

    return {
        "number": entry["number"],
        "year": year,
        "week": week,
        "date": entry["date"],
        "pdf": pdf_path,
        "headlines": [h.strip() for h in headlines],
    }


def check_pdf(stem, pdf):
    size = pdf.stat().st_size
    if size > MAX_PDF_BYTES:
        raise Problem(f"{stem}.pdf is {size // (1024 * 1024)} MB; the limit is 25 MB")
    with pdf.open("rb") as f:
        if f.read(5) != b"%PDF-":
            raise Problem(f"{stem}.pdf is not a PDF file")


def plan():
    """Work out what to publish. Raises Problem without touching any file."""
    if not INBOX.is_dir():
        return [], []

    pairs, unknown = {}, []
    for f in sorted(INBOX.iterdir()):
        if f.name in IGNORED:
            continue
        m = NAME_RE.match(f.name)
        if not m or not f.is_file() or f.is_symlink():
            unknown.append(f.name)
            continue
        year, week, ext = int(m[1]), int(m[2]), m[3]
        pairs.setdefault((year, week), {})[ext] = f
    if unknown:
        raise Problem(
            "inbox has files that don't look like tb-<year>-<week>.pdf/.json: "
            + ", ".join(unknown)
        )

    papers = load_papers()
    numbers = [p["number"] for p in papers]
    next_number = max(numbers, default=0) + 1
    known_pdfs = {p["pdf"] for p in papers}

    ready, waiting = [], []
    entries = []
    for (year, week), files in pairs.items():
        stem = f"tb-{year}-{week:02d}"
        if set(files) != {"pdf", "json"}:
            waiting.append(next(iter(files.values())).name)
            continue
        raw = files["json"].read_text(encoding="utf-8")
        try:
            number = json.loads(raw)
            number = (number[0] if isinstance(number, list) and number else number)["number"]
        except Exception:
            number = None
        entries.append((number if isinstance(number, int) else 0, year, week, stem, files, raw))

    for _, year, week, stem, files, raw in sorted(entries, key=lambda e: e[0]):
        if not 1 <= week <= 53:
            raise Problem(f"{stem}: week must be between 01 and 53")
        entry = check_entry(stem, year, week, raw, next_number)
        target = Path(entry["pdf"])
        if target.exists() or entry["pdf"] in known_pdfs:
            raise Problem(f"{entry['pdf']} already exists; not overwriting it")
        check_pdf(stem, files["pdf"])
        ready.append((entry, files))
        next_number += 1

    return ready, waiting


def git(*args):
    subprocess.run(["git", *args], check=True)


def publish(ready, commit):
    papers = load_papers()
    for entry, files in ready:
        target = Path(entry["pdf"])
        target.parent.mkdir(parents=True, exist_ok=True)
        files["pdf"].rename(target)
        files["json"].unlink()
        papers.append(entry)
        PAPERS_JSON.write_text(
            json.dumps(papers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        title = f"Add {target.stem} (No. {entry['number']})"
        print(f"Published {title}")
        if commit:
            git("add", "--all", "--", str(INBOX), str(target), str(PAPERS_JSON))
            git("commit", "--quiet", "-m", title)


def main():
    commit = "--commit" in sys.argv[1:]
    try:
        ready, waiting = plan()
    except Problem as e:
        print(f"::error::{e}" if commit else f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    for name in waiting:
        print(f"Waiting for the other half of {name}; leaving it in the inbox.")
    if not ready:
        print("Nothing to publish.")
        return
    publish(ready, commit)


if __name__ == "__main__":
    main()
