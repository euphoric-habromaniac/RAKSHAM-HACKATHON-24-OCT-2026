# Asli Awaaz deck: source

This folder rebuilds `final.pdf`, the Round 1 submission (10 pitch pages, 3 architecture pages, Appendix A to E).

## What is here

- `slides/`: one HTML file per page. Each file is one `<section>` sized 1920 by 1080, with inline styles. The `<aside>` at the end of each file holds speaker notes, which do not appear in the PDF.
- `deck.json`: page order (`order`) and the web fonts (`faces`).
- `build_pdf.py`: renders the pages in a headless browser and writes `final.pdf` next to it.

## Page to file

| Page | File |
|---|---|
| Pitch 1 to 10 | cover, harm, journey, screens, detect, diff, evidence, trust, rollout, finale |
| Architecture 1 to 3 | arch1, arch2, arch3 |
| Appendix A to E | app1 (disclosures), app2 (assumptions), app3 and app4 (sources), app5 (rubric map) |

## Set up once

```
pip install -r requirements.txt
python -m playwright install chromium
```

## Rebuild

```
python build_pdf.py
```

On Windows, run `set PYTHONUTF8=1` first (or `$env:PYTHONUTF8=1` in PowerShell). The build needs an internet connection, because the fonts load from Google Fonts. Check the result: all fonts should show `yes` under `emb` in `pdffonts final.pdf`.

## Making a small change

1. Open the page's file in `slides/` and edit the text between the tags. Keep the `style` attributes as they are.
2. Rebuild and look at the page in `final.pdf`.
3. Every element is placed with absolute positions, so a much longer line can overflow its box. Shorten the text or widen the box (`width:`) if it does.

## Rules the deck follows

- Teal is used only for a genuine voice and the Clear state. Magenta is used only for a synthetic voice, Hold and alerts.
- No text smaller than 24px.
- Say "page", never "slide".
- Every number has a source in Appendix C or D, or is marked as a target.
- Pitch pages must stay at 10 and architecture pages at 3 (limits from the brief). If you add or remove a page, update `order` in `deck.json`, the "Pitch page N of 10" footers, and the page references in Appendix C, D and E.
