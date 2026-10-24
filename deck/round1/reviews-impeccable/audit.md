# Audit: Asli Awaaz pitch deck (deck/slides/*.html, 17 pages, 1920x1080 PDF)

Scope: static review of 17 HTML fragments plus the rendered PNGs in deck/page_images, against the audit dimensions adapted to a PDF deck (no interaction, no responsive layout, no runtime performance). References are `file:line`; each file has 5 lines, line 2 holds the visual body, line 4 the `<aside>`.

## Audit Health Score

| # | Dimension | Score | Key finding |
|---|-----------|-------|-------------|
| 1 | Accessibility (PDF/print) | 3 | Contrast and 24px floor pass; tag tree, language and font embedding unverified |
| 2 | Performance | 3 | No images, tiny HTML; risk is web-font fetch and custom elements at export |
| 3 | Responsive | 4 | N/A fixed canvas; no overflow found in the PNGs |
| 4 | Theming | 3 | Palette correct; hex hard-coded inline, no token variables |
| 5 | Anti-patterns | 3 | No gradients, shadows, glass or motion; a few rule-drift items |
| **Total** | | **16/20** | **Good, with fixable gaps** |

## Anti-patterns verdict
Does not look AI-generated. No gradient text, glow, side-stripe borders, hero-metric template or identical card grids. Page compositions differ (timeline plus stat panel, branching flow, table plus stat block, stepped phases). The one template tell is the appendix (four identical table pages). Detector side-tab hits are `border-top` section rules, not accent stripes.

## Executive summary
- 16/20 (Good). 0 P0 design defects; 1 P0 content blocker (placeholders); 3 P1; 7 P2; 5 P3.
- Top issues: unfilled placeholders; web fonts and custom elements as single points of failure at PDF export; off-scale type sizes (28/34/36/72px); appendix table repetition and dark-header run; no evidence of tagged-PDF or language metadata.
- Next: embed fonts, snap type sizes, fill placeholders, re-export, run a PDF accessibility check.

## Detailed findings

### P0
- [P0] Open placeholders ship in the PDF. Location: cover.html:2 (two teammate lines), evidence.html:2 (`[N]`, `[M]`, `[x]`), trust.html:2 (`[x]`), finale.html:2 (three `[Name: ...]`), arch2.html:2 (`[Bank retention policy]`). Category: content/compliance. Impact: brief needs 2 to 4 named members; brackets read as unfinished to a scorer. Fix: owner fills, or replace with plain language ("set after the first run"). Verify with `grep -c "\[[A-Za-z0-9]" deck/slides/*.html`.

### P1
- [P1] Fonts load from the network with weak fallbacks. Location: deck/deck.json `faces` (Google Fonts hrefs for Archivo, Archivo Narrow, Kalam, Rozha One); inline `font-family` stacks fall back to Helvetica Neue, Arial Narrow, Arial, Comic Sans MS, Georgia. Impact: offline or missing Arial Narrow on the export machine widens labels 15 to 25 percent and overflows fixed-width boxes in flow.html:2, arch1.html:2, arch3.html:2, journey.html:2; the Hindi wordmark would fall to Georgia and lose its glyphs. Fix: self-host the four WOFF2 files from deck/ds with `@font-face`, or verify the exported PDF embeds all four (`pdffonts deck.pdf`). Suggested command: `/impeccable harden`.
- [P1] Layout is all `position:absolute` with fixed pixel boxes and no heights. Location: every file, line 2. Impact: any copy edit (the P0 placeholders will force edits) overlaps neighbours silently. Fix: group text blocks in flex columns on the dense pages (arch1, arch3, trust); at minimum re-check PNGs after each edit.
- [P1] Custom elements `<x-connector>` and `<x-shape>` carry arrows and diamonds. Location: journey.html:2, flow.html:2, arch1.html:2, arch3.html:2. Impact: they render in the supplied PNGs, but another renderer would drop every arrow and diamond. Fix: confirm the PDF pipeline expands them; keep the PNG check in the export checklist.

### P2
- [P2] Type scale drift. 28px (about 70 elements, e.g. harm.html:2, journey.html:2), 34px cover.html:2, 36px flow.html:2, 72px cover.html:2. README scale: 128, 68, 44, 32, 26, 40 hand note. Fix: snap to scale or extend tokens.json. Command: `/impeccable typeset`.
- [P2] Tight leading, detector-confirmed: arch1.html:2 (8), flow.html:2 (5), cover.html:2 (2), arch3.html:2 (1), all 1.20x on multi-line Archivo Narrow labels. Fix: 1.3 and widen boxes.
- [P2] Line length: trust.html:2 about 110 characters per line (width ~1244px at 26px). Fix: cap near 75 to 85 characters.
- [P2] Colour-only carriers: arch3.html:2 legend (two close greys), harm.html:2 timeline dots (ink versus magenta, no shape or word). PRODUCT.md principle 4. Fix: add labels or shapes.
- [P2] Dark-header table run: app1 to app4 and arch2 all dark; README allows one per run. Fix: light header on app2 to app4.
- [P2] arch1.html:2 "app prompt" box at y~120 sits above the 128px margin; one shared trunk carries four outputs including the Hold-only dashed path. Fix as critique P2-4.
- [P2] Unlabelled arrows: journey.html:2, flow.html:2 (into "Passes"), arch3.html:2 lifecycle. Fix: label or footnote.

### P3
- Content top edge inconsistent (226 / 240 / 250px) across app1, arch2, others.
- harm.html:3 footer 1380px nowrap box overlaps the counter box (text does not collide today).
- Colours are hard-coded hex inline (`#0F1A30`, `#34405A`, `#4E5A73`, `#086B62`, `#B0105A`); no CSS variables. Acceptable for a generated PDF; emit from tokens.json in the generator so palette changes are one edit.
- `data-transition="fade"` on every `<section>` (line 1) is an animation hint that contradicts "no motion"; remove if the exporter ignores it.
- Stamps over four words: harm.html:2 "All cyber fraud, not only voice"; rollout.html:2 "Assumption: RBI and DPDP fit".

## Dimension notes

Accessibility (PDF/print)
- Contrast: body #34405A on #EAEFF3 about 8:1; captions and footers #4E5A73 about 6:1; rule lines #6F7D94 are decorative only; white-on-ink headers and the night panel pass. Teal and magenta carry icons and outlines, not body text. Check the "1.0 s" dark label on the #6F7D94 bar in arch3 (about 3.5:1; bold 26px so it passes the large-text threshold, but darken the bar one step for safety).
- Minimum text 24px: pass (smallest 24px, footers; about 10.5 pt on A4 landscape).
- Colour not sole carrier: mostly pass (tick, half-circle, cross, solid versus dashed, a word on every chip). Two exceptions above.
- Structure: one `<h1>` on the cover, `<h2>` on every other page, real `<table>` with `<th>` on 9 pages (app1 to app4, arch2, arch3, detect, diff, evidence). Good for a tagged PDF. Not verified: document language, PDF title, tag tree. SVGs carry `aria-label` (waveform, ticks, crosses); `x-connector` arrows carry none. Fix: set language en and title "Asli Awaaz Round 1 Pitch" (in deck.json) at export; run a PDF/UA checker.
- Reading order: DOM order is title, body, footers; matches visual order on harm and journey. On arch1 it follows layout, not data flow; acceptable.

Performance
- No raster images; pages are 3 to 17 KB. Only costs are font fetch and long inline style strings (arch1 16.6 KB, arch3 15.9 KB). Not a PDF concern.

Responsive
- Not applicable. No clipped or overflowing text in the 17 PNGs.

Theming
- Palette matches the system: paper #EAEFF3, ink #0F1A30, soft #34405A, faint #4E5A73, rule #6F7D94, genuine #086B62 (tint #D2EAE6), synthetic #B0105A (tint #F3D3E1). Teal appears only on genuine/Clear items and the matching hand note (flow.html:2); magenta only on cloned, Hold and alert items, plus the harm.html:2 timeline noted above.

Rule compliance (design-system/README.md)
- No gradients, shadows, glass, filters or animation: pass (0 matches in 17 files).
- Minimum 24px: pass.
- "Slide" in visible text: none (0 matches in the files).
- Hindi wordmark once: pass (cover only).
- Hand notes at most two per page, eight words: pass.
- Seven-bar logo: absent everywhere.
- Page counters: pass ("Pitch page N of 10", "Architecture page N of 3", "Appendix A to D").
- Numbers sourced or labelled: pass; Pindrop figures carry "We have not tested it."
- Never imply code before finale: one breach, detect.html:2 "Built with".

## Patterns and systemic issues
- Diagram label pattern (Archivo Narrow 24 to 28px at 1.2 leading in tight boxes) recurs on 5 pages; fix once in the generator.
- Absolute positioning plus inline hex repeats in all 17 files; one generator template change fixes both theming and layout brittleness.

## Positive findings
- Disciplined palette and flat surfaces, applied consistently.
- Honest labelling (stamps, "Illustration, not data", "Typical pattern, not one case").
- Meaning carried three ways (colour, shape, word) on every state.
- Real semantic tables and heading levels.

## Recommended actions (priority order)
1. [P0] Fill or rewrite placeholders (cover, evidence, trust, finale, arch2).
2. [P1] Self-host or embed the four fonts; confirm with `pdffonts`.
3. [P1] Confirm `x-connector` and `x-shape` render in the final PDF.
4. [P2] Snap off-scale type sizes and fix tight diagram leading (`/impeccable typeset`).
5. [P2] Fix arch1 margin, trunk line and arrow labels; label arch3 legend (`/impeccable layout`).
6. [P2] Appendix: light headers on app2 to app4, merge app3 and app4 (`/impeccable polish`).
7. [P3] Normalise content top edge and footer width; remove `data-transition`.
8. Re-run `/impeccable audit` after fixes.

## Detector detail (impeccable detect --json deck/slides)
- tight-leading x16 (arch1 8, flow 5, cover 2, arch3 1): real, low impact.
- low-contrast x10 (arch3 6, diff 4): false positives (light text on ink panels the detector could not see behind).
- side-tab x10 (finale 3, harm 4, rollout 3): false positives (`border-top: 3px` section rules).
