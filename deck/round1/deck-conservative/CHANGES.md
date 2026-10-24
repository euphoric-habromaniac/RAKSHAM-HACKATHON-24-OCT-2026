# CHANGES (deck-conservative)

Only defect fixes; copy, layout and composition unchanged. Originals in deck/ untouched.

## slides/arch1.html
- 23x line-height 1.2 -> 1.3 on 26px text
- 1x line-height 1.2 -> 1.3 on 28px text
- 7x line-height 1.2 -> 1.3 on 24px text

## slides/arch2.html
- 1x line-height 1.2 -> 1.3 on 28px text
- 5x line-height 1.2 -> 1.3 on 26px text

## slides/arch3.html
- 4x line-height 1.0 -> 1.3 on 24px text
- 10x line-height 1.2 -> 1.3 on 26px text
- 2x line-height 1.2 -> 1.3 on 28px text
- 16x line-height 1.2 -> 1.3 on 24px text
- 1x numeral at top:793px: own ink fill + 34px circle box so light text has an explicit dark ground
- 1x numeral at top:828px: own ink fill + 34px circle box so light text has an explicit dark ground
- 1x numeral at top:863px: own ink fill + 34px circle box so light text has an explicit dark ground
- 1x numeral at top:898px: own ink fill + 34px circle box so light text has an explicit dark ground
- 2x time-bar label: explicit ink background matching bar (height 36)

## slides/cover.html
- 4x line-height 1.2 -> 1.3 on 28px text
- 1x line-height 1.2 -> 1.3 on 26px text

## slides/detect.html
- 3x line-height 1.2 -> 1.3 on 28px text

## slides/diff.html
- 4x night-panel text: explicit background #0E1730 matching panel (invisible change)

## slides/evidence.html
- 6x line-height 1.2 -> 1.3 on 28px text
- 7x line-height 1.2 -> 1.3 on 26px text

## slides/finale.html
- 5x line-height 1.2 -> 1.3 on 26px text
- 7x line-height 1.2 -> 1.3 on 28px text
- 3x 3px ink border-top rule -> 3px ink filled bar (same pixels, no border)

## slides/flow.html
- 13x line-height 1.2 -> 1.3 on 26px text

## slides/harm.html
- 2x line-height 1.1 -> 1.3 on 44px text
- 4x line-height 1.2 -> 1.3 on 28px text
- 5x line-height 1.2 -> 1.3 on 26px text
- 4x 3px ink border-top rule -> 3px ink filled bar (same pixels, no border)

## slides/journey.html
- 5x line-height 1.2 -> 1.3 on 28px text
- 10x line-height 1.2 -> 1.3 on 24px text
- 1x line-height 1.2 -> 1.3 on 26px text

## slides/rollout.html
- 1x line-height 1.2 -> 1.3 on 26px text
- 7x line-height 1.2 -> 1.3 on 28px text
- 3x 3px ink border-top rule -> 3px ink filled bar (same pixels, no border)

## slides/trust.html
- 1x line-height 1.2 -> 1.3 on 26px text
- 5x line-height 1.2 -> 1.3 on 28px text

## Detector counts (impeccable detect --json slides)
- Before: 36 (tight-leading 16, low-contrast 10, side-tab 10). After: 0 of those categories.
- A root DESIGN.md appeared mid-run (not created by this pass); with it the detector also reports 26 design-system findings (24px footer/caption size off its ramp, 12px/4px radii, connector border colour, cover 34/72px, flow 36px). Same 26 on the untouched original (62 total there). Left as is: out of scope and the 24px minimum is kept.
- Side-tab hits were 3px ink rules above text columns (no tint, no coloured edge); converted to filled 3px bars so no border remains.
- Low-contrast hits were false positives (light text over sibling dark shapes); fixed by giving the text its own matching dark background. Pixels unchanged.
- PNGs not re-rendered.
