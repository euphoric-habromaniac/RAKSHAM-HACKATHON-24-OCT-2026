⚠️ DEGRADED: single-context (caller asked for a read-only inline run; Assessment A and B were not split into isolated sub-agents. Detector output was read after the visual review of all 17 PNGs, but in the same context.)

# Critique: Asli Awaaz pitch deck (deck/slides/*.html, 17 pages, 1920x1080 PDF)

Binding rules from design-system/README.md and PRODUCT.md were treated as the brief. References are `file:line`. Every slide file is 5 lines: line 1 `<section>`, line 2 the whole visual body (a few files put footers on line 3), line 4 the `<aside>` speaker notes. So locate items by the quoted text.

## Verdict
Disciplined, honest and well matched to the brief: flat surfaces, colour paired with shape and word, no gradients or shadows, every claim carries a label or stamp, and limits sit beside capabilities. It reads like a printed pitch sheet. The weakness is persuasion and pacing, not craft: the same Clear/Step up/Hold story is drawn four times, the product's one human-facing surface (what the agent sees) is never drawn, the appendix is four near-identical table pages, and owner placeholders are still open one day before the deadline.

Design-health read (0-4): hierarchy 3.5, message clarity 3, consistency 3, density control 2.5, brand presence 2.5, rule compliance 3.5.

## Detector (Assessment B) summary
`impeccable detect --json deck/slides`: 31 hits, none confirmed as a real defect.
- low-contrast x10 (arch3, diff): false positives. Light text sits on ink-filled panels or bars that are sibling absolutely-positioned divs, so the detector compared against the page ground. Checked in diff and arch3 PNGs: legible.
- side-tab x10 (finale, harm, rollout): false positives. They are `border-top:3px` section rules, not accent side stripes.
- tight-leading 1.20x x16 (arch1 8, flow 5, cover 2, arch3 1): true but low impact; Archivo Narrow labels at 24-28px inside diagram boxes. Real consequence in flow and arch1 (P2-3).

## P0 (blocks submission)
1. Unfilled owner placeholders on the cover and four other pages. cover.html:2 `[Teammate 2: name, programme, role]`, `[Teammate 3 and 4, if joining]`; evidence.html:2 `[N]`, `[M]`, `[x]`; trust.html:2 `[x]`; finale.html:2 `[Name: scoring models]`, `[Name: backend and policy]`, `[Name: screens and demo]`; arch2.html:2 `[Bank retention policy]`. The brief requires 2 to 4 student members, so one named member on the cover is a rubric risk. Due 12 Oct 23:59 IST. Fix: owner fills names; if the team really is one person, say so plainly on the cover and finale and reword the finale footer ("team of three or four"). For [x], [N], [M], supply a number stamped "Target, not a result" or replace with "set after the first run" (evidence.html already does this for equal error rate).

## P1 (materially weakens the pitch)
1. The deck tells the same story four times. journey.html:2 draws "Customer calls / Menu routes / Agent asks" twice (Today lane, With lane); flow.html:2 draws it again; detect.html:2 right column redefines Clear/Step up/Hold a third time; finale.html:2 a fourth. Pages 3 and 4 are one diagram at two zoom levels. Fix: merge them. Keep Today-versus-With from journey (three boxes, one line each) and the labelled branch logic from flow. Use the freed page for the drawing below.
2. The user-facing surface is never shown. The agent's band and message and the customer's app prompt are the product's moments of truth, yet appear only as text (arch1 "Agent desktop: band and plain message"). PRODUCT.md says draw the mechanism. Fix: add a flat SVG agent-desktop strip (no faces) with the three bands and the example message from trust.html ("Voice differs from the enrolled sample. Ask the customer to confirm in the app."), using tick, half-circle, cross exactly as the system specifies.
3. No page shows a result or a prototype, and the evidence page does not say so up front. evidence.html:2 ("Tests will use phone-line audio") is all plan. Fix: retitle as a fact ("No results yet; the test plan is fixed"), and lead with what is real: the 6.9 s GPU / 8.9 s CPU time budget from arch3 and the pass line.
4. The seven-bar logo mark is absent from the whole deck. PRODUCT.md and README list it as a brand commitment. cover.html:2 uses a 26-bar waveform illustration instead. Fix: put the seven-bar mark (four uneven teal, three equal magenta) beside "Asli Awaaz" on the cover and as a small footer mark, or drop the commitment from PRODUCT.md.
5. Pre-finale copy implies built code. detect.html:2 column header "Built with" (SpeechBrain, wav2vec2, faster-whisper) breaks "never say code was written before the finale." Fix: "Starts from" or "Model (planned)".

## P2 (visible polish and rule drift)
1. Appendix is four consecutive identical dark-header tables (app1 to app4), each leaving 25 to 35 percent of the canvas empty (app2.html:2 table ends y~757, app4.html:2 ends y~680, footer y~1000). README: one dark-header table per run, vary composition, no repeated grids on consecutive pages. arch2.html:2 is dark too. Fix: dark header on app1 only; light on app2 to app4; merge app3 and app4 into one two-column sources page; raise row padding or text to 28px to fill the page.
2. Off-scale type. README scale is 128/68/44/32/26 plus the 40px hand note, "add none". Found: 28px on about 70 elements (harm.html:2 timeline labels, journey.html:2 "Today", cover.html:2 meta), 34px cover.html:2 "Detectors look for generator patterns.", 36px flow.html:2 hand note, 72px cover.html:2 Hindi wordmark. Fix: snap 28 to 26 or 32, 34 to 32, 36 to 40; if 72 is deliberate add it to tokens.json.
3. Diagram label crowding and tight leading. flow.html:2 "Call opens; recording notice plays" is 3 lines at 1.2 leading in a ~100px box with text almost on the 3px border; "Hold: request paused, customer gets an app prompt, analyst opens a case" likewise. arch1.html:2 ASR, L1 and L2 boxes run 3 to 4 lines at 24px. Fix: widen boxes 20 to 30 percent or cut labels to one clause; line-height 1.3.
4. arch1 is the densest, least legible page. The "app prompt" box sits at y~120, above the 128px top margin; the bold 28px note beside the title competes with it; one vertical trunk at x~1264 carries four outputs (three solid ink, one magenta dashed) so the Hold-only path is ambiguous; internal arrows (Ingest to ASR/L1/L2, L1/L2 to Fusion) carry no label (README: label every arrow with what travels along it). Fix: give app prompt its own dashed magenta line from Fusion, move the box inside the margin, move the note under the diagram, label internal arrows ("5 s window", "score").
5. Unlabelled arrows: journey.html:2 (all connectors between Today boxes), flow.html:2 (arrow into "Passes"), arch3.html:2 lifecycle row. Fix: one word each, or one footer line saying unlabelled arrows are sequence only.
6. Stamps over four words: harm.html:2 "All cyber fraud, not only voice" (6), rollout.html:2 "Assumption: RBI and DPDP fit" (5). Fix: "Not only voice", "Assumption: RBI, DPDP".
7. Title grammar drift (README: noun phrase or one short fact, one grammar). Mix of noun phrases (arch2 "Data, consent and attack surface"), semicolon statement (detect.html:2 "Three scores set the band; two checks follow"), colon forms (trust.html:2 "Trust: five questions from the brief", all "Appendix: ..."), bare "How a bank adopts it". Fix: choose short-fact form; e.g. "Three scores set the band" and "Five answers to the brief".
8. Colour discipline. harm.html:2 colours three timeline dots and the hand circle magenta, but "After the call" (money moves) and "The approval" (a process step) are not the cloned voice itself. Fix: dots ink; magenta only on "The call"; ink circle on "The approval".
9. arch3.html:2 time-budget legend separates Features (#4E5A73) from L1+L2 (#6F7D94) by tone alone, and the 0.3 s / 0.5 s / 0.1 s labels sit on tick marks. Fix: label each segment directly or add hatch plus word; stagger the three small labels.
10. trust.html:2 is the heaviest page: 268 words, five Q&A rows plus two boxes, about 110 characters per line at 1244px. Fix: two lines per answer; move the caller-facing example into the new agent-desktop drawing.

## P3 (nice to have)
1. Content top edge drifts: y 226 (app1), 240 (arch2), 250 (most). Set one top.
2. harm.html:3 footer source uses a 1380px nowrap box overlapping the counter box (text does not collide now, but edits will). Cap near 1180px.
3. harm.html:2 right panel: two 44px figures with a rotated stamp between them; put the stamp under the first stat only.
4. Cover team block (y 766 to 892) sits tight to the footer counter (y ~1000); lift about 24px.
5. Cover stacks three display statements (128px title, hand underline, 72px Hindi wordmark); consider moving the wordmark beside the waveform.

## What works (keep)
- Cover: one idea, one illustration, honest "Illustration, not data."
- Page 5 "Does not catch" column is the strongest rubric-facing move.
- Page 6 "Closest product ... We have not tested it." is exactly the Principle 2 voice.
- Colour is doubled by shape and word on every state (tick, half-circle, cross, solid versus dashed).
- Footer structure (source left, counter right) is clean and consistent.

## Questions for the owner
1. Is the team one person or several? It decides cover, finale and footer copy (P0).
2. Seven-bar mark on the cover, or drop the commitment (P1-4)?
3. Merge pages 3 and 4 and add a drawn agent-desktop view (P1-1, P1-2)?
