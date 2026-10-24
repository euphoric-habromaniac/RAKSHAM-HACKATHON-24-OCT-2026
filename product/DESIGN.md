---
name: Asli Awaaz
description: A printed pitch sheet for a call-security layer; flat ink-on-paper pages where teal and magenta mean one thing each.
colors:
  paper: "#eaeff3"
  paper-deep: "#d8e0e8"
  paper-raised: "#f6f8fa"
  ink: "#0f1a30"
  ink-soft: "#34405a"
  ink-faint: "#4e5a73"
  rule: "#6f7d94"
  genuine: "#086b62"
  genuine-tint: "#d2eae6"
  synthetic: "#b0105a"
  synthetic-tint: "#f3d3e1"
  on-accent: "#f6f8fa"
  night: "#0e1730"
typography:
  cover-title:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "128px"
    fontWeight: 800
    lineHeight: "122px"
  slide-title:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "68px"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-1px"
  lead:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "44px"
    fontWeight: 500
    lineHeight: "54px"
  body:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "32px"
    fontWeight: 400
    lineHeight: "44px"
  caption:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "26px"
    fontWeight: 400
    lineHeight: "34px"
  label:
    fontFamily: "Archivo Narrow, Arial Narrow, Arial, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: "32px"
    letterSpacing: "0.01em"
  hand-note:
    fontFamily: "Kalam, Comic Sans MS, cursive"
    fontSize: "40px"
    fontWeight: 400
    lineHeight: "44px"
  wordmark-hi:
    fontFamily: "Rozha One, Georgia, serif"
    fontSize: "96px"
    fontWeight: 400
    lineHeight: "110px"
rounded:
  none: "0px"
  sm: "4px"
  md: "12px"
spacing:
  space-1: "8px"
  space-2: "16px"
  space-3: "24px"
  space-4: "32px"
  space-6: "48px"
  space-8: "64px"
  space-16: "128px"
components:
  panel:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "32px"
  panel-quiet:
    backgroundColor: "{colors.paper-deep}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "32px"
  chip-clear:
    backgroundColor: "{colors.genuine-tint}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "6px 12px"
  chip-step-up:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "6px 12px"
  chip-hold:
    backgroundColor: "{colors.synthetic-tint}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "6px 12px"
  stamp:
    backgroundColor: "{colors.paper-deep}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "6px 8px"
  table-header-dark:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper-raised}"
  table-header-light:
    backgroundColor: "{colors.paper-deep}"
    textColor: "{colors.ink}"
---

# Design System: Asli Awaaz

## Overview

**Creative North Star: "The Printed Pitch Sheet"**

Every page is a 1920 by 1080 sheet that will be read as a PDF, so it behaves like paper: cool grey-blue ground, dark navy ink, flat rectangles, hairlines, and nothing that needs motion or a screen to work. Reviewers, fraud-ops staff and engineers read it closely and print it, so the system favours legibility at distance (nothing under 24px) and plain structure over atmosphere.

Colour is a vocabulary, not decoration. Two hues exist, teal for a genuine voice and magenta for a synthetic one, and everything else is ink or grey. The middle verdict, Step up, is deliberately neither: it is ink. Stamps, placeholders and hand notes are neutral because they describe claims, not voices.

The deck is composed per page (a timeline beside a callout, a full-width diagram, a table) with blocks placed at explicit coordinates on a fixed canvas, not a repeated card grid. Imagery is drawn mechanism in inline SVG; no photographs, faces, gradients or shadows.

**Key Characteristics:**
- Cool paper grounds, navy ink, two meaning-bearing accents
- Flat surfaces: 2-3px ink outlines or tint fills, square corners
- Colour always paired with a word and a shape (tick, half-circle, cross; solid vs dashed)
- Archivo 800 titles, Archivo Narrow labels, sparing Kalam hand notes
- Fixed 128px margins, one-line footer with source and section counter

## Colors

A restrained blue-grey paper and navy ink palette with one teal and one magenta that each carry a single meaning.

### Primary
- **Genuine Teal** (`{colors.genuine}`): a real voice, a verified step, the Clear state, the safe path. Text on paper and raised panels; fill for chips, bars and nodes. Its tint (`{colors.genuine-tint}`) is the panel fill behind genuine content.
- **Synthetic Magenta** (`{colors.synthetic}`): a cloned voice, an alert, the Hold state, the escalation path. Its tint (`{colors.synthetic-tint}`) is the panel fill behind it.

### Neutral
- **Cool Paper** (`{colors.paper}`): default page ground.
- **Paper Deep** (`{colors.paper-deep}`): alternate ground, quiet bands, light table headers, stamps.
- **Paper Raised** (`{colors.paper-raised}`): panels and table bodies; also `on-accent` text on solid accent fills.
- **Navy Ink** (`{colors.ink}`): headings, outlines, strong text, the Step up outline and glyph, the dark table header.
- **Ink Soft** (`{colors.ink-soft}`): body copy. **Ink Faint** (`{colors.ink-faint}`): captions, sources, footer.
- **Rule Grey** (`{colors.rule}`): hairlines, dividers, boundaries and stores. Never text.
- **Night** (`{colors.night}`): ground for the one statement page per deck; ink flips to light. Night values for every token live in design-system/tokens.json.

### Named Rules
**The Two Meanings Rule.** Teal and magenta mean genuine and synthetic and nothing else. Never use them as decoration or as a button colour. Boundaries, stores, assumptions, phase blocks and stamps stay ink or grey.
**The Never Alone Rule.** Clear is a tint fill, solid teal outline and tick. Hold is a tint fill, dashed magenta outline and cross. Step up is a solid 3px ink outline on raised paper with a half-filled circle and no teal or magenta. Every chip carries its word.

## Typography

**Display Font:** Archivo (Helvetica Neue, Arial)
**Label Font:** Archivo Narrow (Arial Narrow, Arial)
**Hand Font:** Kalam (Comic Sans MS, cursive). **Mark Font:** Rozha One (Georgia), Hindi wordmark only.

**Character:** A heavy grotesque for titles against a narrow, firm label face; Kalam adds a human "look here" voice used at most twice a page.

### Hierarchy
- **Cover title** (800, 128px, 122px): once per deck.
- **Slide title** (800, 68px, 1.08, -1px tracking): one heading at the top margin of every page, one line, in ink.
- **Lead** (500, 44px, 54px): a one-sentence statement; shipped at 800 weight for figure headlines inside panels.
- **Body** (400, 32px, 44px): the scale value for running text in ink-soft. The build mostly sets running text at 26-28px (see drift note).
- **Caption** (400, 26px, 34px): sources, notes, panel text; the most used size in the build. Footers are 24px.
- **Label** (600-700, 28px or 26px, narrow): chips, diagram labels, row headings, stamps.
- **Hand note** (400, 40px): beside a hand mark, eight words maximum.

### Named Rules
**The 24px Floor Rule.** Nothing is set below 24px; footers sit at exactly 24px.
**The Hindi Once Rule.** The wordmark असली आवाज़ appears on the cover only.

## Layout

A fixed 1920 by 1080 canvas with 128px (`space-16`) margins; the title sits at the top margin on every page and never moves, with 48px (`space-6`) to the content. Blocks are placed at explicit coordinates: timelines, side callouts, columns divided by 3px ink top rules, and full-width diagrams. Rhythm is 8px-based (8/16/24/32/48/64/128). Vary composition between consecutive pages. The footer is one 24px row 64px (`space-8`) from the bottom: source text left, section counter right ("Pitch page 4 of 10", "Architecture page 1 of 3", "Appendix B"). Tables: one dark-header table per run of pages, the rest light-header; question-and-answer pages use ruled lists.

## Elevation & Depth

Flat. No shadows, gradients or glass anywhere in the build (none found in any page). Depth comes from tonal steps (paper, paper-deep, paper-raised), 2-3px outlines, and slight rotation on stamps and hand marks.

### Named Rules
**The Flat Sheet Rule.** Surfaces are rectangles with an outline or a tint, never both a tint and a coloured left edge.

## Shapes

Square by default (0px) for panels, blocks and tables. 4px for chips, stamps and 8px-wide bars that read as pills (the most common radius in the build); 12px for large call-outs and phone-style frames; circles for signal nodes. Outlines are 2px ink, or 3px for emphasis and verdicts. Dashed is reserved for the synthetic path and Hold. Node shapes carry meaning: circle is a signal, square a component, diamond a decision. Hand marks (at most two per page) are wobbly ink strokes.

## Components

### Verdict chip (Clear / Step up / Hold)
Narrow label in ink, glyph left of the word, 4px corners. Clear: genuine tint, solid 3px teal, tick. Step up: raised paper, solid 3px ink, half-filled circle (r=10); also marks the digit challenge L3 only. Hold: synthetic tint, dashed 3px magenta, cross. Never a button; never reuse the Step up look for other boxes.

### Stamp
Small label rotated -3 to +3 degrees (shipped around -1.5), 2px ink-soft outline, paper-deep fill, 4px corners, four words or fewer, neutral colour, set beside (not over) the figure. One wording for targets: "Target, not a result".

### Panels and tables
Raised or deep paper rectangles with 32px padding and a 2px ink outline, or a tint fill. Dark-header table: ink header with light text on a raised body, 2px ink outline, bold first column. Light-header: paper-deep header with ink text.

### Footer and section counter
Plain caption text, 24px, ink-faint (ink-soft on night); source left, counter right; on the cover the counter sits left.

### Cover
Product name at lower left in the cover title; a row of 8px rounded bars at a 16px pitch directly on paper: irregular teal for real speech, equal magenta for generated; caption "Real speech varies. Generated speech is too even."

### Logo mark
Seven vertical bars, four uneven teal and three equal magenta; "Asli Awaaz" in slide-title weight beside it with one bar width of clear space.

## Do's and Don'ts

### Do:
- **Do** set pages on paper, alternate paper-deep, put panels on paper-raised.
- **Do** pair every status colour with a word and a glyph or outline style.
- **Do** give every number a source in a caption or a bracketed placeholder; stamp goals "Target, not a result".
- **Do** label every diagram arrow with what travels along it, and lay text over SVG rather than inside it.

### Don't:
- **Don't** use teal or magenta as decoration, a button colour, or on stamps and placeholders.
- **Don't** add gradients, shadows, glass, photographs, faces, emoji or motion.
- **Don't** set text below 24px.
- **Don't** colour or dash boundaries, stores or assumption boxes; use a solid rule line.
