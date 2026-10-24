---
id: xlsx
name: Xlsx
category: productivity
invocation: both
description: Create Excel (.xlsx) spreadsheets deterministically with a stdlib-only script — a title row plus data rows, shared strings, no new dependency needed.
tags: [xlsx, spreadsheet, excel, generation]
triggers: ["create an xlsx", "make a spreadsheet", "generate an xlsx"]
---
# Xlsx

Create a .xlsx file deterministically — do not hand-write spreadsheet
XML in chat. Use the skill script:

```
python3 scripts/generate.py --title "Report" --out out.xlsx \
  --rows '[["Name", "Score"], ["Ada", 10]]'
```

The script builds the file with zipfile + templated XML (stdlib only),
using shared strings. Verify: it opens as a ZIP and
`xl/sharedStrings.xml` contains the title and cell values.

## Rules
- The first row of --rows is the header row; the title is written as a
  row above it. All values are stored as text.
