# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary readers: hackathon reviewers (RAKSHAM, IIT Delhi x Amazon, Problem Statement 01) scoring a PDF against a 100-point rubric, plus fraud-ops staff and engineers at banks who would operate or integrate the product. They read the deck as a PDF, printed-sheet style, not as a web page. Product operators: helpline agents, analysts, fraud head.

## Product Purpose
Asli Awaaz ("real voice") is a bank-side layer that scores helpline calls for the risk of a cloned voice, and steps up (asks for extra proof) rather than auto-blocking on one weak signal. Bands: Clear, Step up, Hold. Runs inside the bank network. This repo is the Round 1 submission: a 10-page pitch, 3 architecture pages, Appendix A to D, due 12 Oct 2026 23:59 IST.

## Positioning
Layered decision (speaker match, synthetic-speech check, random-digit challenge, call-context rules, app confirmation plus analyst) that states what each layer cannot catch, e.g. the digit challenge stops pre-recorded clones but not a live voice changer.

## Capabilities and Constraints
- Deck is 1920x1080 HTML pages exported to PDF; no motion; text at least 24px; inline styles only.
- All numbers are sourced, labelled, or a bracketed placeholder. No accuracy claim before a test run; goals carry the stamp "Target, not a result".
- The deck must never say code was written before the finale.
- Open placeholders only the owner can fill: teammate names, [N]/[M], [x] targets, [Name] roles, [Bank retention policy].

## Brand Commitments
Name "Asli Awaaz"; Hindi wordmark असली आवाज़ appears once. Seven-bar logo mark (four uneven genuine-teal, three equal synthetic-magenta). Full rules in design-system/README.md and design-system/tokens.json: teal = genuine/Clear only, magenta = synthetic/Hold only, flat surfaces, no gradients/shadows, Archivo / Archivo Narrow / Kalam / Rozha One.

## Evidence on Hand
Sourced figures listed in handoff/HANDOFF.md. No measured baseline yet; no testimonials or customers. Do not fabricate results.

## Product Principles
1. Step up, never block on one weak signal.
2. Say what the system cannot do in the same breath as what it does.
3. Every number has a source or a label.
4. Colour never works alone: pair with shape and word.
5. Read as a printed pitch sheet.

## Accessibility & Inclusion
Colour is never the only carrier of meaning; minimum 24px text; sufficient contrast in PDF and print.
