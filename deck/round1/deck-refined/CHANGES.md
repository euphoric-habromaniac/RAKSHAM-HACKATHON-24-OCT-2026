# deck-refined: change log

Source `deck/` was copied and left untouched. All edits are in `deck-refined/slides/*.html`. `deck.json`, `ds/` and `page_images/` are unchanged (`page_images/` still shows the old renders).

Visible text, numbers, placeholders and sources are word-for-word identical to `deck/` (checked per file with a word-count diff). Footers and titles are unchanged in text, size and position.

Detector (`impeccable detect --json deck-refined/slides`): 36 hits before (tight-leading x16, low-contrast x10, side-tab x10), 0 after in those categories. Run again after the work, it reports 23 advisory `design-system-*` hits. A `DESIGN.md` appeared in the project root after my first run, so these checks were not in the baseline. They are 17 footer lines at 24px (required by the footer rule and the 24px floor), 4 `x-connector` border colours that the export pipeline reads from `color:`, and 2 radii (4px and 12px) that are both in `tokens.json`. I left all of them.

## Global (every file)
- Type scale: 28 -> 26, 34 -> 32, 72 (Hindi wordmark) -> 68, 36 (hand note) -> 40. Body-size 24 -> 26. Only 128, 68, 44, 32, 26, 40 remain, plus 24 on footers.
- Line-height 1.2 -> 1.3 on all text (clears the tight-leading hits). 40px hand notes use 1.1.
- `data-transition="fade"` -> `"none"` (no motion).
- Role rule: node, card and column titles use 32px Archivo Narrow 700. Labels and diagram text use 26px. Titles of tiny cards stay 26px where 32px does not fit.
- Content starts at y=250 on every page (title top 128 + 73 title height + 48 gap).

## cover.html
- Title moved to the 128px top margin like every other page. The event and round lines were above the title, which read as an eyebrow, so they moved to a ruled bottom block beside the team block.
- Rebuilt as three tiers: title, underline and Hindi wordmark; the 44px lead; two ruled columns (Team, event and round).
- Bars graphic pulled inside the right margin (it overflowed to x=1880). Caption and "Illustration, not data." moved under the bars.

## harm.html
- Step labels 26 -> 32; steps no longer wrap to four lines.
- "One precedent" 44 -> 32, so the 44px figure leads. Stat panel height 500 -> 460 to match the timeline.
- Column rules moved from `border-top:3px` to 3px block elements. Visually the same, clears the side-tab hits.
- Removed the duplicate hairline under the title area.

## journey.html
- "Today" and "With Asli Awaaz" -> 32. Clear, Step up and Hold titles 26 -> 32. Result boxes 128 -> 140 high, spacing re-set, connectors and icons realigned.

## flow.html
- Hand note 40px with 1.1 leading so its three lines clear the Passes box. First two nodes 100 -> 112 high so three-line labels sit inside the border.

## detect.html
- Two tables joined into one (the "Run only after the band is set" band is now a row). Cell padding, collapsed borders and rule hairlines added; question lines set in ink-soft under the bold check name.
- Clear, Step up and Hold are now one flex column of auto-height panels with icons inside the panel (no hard-coded heights, no overflow). Titles 32.
- Removed the left/right border on the divider band.

## diff.html
- The dark statement panel now contains its text (fixes the false low-contrast hits and keeps copy inside its panel). Stat 68, lead 32, caption 26.
- Table in flow with padding and hairlines. The two notes sit below it in one flex column.

## evidence.html
- Table padding and hairlines; "What we report" label and stamp re-spaced. Card titles 32, card heights aligned to the assumptions panel bottom.

## trust.html
- Absolute-positioned rows replaced with a ruled Q and A list in flow (question 32 narrow, answer 26 ink-soft, solid rule hairlines, no fill). The fixed row pitch was crowding the second line of long answers.
- Two bottom boxes in one flex row with auto height.

## rollout.html
- Phase and column titles 32. Phase cards 20px taller, dividers moved down, so four-line text stays inside the border. 3px column rules as blocks. Hand note leading 1.7 -> 1.1.

## finale.html
- Layout changed so pages 9 and 10 no longer repeat the "cards plus three columns" pattern: hours strip (widths still proportional to hours), then a left stack of three demo rows (title and result) and a right ruled list (Gathered beforehand, Built on site, Who does what).
- Teal and magenta used only for the genuine caller (solid, tick) and pre-recorded clone (dashed, cross); the live voice changer stays plain.

## arch1.html
- Node heights and gaps re-set for 26px text at 1.3 leading (network boundary and service box taller). Connectors re-pointed. Annotation text aligned to the 128px top.

## arch2.html
- Table padding, hairlines and column widths. Right-hand attacker list rebuilt as a ruled flow list. Provenance box re-spaced.

## arch3.html
- Table padding and hairlines. Bar and circle labels moved inside their bars (clears the low-contrast hits). Small time labels widened and set to no-wrap (the "s" was wrapping). "Time budget per call" and "Validation, in order" 32. Validation list and paragraph re-spaced. Evidence pack aligned to the right column's bottom.

## app1.html, app2.html, app3.html, app4.html
- Table top 226 -> 250 (title gap 48). Cell padding, collapsed borders, rule hairlines. URL lines in app3 and app4 24 -> 26.

## Second pass: rendering robustness, arch1, appendix
- Fonts: every stack now ends in a metric-close fallback. Archivo: 'Helvetica Neue', Arial, sans-serif. Archivo Narrow: 'Arial Narrow', 'Liberation Sans Narrow', Arial, sans-serif. Kalam: 'Segoe Print', cursive (was Comic Sans MS). Rozha One: Georgia, serif (unchanged).
- `<x-connector>` and `<x-shape>` removed from arch1, arch3, flow and journey. Arrows are now inline SVG (polyline plus filled triangle head, same geometry and dash as the shim in handoff/src/build_pdf.py); the two nested diamonds are inline SVG polygons at the same boxes. No custom elements remain, so PDF export no longer needs the shim. Text and positions are unchanged on flow, journey and arch3.
- arch1: "Bank app" box moved from y=120 to the 128px top margin. The old shared trunk is split. One solid ink trunk (x=1292) now carries Fusion and policy to the agent desktop, analyst console and case system/SIEM, with an arrowhead where it leaves the policy box and the label "Clear, Step up or Hold". The Hold-only path is its own magenta dashed line from the same point, up to the bank app box, labelled "app prompt". Output column re-set to x=1500, width 292. Branch labels moved to match.
- app1 keeps the one dark-header table. app2 is now a ruled list (ID, assumption, test or owner; solid rule hairlines, no fill). app3 and app4 have a paper-deep header row with ink text. Appendix text is word-for-word as before.
- Detector (`impeccable detect --json deck-refined/slides`): 19 hits, all the advisory design-system-font-size (24px footers) and design-system-radius items listed above; 0 tight-leading, low-contrast or side-tab. The x-connector colour hits are gone.
- All 17 `page_images/*.png` re-rendered with handoff/src/render_slides.py (names unchanged). Reported overflow notes on cover, flow and rollout are the hand-note and Hindi line boxes, as before.

## Third pass: merged journey, new screens page, finale spacing, PDF tags
- Order is now cover, harm, journey, screens, detect, diff, evidence, trust, rollout, finale (pitch 10), arch1 to arch3, app1 to app4 (17 pages). `deck.json` order updated; section s2 now starts at `screens`.
- journey.html (page 3) now holds the old pages 3 and 4 as one diagram (critique P1-1). Top: the Today lane (four one-line boxes, cross on "Agent approves the request", the trust caption). Below a rule: With Asli Awaaz, "the call keeps its first three steps" and the 10 s line with one "Target, not a result" stamp. Then flow's diagram: call opens, audio tapped and scored, Risk band diamond, labelled branches (Low: no signal; Medium: one strong or two weak signals, or a sensitive request; High: strong signals agree), Clear, Step up with Passes and "fails or unclear" to Hold, and the evidence-record band. Clear, Step up and Hold text merges both pages' wording; no fact dropped. Flow's footer line ("actions with their own shapes; colour is a second cue") and its speaker note moved into the merged speaker note. Flow's hand note was dropped for space.
- flow.html moved out of the build to `deck-refined/retired/flow.html` (kept, not deleted).
- screens.html (new, page 4, critique P1-2): "What the agent and the customer see". Flat agent-desktop panel with Clear (tint, solid teal, tick), Step up (raised, 3px ink, half circle, six empty digit boxes, no digits) and Hold (tint, dashed magenta, cross, the trust-page message "Voice differs from the enrolled sample. Ask the customer to confirm in the app."). A dashed "app prompt" arrow goes to the customer's bank-app prompt (Confirm, Deny, Report; ink only). All wording comes from pages 3, 5, 8, arch1 and arch3; no numbers. Stamp "Illustrative screen, not a built product" (six words, as requested, over the four-word stamp guideline).
- Counters: only pages 3 and 4 changed ("Pitch page 3 of 10", "Pitch page 4 of 10"). Every other cross reference (pitch page 5 on arch1 footer and note, page 5 on diff, Appendix C/D "Used on" pages 2, 6, 7, 9, and pages 2, 6 and 7 in notes) still points at the same content, so none needed changing. Verified in the PDF text: counters run 1 to 10.
- finale.html: the right column (Gathered beforehand, Built on site, Who does what) is one flex column with 3px rule blocks and even 12px gaps; the four Who does what rows sit 4px apart and end level with the left demo rows (~y=932), about 50px above the footer. Text unchanged.
- handoff/src/build_pdf.py: `<html lang="en">`, and `pg.pdf(..., tagged=True, outline=True)` (Playwright 1.62.0 supports both). Metadata blanking unchanged. pdfinfo: Tagged yes, Pages 17, Title kept, Creator and Producer blank.
- Detector: 19 hits, all advisory (17 footer font-size at 24px, 2 arch1 radii), as before. New hits found during the work (side-tab on finale rules, cramped padding on screens) were fixed.
- `page_images/` re-rendered and renamed to the new order (01-cover to 17-app4; 04-screens replaces 04-flow). Render overflow notes remain only on cover (Hindi line box) and rollout (unchanged page).
