"""Package the double-click artifact. Wraps PyInstaller; bundles ffmpeg + viewer/ (KE-022)."""

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found on PATH — install it first; it must be bundled.")
    pkg = Path("src/igarchive")
    sep = ";" if sys.platform == "win32" else ":"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--name",
            "igarchive",
            "--add-data",
            f"{pkg / 'viewer'}{sep}igarchive/viewer",
            "--add-data",
            f"{pkg / 'ui'}{sep}igarchive/ui",
            "--add-binary",
            f"{ffmpeg}{sep}.",
            "run.py",
        ],
        check=True,
    )
    print("Built dist/igarchive — double-click to run.")


if __name__ == "__main__":
    main()
