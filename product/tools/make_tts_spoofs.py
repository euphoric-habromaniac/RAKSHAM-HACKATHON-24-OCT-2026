"""Generate Hinglish TTS fake clips with Windows SAPI (System.Speech via PowerShell). No extra packages.

    python -m tools.make_tts_spoofs --list-voices
    python -m tools.make_tts_spoofs [--incoming data/hinglish_incoming/tts] [--consent-dir data/consent]

Needs a Hindi (hi-IN) or Indian English (en-IN) voice: Windows Settings > Time & language >
Speech > Add voices > install 'Hindi'. Output follows tools/ingest_hinglish.py:
    <incoming>/spoof/tts_<voice>__<phrase_id>.wav     (speaker_id = tts_<voice>)
plus a consent record data/consent/tts_<voice>.json for that synthetic speaker.
Then: python -m tools.ingest_hinglish --incoming data/hinglish_incoming/tts --out data/hinglish
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_JSON = ROOT / "tools/recorder/prompts.json"
CULTURES = ("hi-IN", "en-IN")
NO_VOICE_MSG = ("No Hindi / Indian-English SAPI voice installed. Install one in Windows Settings > "
                "Time & language > Speech > Add voices ('Hindi'), then rerun with --list-voices.")


def read_prompts(text: str) -> list:
    """[(phrase_id, lang, text)] from the contents of prompts.json; lang is the id suffix hi|en|hg."""
    return [(p["id"], p["id"].rsplit("_", 1)[1], p["text"]) for p in json.loads(text)]


def voice_slug(name: str) -> str:
    """Safe id part: letters, digits and single '-' only (ingest splits file names on '__')."""
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")


def speaker_id(voice: str) -> str:
    return f"tts_{voice_slug(voice)}"


def clip_name(voice: str, phrase_id: str) -> str:
    return f"{speaker_id(voice)}__{phrase_id}.wav"


def phrases_for(culture: str, prompts: list) -> list:
    """hi-IN voices read Devanagari; en-IN voices read English + Hinglish (roman)."""
    langs = {"hi-IN": {"hi"}}.get(culture, {"en", "hg"})
    return [p for p in prompts if p[1] in langs]


def consent_record(voice: str, now: str = "") -> dict:
    return {"speaker_id": speaker_id(voice), "full_name": f"Synthetic voice {voice}", "signed": True,
            "signed_at": now or datetime.now(timezone.utc).isoformat(),
            "allow_recording": True, "allow_spoof_testing": True, "allow_voice_cloning": False,
            "retention_days": 3650,
            "metadata": {"note": "synthetic voice, no real person", "language": "hinglish"}}


def write_consent(voice: str, consent_dir: Path) -> Path:
    consent_dir.mkdir(parents=True, exist_ok=True)
    p = consent_dir / f"{speaker_id(voice)}.json"
    p.write_text(json.dumps(consent_record(voice), indent=2), encoding="utf-8")
    return p


# ------------------------------------------------------------ SAPI (not unit-tested)
def _ps(script: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "PowerShell failed")
    return r.stdout


def list_voices() -> list:
    """[(name, culture)] of installed SAPI voices."""
    out = _ps("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              "$s.GetInstalledVoices()|%{$_.VoiceInfo.Name+'|'+$_.VoiceInfo.Culture.Name}")
    return [tuple(l.strip().split("|")) for l in out.splitlines() if "|" in l]


_SYNTH = ("Add-Type -AssemblyName System.Speech;$j=Get-Content -Raw -Encoding UTF8 '{jobs}'|ConvertFrom-Json;"
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;$s.SelectVoice('{voice}');"
          "$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
          "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono);"
          "foreach($x in $j){$s.SetOutputToWaveFile($x.path,$f);$s.Speak($x.text);$s.SetOutputToNull()}")


def synthesize(voice: str, jobs: list) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump([{"path": str(p.resolve()), "text": t} for p, t in jobs], f, ensure_ascii=False)
    try:
        _ps(_SYNTH.format(jobs=f.name, voice=voice.replace("'", "''")))
    finally:
        Path(f.name).unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--incoming", default="data/hinglish_incoming/tts")
    ap.add_argument("--consent-dir", default="data/consent")
    a = ap.parse_args()
    voices = list_voices()
    if a.list_voices:
        print("\n".join(f"{n}\t{c}" for n, c in voices) or "(no voices)")
        return 0
    usable = [(n, c) for n, c in voices if c in CULTURES]
    if not usable:
        print(NO_VOICE_MSG, file=sys.stderr)
        return 1
    prompts = read_prompts(PROMPTS_JSON.read_text(encoding="utf-8"))
    spoof = Path(a.incoming) / "spoof"
    spoof.mkdir(parents=True, exist_ok=True)
    for name, culture in usable:
        jobs = [(spoof / clip_name(name, pid), text) for pid, _, text in phrases_for(culture, prompts)]
        synthesize(name, jobs)
        print(f"{name}: wrote {write_consent(name, Path(a.consent_dir))} and {len(jobs)} clips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
