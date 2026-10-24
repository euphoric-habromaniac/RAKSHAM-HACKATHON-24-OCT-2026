Nine line icons on a 48 unit grid, 3px strokes with round caps, for status and flow labels. They are drawn for this system; there is no external icon set. Each icon comes in a day file for `paper` grounds and a night file for the `night` ground. The drawing is the same in both.

Day files, for `paper`, `paper-deep` and `paper-raised`:

- `call.svg`, `step-up.svg`, `hold.svg`, `analyst.svg`, `evidence.svg`, `lock.svg`: one ink, #0F1A30.
- `app-confirm.svg`: ink #0F1A30 with a teal #086B62 tick.
- `voice-match.svg`: ink circle with a teal #086B62 tick. Means a real voice matched.
- `synthetic.svg`: one colour, magenta #B0105A: a dashed circle with a cross. Means a likely cloned voice.

Night files, for the `night` ground. Strokes are #E8EDF3, teal is #4CCFBF and magenta is #FF7BAE, wherever the day file uses ink, teal or magenta:

- `call-night.svg`, `step-up-night.svg`, `hold-night.svg`, `analyst-night.svg`, `evidence-night.svg`, `lock-night.svg`
- `app-confirm-night.svg`, `voice-match-night.svg`, `synthetic-night.svg`

Use the day file on a light ground and the night file on the `night` ground. Do not put a day icon on `night` or a night icon on `paper`: the ink does not read.

Pair every icon with a word. Use `voice-match` and `synthetic` only for those two meanings, since teal and magenta mean a real voice and a cloned voice. Teal appears in two icons (`voice-match` and the tick in `app-confirm`) and magenta in one (`synthetic`). Every other stroke is ink. `step-up` is a rising stair and stays ink; the half-filled circle belongs to the Step up chip (see VerdictMark).

The icons are SVGs shown through `<img>`, so the colours are fixed in the file. Make a new file for another ground.
