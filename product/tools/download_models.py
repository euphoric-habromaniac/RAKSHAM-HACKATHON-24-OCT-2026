"""
Model Weights & Checkpoint Fetcher for Kushagra's RTX 4060 Laptop.
Downloads and verifies required speech biometrics, anti-spoofing, and ASR checkpoints.
Run: python tools/download_models.py [--skip-large]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path("models/weights")

DOWNLOADS = {
    # 1. Clova AASIST Baseline Weights
    "aasist_baseline.pth": {
        "url": "https://github.com/clovaai/aasist/raw/main/models/weights/AASIST.pth",
        "description": "AASIST Raw Spectro-Temporal Graph Attention Network",
        "size_mb": 1.2,
    },
    # 2. HuBERT base for RVC feature extraction
    "hubert_base.pt": {
        "url": "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt",
        "description": "HuBERT Soft Speech Feature Extractor for RVC V2",
        "size_mb": 178.0,
    },
    # 3. RVC V2 Pretrained Base Models
    "rvc_f0D40k.pth": {
        "url": "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/pretrained_v2/f0D40k.pth",
        "description": "RVC V2 Discriminator 40k",
        "size_mb": 55.0,
    },
    "rvc_f0G40k.pth": {
        "url": "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/pretrained_v2/f0G40k.pth",
        "description": "RVC V2 Generator 40k",
        "size_mb": 55.0,
    },
}


def download_file(url: str, dest_path: Path, desc: str, max_retries: int = 5) -> None:
    print(f"\n[DOWNLOAD] {desc}")
    print(f"  URL: {url}")
    print(f"  Destination: {dest_path}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if dest_path.exists() and dest_path.stat().st_size > 1024:
        print(f"  [CACHE] File already exists ({dest_path.stat().st_size / 1e6:.1f} MB). Skipping.")
        return

    tmp_path = dest_path.with_suffix(".tmp")
    for attempt in range(1, max_retries + 1):
        try:
            downloaded = tmp_path.stat().st_size if tmp_path.exists() else 0
            headers = {"User-Agent": "Mozilla/5.0"}
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                mode = "wb"
                total_size = None
                cl = resp.headers.get("Content-Length")
                cr = resp.headers.get("Content-Range")

                if resp.status == 206 or cr:
                    mode = "ab"
                    if cr:
                        # Format: bytes start-end/total
                        total_size = int(cr.split("/")[-1])
                    elif cl:
                        total_size = downloaded + int(cl)
                else:
                    downloaded = 0
                    mode = "wb"
                    if cl:
                        total_size = int(cl)

                chunk_size = 256 * 1024  # 256 KB
                with open(tmp_path, mode) as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            pct = min(100.0, downloaded * 100.0 / total_size)
                            sys.stdout.write(f"\r  Progress: {pct:5.1f}% ({downloaded / 1e6:5.1f} MB / {total_size / 1e6:5.1f} MB)")
                        else:
                            sys.stdout.write(f"\r  Downloaded: {downloaded / 1e6:5.1f} MB")
                        sys.stdout.flush()

            if tmp_path.exists() and tmp_path.stat().st_size > 0:
                if total_size and tmp_path.stat().st_size < total_size:
                    raise IOError(f"Truncated download: {tmp_path.stat().st_size} < {total_size}")
                if dest_path.exists():
                    dest_path.unlink()
                tmp_path.rename(dest_path)
                print(f"\n  [SUCCESS] Downloaded to {dest_path}")
                return
        except Exception as e:
            print(f"\n  [ATTEMPT {attempt}/{max_retries}] Error: {e}")
            if attempt == max_retries:
                if tmp_path.exists():
                    tmp_path.unlink()
                print(f"  [ERROR] Failed to download {url} after {max_retries} attempts.")
            import time
            time.sleep(2 * attempt)


def verify_torch_gpu() -> None:
    print("\n=== Checking PyTorch CUDA Acceleration ===")
    try:
        import torch
        print(f"  PyTorch Version: {torch.__version__}")
        cuda_avail = torch.cuda.is_available()
        print(f"  CUDA Available:  {cuda_avail}")
        if cuda_avail:
            print(f"  Device Count:    {torch.cuda.device_count()}")
            print(f"  GPU Name:        {torch.cuda.get_device_name(0)}")
            print(f"  VRAM Total:      {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
        else:
            print("  [WARNING] CUDA is NOT available. Install PyTorch with CUDA support:")
            print("  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121")
    except ImportError:
        print("  [ERROR] PyTorch is not installed in the active environment.")


def main():
    parser = argparse.ArgumentParser(description="Download model weights for Asli Awaaz GPU node")
    parser.add_argument("--skip-large", action="store_true", help="Skip large RVC base models (>100MB)")
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    verify_torch_gpu()

    print("\n=== Downloading Pretrained Biometric Checkpoints ===")
    for filename, info in DOWNLOADS.items():
        if args.skip_large and info["size_mb"] > 100:
            print(f"  [SKIPPED] {filename} (Large file: {info['size_mb']} MB)")
            continue
        dest = MODELS_DIR / filename
        download_file(info["url"], dest, info["description"])

    print("\n[COMPLETE] Model download routine finished.")
    print("Checkpoints directory: " + str(MODELS_DIR.resolve()))


if __name__ == "__main__":
    main()
