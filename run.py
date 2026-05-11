from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "backend" / "data" / "destinations.json"

if not DATA_FILE.exists():
    subprocess.check_call([sys.executable, str(ROOT / "tools" / "init_system_data.py")], cwd=str(ROOT))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=False)
