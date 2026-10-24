# Classic-ML baseline (MFCC mean+std, 20 MFCC + delta)

| model | language | condition | split | EER % | acc % | n |
|---|---|---|---|---|---|---|
| RandomForest | english | clean | test | 10.87 | 90.0 | 687 |
| RandomForest | english | clean | val | 8.88 | 92.3 | 788 |
| RandomForest | english | g711u | test | 10.94 | 88.8 | 687 |
| RandomForest | english | g711u | val | 9.26 | 91.6 | 788 |
| RandomForest | english | gsm | test | 11.91 | 88.1 | 687 |
| RandomForest | english | gsm | val | 9.39 | 92.0 | 788 |
| MLP | english | clean | test | 8.87 | 87.5 | 687 |
| MLP | english | clean | val | 7.49 | 91.4 | 788 |
| MLP | english | g711u | test | 6.99 | 91.3 | 687 |
| MLP | english | g711u | val | 7.99 | 91.1 | 788 |
| MLP | english | gsm | test | 8.44 | 89.8 | 687 |
| MLP | english | gsm | val | 8.25 | 91.2 | 788 |

Notes:
- Trained on split=train, language=english only (Hinglish is never trained on unless `--include-hinglish-train`); Hinglish rows are reported separately by language.
- Reference: AASIST pretrained, on the same kind of subset, scored clean 0.92% EER and gsm 7.36% EER (results/SUMMARY.md).
- Not the same subset split or training, so treat as a rough yardstick, not a head-to-head.
