# Baseline results: AASIST on ASVspoof 2019 LA eval

These are pretrained-model results without fine-tuning: the released AASIST weights were scored as they are on clean and telephone-degraded audio.

| Condition | n_bonafide | n_spoof | EER % | Change vs clean16k (points) |
|---|---:|---:|---:|---:|
| clean16k | 2500 | 2500 | 0.92 |  |
| pstn8k | 2500 | 2500 | 1.12 | +0.20 |
| g711u | 2500 | 2500 | 1.08 | +0.16 |
| g711a | 2500 | 2500 | 1.12 | +0.20 |
| gsm | 2500 | 2500 | 7.36 | +6.44 |
| amrnb | 2500 | 2500 | 4.80 | +3.88 |
| opus8k | 2500 | 2500 | 6.48 | +5.56 |
| loss5 | 2500 | 2500 | 4.20 | +3.28 |
| loss10 | 2500 | 2500 | 6.48 | +5.56 |
| noise20 | 2500 | 2500 | 4.40 | +3.48 |
| noise10 | 2500 | 2500 | 15.12 | +14.20 |
