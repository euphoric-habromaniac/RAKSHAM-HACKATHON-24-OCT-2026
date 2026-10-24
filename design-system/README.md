Asli Awaaz is a call-security layer that scores bank helpline calls for the risk of a cloned voice. This system styles its pitch pages: a 1920 by 1080 deck that is read as a PDF by reviewers, fraud-ops staff and engineers. Build every page like a printed pitch sheet, not a web page.

## Content fundamentals

- Write plain sentences in sentence case and active voice. Say what the product does to a call: "scores", "asks", "holds for review".
- Name the person acting: "agent", "customer", "analyst". Do not write "users".
- Give every number a source or a label. A source goes in `caption` under the figure. A goal gets the Stamp "Target, not a result". A number nobody has supplied is a bracketed placeholder such as [needs number], set in `ink` with a dashed `ink` underline.
- Claim no accuracy before a test run. Write "we measure EER on telephone-degraded audio" instead of a percentage.
- Titles name the topic as a noun phrase ("Detection layers", "What we collect") or state one short fact. Use one grammar through the deck. A title fits one line: about 44 characters at 68px. A plain statement beats an "X, Y" construction. No questions, no exclamation marks, no emoji.
- Say "page", not "slide", in all visible text. Point to "page N" for pitch pages (1 to 10), "architecture page N" and "Appendix A", "Appendix B" or "Appendix C".
- Hindi appears once, as the wordmark असली आवाज़ ("real voice"), set in `wordmark-hi`. Everything else is English. Hinglish appears only as the name of a test set.
- Say what the system cannot do in the same breath as what it does. Example: "The digit challenge stops pre-recorded clones. A live voice changer passes it, so the audio check and the app confirmation cover that case."

## Visual foundations

**Colour.** Set pages on `paper`, alternate with `paper-deep`, and put panels on `paper-raised`. Text is `ink` for headings, `ink-soft` for body, `ink-faint` for captions. Hairlines use `rule`.

Two hues carry meaning and nothing else. `genuine` (teal) is for a genuine voice, the Clear state and the safe path. `synthetic` (magenta) is for a synthetic voice, the Hold state and alerts. Everything else is ink or grey: stamps, hand notes, placeholders, boundaries, stores, phase blocks and decoration. A boundary, a store or an assumption box is a solid `rule` line, never dashed and never coloured. Never use teal or magenta as decoration or as a button colour. Panels behind them use `genuine-tint` and `synthetic-tint`. Text on a solid accent fill uses `on-accent`. One statement page per deck uses the `night` theme: `paper` as ground, `ink` for text.

**Colour never works alone.** Clear is a `genuine-tint` fill, a solid `genuine` outline and a tick. Hold is a `synthetic-tint` fill, a dashed `synthetic` outline and a cross. A genuine path is a solid line with a tick mark. A synthetic path is a dashed line with a cross mark. Every chip carries a word as well as its colour.

**Step up marker.** Step up is the middle state: the score is not enough to clear the call, so an extra proof is asked. It is a solid 3px `ink` outline on a `paper-raised` fill, a half-filled circle glyph in `ink` (circle r=10, 3px stroke, left half filled) and the word "Step up". No teal and no magenta. Use it only for the Step up band and for L3, the digit challenge, which runs only on Step up. Other boxes (fairness, a live voice changer, lifecycle states, fusion) are plain boxes. See VerdictMark.

**Type.** Archivo (`display`) at 800 for titles, 400 and 500 for text. Archivo Narrow (`narrow`, style `label`) for chips, diagram labels and stamps. Kalam (`hand`, style `hand-note`) for at most two handwritten notes per page, eight words each. Rozha One (`mark`) for the Hindi wordmark only. Use the five sizes in the scale (128, 68, 44, 32, 26) and the 40px hand note; add none. Nothing is set below 24px.

**Layout.** The canvas is 1920 by 1080 with `space-16` margins. A title sits at the top margin on every page and never moves. Footer: one 24px row at `space-8` from the bottom, with the source text on the left and the section counter on the right (see SectionCounter). The counter is plain text such as "Pitch page 4 of 10", "Architecture page 1 of 3" or "Appendix B". The source line never repeats the page position. Vary the composition between pages: a left-heavy panel on one, a full-width diagram on the next, a table with a tall callout after that. Do not repeat the same card grid on consecutive pages.

**Tables.** Use one dark-header table per run of pages: an `ink` header row with light text (the night value of `ink`) on a `paper-raised` body, a 2px `ink` outline, first column bold. Every other table in the run has a light header: a `paper-deep` header row with `ink` text. Where a page is really a set of questions and answers, use a ruled list instead: the question in `ink`, the answer in `ink-soft`, rows divided by solid `rule` hairlines, no outline and no fill.

**Flat surfaces.** No gradients, no shadows, no glass. Panels are rectangles at `radius-0` with a 2px `ink` outline or a tint fill, never both a tint and a coloured left edge. Chips and stamps use `radius-sm`.

**Hand marks.** Use at most two wobbly hand-drawn marks per page (an underline, a circle, an arrow). They point at the one thing the reviewer should not miss. Hand marks are `ink`. Use `genuine` or `synthetic` only when the thing marked is itself a genuine-voice item or a cloned-voice, Hold or alert item.

**Stamps.** A stamp names the status of a claim. Use one wording for targets, "Target, not a result". Keep a stamp to four words or fewer. Keep it neutral: `ink-soft` or `ink` outline and text, never teal or magenta. Rotate it between -3 and +3 degrees.

**Diagrams.** Draw in inline SVG with flat fills from the tokens. Put every label in text laid over the drawing, since fonts do not load inside an SVG. Label every arrow with what travels along it.

**Imagery.** No photographs, no stock illustration, no faces. Where a page needs a picture, draw the mechanism.

**Motion.** None. The deck is exported to PDF.

## Iconography

The product mark is seven vertical bars: four uneven in `genuine`, three equal in `synthetic`. Use the files in the Logos group: full colour on `paper`, the night version on `night`, a mono version where colour is unavailable. Set the name "Asli Awaaz" in `slide-title` weight 800 beside it, one bar width of clear space on every side.

The Icons group holds nine line icons (call, voice-match, synthetic, step-up, hold, app-confirm, analyst, evidence, lock) drawn for this system. Each has a day file for `paper` grounds and a night file for the `night` ground (`call-night.svg` and so on). Use no other icon set and no emoji. Pair every icon with a word. `voice-match` and `synthetic` carry only those two meanings. Status glyphs inside diagrams are drawn as a tick (3px stroke, `genuine`), a cross (3px stroke, `synthetic`) and the half-filled circle (`ink`) for Step up. Node shapes carry meaning: a circle is a signal, a square is a component, a diamond is a decision.
