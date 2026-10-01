"""Double-click to start FileSh without a console window (logs go to %LOCALAPPDATA%\\FileSh)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.runner import main  # noqa: E402

main()
