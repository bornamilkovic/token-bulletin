# Inbox

Drop a new issue here as two files with the same name:

- `tb-<year>-<week>.pdf`: the paper
- `tb-<year>-<week>.json`: its entry, for example:

```json
{
  "number": 3,
  "year": 2026,
  "week": 46,
  "date": "2026-11-14",
  "headlines": [
    "Lead headline",
    "Second headline",
    "Third headline"
  ]
}
```

Upload both in one go (on github.com: **Add file → Upload files** in this folder, commit to `main`). The **Publish new issue** action then checks them, moves the PDF to `papers/<year>/`, adds the entry to `papers.json`, empties the inbox and commits `Add tb-<year>-<week> (No. N)`. The archive page updates a minute or two later.

If something is wrong (bad JSON, the wrong issue number, a week that doesn't match the date, a PDF that already exists), the action fails, nothing is published and GitHub emails you. Fix or replace the files here and it runs again.
