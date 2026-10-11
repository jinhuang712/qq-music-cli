"""Turn a local image into the square JPEG that y.qq.com's playlist editor uploads as a cover.

The web editor crops to a square in a canvas and sends `canvas.toDataURL("image/jpeg")`. We do the
same with macOS's built-in `sips`, so no image library is needed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import UsageError

MAX_SIDE = 800  # downscale larger squares; the editor's own preview caps at 700


def square_jpeg(path: Path) -> bytes:
    """Centre-crop `path` to a square, shrink it to at most MAX_SIDE, and return JPEG bytes."""
    path = path.expanduser()
    if not path.is_file():
        raise UsageError(f"no such image: {path}")
    if shutil.which("sips") is None:
        raise UsageError("changing a cover needs macOS `sips`")
    size = _sips(["-g", "pixelWidth", "-g", "pixelHeight", str(path)], path)
    dims = [int(v) for v in re.findall(r"pixel(?:Width|Height):\s*(\d+)", size)]
    if len(dims) != 2 or min(dims) == 0:
        raise UsageError(f"not an image sips can read: {path}")
    side = min(dims)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cover.jpg"
        args = ["-c", str(side), str(side)]
        if side > MAX_SIDE:
            args += ["-Z", str(MAX_SIDE)]
        _sips([*args, "-s", "format", "jpeg", "-s", "formatOptions", "90", str(path), "--out", str(out)], path)
        return out.read_bytes()


def _sips(args: list[str], path: Path) -> str:
    done = subprocess.run(["sips", *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise UsageError(f"not an image sips can read: {path}")
    return done.stdout
