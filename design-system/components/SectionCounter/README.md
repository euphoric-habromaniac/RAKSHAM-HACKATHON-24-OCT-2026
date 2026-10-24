SectionCounter is the page position in the footer row: plain text, right-aligned, with the source text on the left. It replaces the old tick strip.

Provide the section and the page. The text reads "Pitch page N of 10" for pitch pages, "Architecture page N of 3" for architecture pages, and "Appendix A", "Appendix B" or "Appendix C" for appendix pages. Set it in `caption` at 24px, in `ink-faint` on paper grounds and `ink-soft` on the `night` ground. No colour, no icon, no ticks.

Use it once per page, in the one 24px footer row at `space-8` from the bottom edge, right-aligned to the right margin. The source text sits at the left margin on the same row, on one line. If a page has no source, leave the left side empty. Do not repeat the page position inside the source text. On the cover, the counter sits at the left margin instead.
