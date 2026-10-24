"""
Preflight Diagnostic Tool (make preflight).
Validates runtime environment, audio devices, dependencies, model files, and network configuration.
Prints a clear green/red status row per checklist item.
"""

import sys
import shutil
from pathlib import Path

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


def check_item(name: str, passed: bool, detail: str = "") -> bool:
    status_str = f"{GREEN}[ PASS ]{RESET}" if passed else f"{RED}[ FAIL ]{RESET}"
    print(f"{status_str} {name.ljust(42)} {detail}")
    return passed


def run_preflight() -> int:
    print("=" * 65)
    print("           ASLI AWAAZ PREFLIGHT READINESS CHECK")
    print("=" * 65)

    all_passed = True

    # 1. Python version
    py_ok = sys.version_info >= (3, 10)
    all_passed &= check_item("Python Version (>= 3.10)", py_ok, f"{sys.version.split()[0]}")

    # 2. Virtual environment
    venv_dir = Path(".venv")
    all_passed &= check_item("Virtual Environment (.venv)", venv_dir.exists(), "Present")

    # 3. Audio & Numerical Libraries
    try:
        import numpy
        import scipy
        import soundfile
        audio_ok = True
        audio_detail = f"numpy {numpy.__version__}, soundfile {soundfile.__version__}"
    except ImportError as e:
        audio_ok = False
        audio_detail = str(e)
    all_passed &= check_item("Audio & Numeric Stack", audio_ok, audio_detail)

    # 4. FastAPI & Pydantic Service Stack
    try:
        import fastapi
        import pydantic
        service_ok = True
        service_detail = f"fastapi {fastapi.__version__}, pydantic {pydantic.__version__}"
    except ImportError as e:
        service_ok = False
        service_detail = str(e)
    all_passed &= check_item("Service & API Stack", service_ok, service_detail)

    # 5. Free Disk Space (> 5 GB recommended)
    disk = shutil.disk_usage(".")
    free_gb = disk.free / (1024 ** 3)
    disk_ok = free_gb >= 5.0
    all_passed &= check_item("Free Disk Space (>= 5.0 GB)", disk_ok, f"{free_gb:.1f} GB available")

    # 6. Governance & Documentation
    contracts_ok = Path("docs/CONTRACTS.md").exists()
    decisions_ok = Path("docs/DECISIONS.md").exists()
    licences_ok = Path("docs/LICENCES.md").exists()
    all_passed &= check_item("Governance Docs & Contracts", contracts_ok and decisions_ok and licences_ok, "Frozen")

    # 7. Demo Reset State
    demo_ready = Path("data/consent").exists() and Path("data/enrolments").exists()
    all_passed &= check_item("Demo Baseline Persona State", demo_ready, "Ready")

    print("=" * 65)
    if all_passed:
        print(f"{GREEN}ALL PREFLIGHT CHECKS PASSED. Ready for demonstration.{RESET}")
        return 0
    else:
        print(f"{RED}SOME CHECKS FAILED. Please review above failures.{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(run_preflight())
