ASLI AWAAZ - RECORDINGS

FILES
  <Speaker Name>/N.wav  one clip, 16 kHz mono 16-bit. N is the sentence number (1..100) in SPEAKER_SCRIPT.txt. A redo overwrites it.
  <Speaker Name>/profile.json  name, speaker_id (random, assigned once), age band, gender, accent group, device, consent language.
  <Speaker Name>/consent.json  consent record written when the speaker signs (metadata.signed_history keeps every signing).
  manifest_master.csv  one row per saved clip, rewritten after every clip. The first 9 columns are the ingest columns.
  people.csv  one row per speaker.
  _session_log.csv  append-only event log.
  SPEAKER_SCRIPT.txt, prompts.csv  the 100 sentences, numbered.
  README.txt  this file.
  Which clips are done is decided by the files on disk: a clip counts as done when N.wav exists.

COLUMNS of manifest_master.csv
    speaker_id: random 8-character id, assigned once when the profile is created
    phrase_id: prompt id, e.g. p001_hi (hi/en/hg = language)
    language: prompt language: hindi, english or hinglish
    accent_group: accent / region group chosen by the speaker
    age_band: age band chosen by the speaker
    gender: gender chosen by the speaker (may be empty)
    device: device / microphone typed by the speaker
    duration_s: clip length in seconds
    file: clip path relative to the recordings folder: <Speaker Name>/N.wav
    full_name: full name typed by the speaker
    sentence_number: N, the number of the sentence in the script
    prompt_text: the exact text shown
    topic: prompt topic
    sample_rate: Hz
    channels: number of channels
    bit_depth: bits per sample
    peak: highest absolute sample (0-1)
    rms_dbfs: average level in dB below full scale
    clipped: true if the clip hit full scale
    warnings: warnings noticed on the take (may be empty)
    recorded_at_iso: time the clip was saved (UTC)
    consent_file: consent JSON of this speaker

COLUMNS of people.csv
    speaker_id: random 8-character id, assigned once when the profile is created
    full_name: full name typed by the speaker
    name_key: normalised name: same key = same person
    age_band: age band chosen by the speaker
    gender: gender chosen by the speaker (may be empty)
    accent_group: accent / region group chosen by the speaker
    device: device / microphone typed by the speaker
    consent_language: language of the consent form signed
    first_seen_iso: profile creation time
    last_seen_iso: latest signing or clip time
    clips_total: N.wav files on disk for this speaker

COLUMNS of _session_log.csv
    timestamp: event time (UTC)
    event: profile_created, continued, clip_saved, clip_redo, zip_built or save_failed
    speaker: full name
    sentence_number: N, the number of the sentence in the script
    detail: free text
