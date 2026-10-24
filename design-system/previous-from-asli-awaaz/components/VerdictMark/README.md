VerdictMark is a chip that shows the outcome of a call with a word, a shape and an outline together. It has three states.

Provide the word and one state. Text is `label` in `ink`. The glyph sits left of the word.

- Clear: `genuine-tint` fill, a solid 3px `genuine` outline, a tick glyph. Use it when the call passes: the voice is judged real and the safe path runs.
- Step up: `paper-raised` fill, a solid 3px `ink` outline, a half-filled circle glyph in `ink` (circle r=10, 3px stroke, left half filled). Use it when the score is not enough to clear the call and an extra proof is asked. It is also the marker for the digit challenge (L3), which runs only on Step up.
- Hold: `synthetic-tint` fill, a dashed 3px `synthetic` outline, a cross glyph. Use it when the call is likely synthetic or an alert fires, and the call goes to an analyst.

Step up has no teal or magenta in it. It is neither a pass nor an alert, so it stays in ink.

Use it in tables and diagrams wherever an outcome is shown. Do not rely on the colour: the glyph and the outline style must stay, and each state keeps its word. Do not use the Step up look on other boxes (fairness, a live voice changer, lifecycle states, fusion); those are plain boxes. Do not use any state as a button.
