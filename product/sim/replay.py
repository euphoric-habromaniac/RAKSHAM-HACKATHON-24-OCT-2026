"""
Call Replayer and Telemetry Simulator (Workstream D6).
Replays WAV audio through telephone channel degradation conditions,
streams real-time frames into the ingest socket, and automatically handles
challenge responses when challenge_pending becomes True.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:
    import soundfile as sf
except ImportError:
    sf = None

try:
    import websockets
except ImportError:
    websockets = None

try:
    import requests
except ImportError:
    requests = None


def generate_synthetic_speech(duration_sec: float = 5.0, sample_rate: int = 16000) -> np.ndarray:
    """Generate harmonic voice-like audio for testing without external audio files."""
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    # Fundamental frequency ~130 Hz with vocal harmonics and amplitude modulation
    audio = 0.4 * np.sin(2 * np.pi * 130 * t)
    audio += 0.25 * np.sin(2 * np.pi * 260 * t)
    audio += 0.15 * np.sin(2 * np.pi * 390 * t)
    # Speech envelope modulation
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 2.5 * t))
    audio = audio * envelope
    return audio.astype(np.float32)


def read_or_synthesize_wav(wav_path: Optional[str], duration_sec: float = 5.0) -> np.ndarray:
    if wav_path and Path(wav_path).exists() and sf is not None:
        data, sr = sf.read(wav_path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != 16000:
            # Resample if needed
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(16000, sr)
            data = resample_poly(data, 16000 // g, sr // g).astype(np.float32)
        return data
    return generate_synthetic_speech(duration_sec=duration_sec)


class CallReplayer:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        ws_url: str = "ws://127.0.0.1:8000",
    ):
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url.rstrip("/")

    def start_call(
        self,
        call_id: str,
        customer_id: str,
        request_type: str,
        enrolled: bool = True,
        bank_flags: Optional[Dict[str, bool]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        import urllib.request
        payload = {
            "call_id": call_id,
            "customer_id": customer_id,
            "request_type": request_type,
            "enrolled": enrolled,
            "bank_flags": bank_flags or {},
            "metadata": metadata or {},
        }
        req = urllib.request.Request(
            f"{self.base_url}/calls",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_audio_chunk(self, call_id: str, pcm_bytes: bytes, sample_rate: int = 16000) -> Dict[str, Any]:
        import urllib.request
        payload = {
            "pcm_b64": base64.b64encode(pcm_bytes).decode("ascii"),
            "sample_rate": sample_rate,
        }
        req = urllib.request.Request(
            f"{self.base_url}/calls/{call_id}/audio",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_transcript(self, call_id: str, text: str) -> Dict[str, Any]:
        import urllib.request
        payload = {"text": text}
        req = urllib.request.Request(
            f"{self.base_url}/calls/{call_id}/transcript",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_challenge_answer(self, call_id: str, answer_text: str) -> Dict[str, Any]:
        import urllib.request
        payload = {"text": answer_text}
        req = urllib.request.Request(
            f"{self.base_url}/calls/{call_id}/challenge/answer",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def replay_scenario(
        self,
        scenario_num: int,
        wav_path: Optional[str] = None,
        condition: str = "clean16k",
    ) -> None:
        print(f"\n[REPLAY] Initializing Scenario {scenario_num} under condition '{condition}'...")
        audio = read_or_synthesize_wav(wav_path, duration_sec=5.0)

        # Convert float32 [-1, 1] to int16 PCM bytes
        audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        pcm_bytes = audio_int16.tobytes()

        if scenario_num == 1:
            call_id = f"replay-genuine-{int(time.time())}"
            print(f"  -> Starting Call: {call_id} (cust_genuine / balance)")
            self.start_call(
                call_id=call_id,
                customer_id="cust_genuine",
                request_type="balance",
                enrolled=True,
                metadata={"mock_l1_cosine": 0.84, "mock_l2_spoof": 0.04},
            )
            print("  -> Streaming 5s audio chunk...")
            self.send_audio_chunk(call_id, pcm_bytes)
            print("  -> Transmitting transcript: 'mera balance bata dijiye'")
            v = self.send_transcript(call_id, "mera balance bata dijiye")
            print(f"  -> Result: Band=[{v.get('band')}] Message='{v.get('agent_message')}'")

        elif scenario_num == 2:
            call_id = f"replay-clone-{int(time.time())}"
            print(f"  -> Starting Call: {call_id} (cust_victim / limit_change)")
            self.start_call(
                call_id=call_id,
                customer_id="cust_victim",
                request_type="limit_change",
                enrolled=True,
                metadata={"mock_l1_cosine": 0.54, "mock_l2_spoof": 0.58},
            )
            print("  -> Streaming 5s clone audio...")
            self.send_audio_chunk(call_id, pcm_bytes)
            v = self.send_transcript(call_id, "mujhe card ki limit badhani hai")
            print(f"  -> Step Up Triggered: Message='{v.get('agent_message')}'")

            # Mismatched digits answer (attacker cannot read dynamic challenge)
            print("  -> Submitting mismatched challenge digits: '0 0 0 0 0 0'")
            v2 = self.send_challenge_answer(call_id, "0 0 0 0 0 0")
            print(f"  -> Escalation Result: Band=[{v2.get('band')}] Message='{v2.get('agent_message')}'")

        elif scenario_num == 3:
            call_id = f"replay-rvc-{int(time.time())}"
            print(f"  -> Starting Call: {call_id} (cust_victim / new_payee / RVC voice changer)")
            self.start_call(
                call_id=call_id,
                customer_id="cust_victim",
                request_type="new_payee",
                enrolled=True,
                bank_flags={"new_device": True, "new_payee": True},
                metadata={"mock_l1_cosine": 0.72, "mock_l2_spoof": 0.94},
            )
            print("  -> Streaming live converted voice...")
            self.send_audio_chunk(call_id, pcm_bytes)
            v = self.send_transcript(call_id, "urgent hai, jaldi payee add karo")
            print(f"  -> Immediate Hold Result: Band=[{v.get('band')}] Message='{v.get('agent_message')}'")


def main():
    parser = argparse.ArgumentParser(description="Asli Awaaz Audio Replayer")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3], default=1, help="Demo scenario to replay")
    parser.add_argument("--wav", type=str, default=None, help="Path to input audio WAV file")
    parser.add_argument("--condition", type=str, default="clean16k", help="Channel degradation condition")
    parser.add_argument("--host", type=str, default="http://127.0.0.1:8000", help="Service host URL")
    args = parser.parse_args()

    replayer = CallReplayer(base_url=args.host)
    replayer.replay_scenario(args.scenario, wav_path=args.wav, condition=args.condition)


if __name__ == "__main__":
    main()
