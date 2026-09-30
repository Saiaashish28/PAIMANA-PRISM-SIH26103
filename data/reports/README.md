# PAIMANA / OCMS PDF reports

Drop the monthly Flash Reports here (any sub-folder). They are converted into one table per
month in `data/real/paimana_YYYY-MM.csv`, which the app then trains on:

```bash
cd backend
python -m prism.data.pdf_import          # extract every PDF under data/reports/ (cached; --force to redo)
python -m prism --force                  # retrain on the extracted data
```

Or use **Data sources → Import PDFs & retrain** in the app.

| Report type | Imported? |
| --- | --- |
| PAIMANA Flash Report (2025 onwards, "Table 6: All Ongoing Projects") | Yes: all ongoing projects plus the month's completed projects |
| MoSPI Flash Report "List of Tables" (2024 – early 2025) | Yes: ongoing and completed project lists |
| Quarterly QPISR reports with a full project list | Used only for months that have no monthly Flash Report |
| OCMS Flash Reports 2020–2023 | Not yet: they have no physical-progress column |
| Synopsis / Part-I, Review Reports (sector output statistics) | No: they contain no project-level tables |

Projects are matched across months by their PAIMANA project code. Older reports are linked
through the legacy OCMS code (e.g. `N24001425`), or by an identical sanctioned cost plus a
similar name when the code is missing.

Check: extracting `FlashReport_April2026.pdf` reproduces the official April 2026 totals
(1,981 projects; ₹37.13 / ₹42.78 / ₹20.36 lakh crore original cost / revised cost /
expenditure; 17 ministries; 22 sectors). This is covered by a test.
