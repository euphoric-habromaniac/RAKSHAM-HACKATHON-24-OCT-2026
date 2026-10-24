# Sehaj dataset - Stage A (English)

Real vs fake (spoof) speech clips for training a deepfake-voice detector.
All audio is **16 kHz, mono, 16-bit WAV**. Total rows: 15000.

## labels.csv columns
| column | meaning |
|---|---|
| file | path relative to this folder, e.g. `audio/gsm/LA_E_1002903.wav` |
| label | `real` or `fake` |
| label_id | 1 = real, 0 = fake |
| split | `train`, `val` or `test` |
| speaker_id | ASVspoof speaker (e.g. LA_0079) |
| language | `english` now; Hinglish rows will be appended with `hinglish` |
| fake_type | attack code A07..A19 for fakes, empty for real |
| condition | `clean`, `gsm` (GSM phone codec) or `g711u` (landline mu-law) |
| source | `asvspoof2019` |
| orig_label | original ASVspoof label, `bonafide` or `spoof` |

## Splits
Splits are **speaker-disjoint** (seeded, about 70/15/15 by speakers): a speaker, and every
variant (clean/gsm/g711u) of an utterance, lives in exactly one split. Never mix them,
warna test scores jhoothe ho jayenge.

## Counts (rows)
Per split and label:

| split | fake | real |
|---|---|---|
| test | 816 | 1245 |
| train | 5487 | 5088 |
| val | 1197 | 1167 |

Per split and condition:

| split | clean | g711u | gsm |
|---|---|---|---|
| test | 687 | 687 | 687 |
| train | 3525 | 3525 | 3525 |
| val | 788 | 788 | 788 |

Per condition and label:

| condition | fake | real |
|---|---|---|
| clean | 2500 | 2500 |
| g711u | 2500 | 2500 |
| gsm | 2500 | 2500 |

## Loading
```python
import pandas as pd, soundfile as sf
df = pd.read_csv("labels.csv")
train = df[(df.split == "train") & (df.language == "english")]
x, sr = sf.read(train.file.iloc[0])   # sr == 16000
y = train.label_id                    # 1 = real, 0 = fake
```

## Honest limits
- English only. No Hinglish yet (rows will be appended with `language=hinglish`).
- Fakes are the ASVspoof 2019 LA attacks (A07..A19) only; a new TTS/voice-cloning system may behave differently.
- gsm and g711u are *simulated* phone channels (codec applied in software), not real calls.
- Scores on this data do not promise the same accuracy on real calls.

## Hinglish rows (language = `hinglish`)
1,800 rows = 3 speakers x 100 script sentences x {real, fake} x {clean, gsm, g711u}. Files are in
`audio/hinglish/<condition>/<speaker_id>_<NNN>_<real|fake>.wav` (NNN = sentence number 1..100).
- **real**: consented recordings (Asli Awaaz recorder), 16 kHz mono. `source=asli_awaaz`, `orig_label=bonafide`.
- **fake**: voice clones of the same speaker saying the same sentence (Coqui XTTS-v2, fine-tuned on 10-20
  of that speaker's clips; `fake_type` = generator tag). `orig_label=spoof`. Consent covers cloning and spoof testing.
- `gsm` / `g711u` were made with `product/degrade/telephony.py` (same code as the English set).
- The 100 sentences mix Hindi (Devanagari), English and Hinglish (Roman script), all in bank-call topics;
  all are labelled `hinglish` because the set is one code-mixed bank-call domain.
- **Splits**: only 3 speakers. `test` = YASH CHAUHAN (speaker-disjoint). `train`/`val` = KUSHAGRA + PRANJAL KUMAR,
  val = sentence numbers divisible by 5. So **val shares speakers with train** (different sentences) - it is
  not speaker-disjoint; trust `test` for generalisation.
- Fakes are one generator family (XTTS-v2) and speakers are young Hindi-belt males, so results do not cover
  other cloning tools, genders or accents. Fake text = real text (paired), so a model can compare pairs.
