"""
Small local server so the "Reload data" button in the React page can run your Python scripts.

Start it in your Strava folder (with your venv active) and keep it running:

    python server.py

It only listens on your own computer (127.0.0.1) and only runs the scripts listed in STEPS.
No extra packages are needed.
"""

import copy
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    DATA_FOLDER = Path(__file__).resolve().parent
except NameError:
    DATA_FOLDER = Path.cwd()

# ---------------- Settings ----------------
# Folder layout this is set up for:
#   Strava/
#     FE/     the React app (contains package.json)
#     Runs/   this file, activities.csv and the other Python scripts  <- DATA_FOLDER
# If your React folder is somewhere else, write the full path, e.g. Path("C:/Users/me/Strava/FE")
REACT_PROJECT = DATA_FOLDER.parent / "FE"

PORT = 5050
STEP_TIMEOUT_S = 30 * 60  # the first run of the track analysis can take a while

# Scripts that run, in this order, when you press the button.
# (name shown on the page, file name in this folder, extra arguments)
# Change the file names to match yours. A file that does not exist is skipped.
STEPS = [
    ("Monthly charts", "strava.py", []),
    ("Track analysis", "gpx.py", []),
    ("Export for the web page", "export.py", [str(REACT_PROJECT)]),
]

# ---------------- Job state ----------------
lock = threading.Lock()
state = {"running": False, "started": None, "finished": None, "ok": None, "steps": []}


def new_steps():
    return [
        {"name": name, "script": script, "status": "waiting", "seconds": None, "output": ""}
        for name, script, _ in STEPS
    ]


def snapshot():
    with lock:
        return copy.deepcopy(state)


def update_step(index, **fields):
    with lock:
        state["steps"][index].update(fields)


def run_all():
    all_ok = True
    for index, (_, script, arguments) in enumerate(STEPS):
        path = DATA_FOLDER / script
        if not path.exists():
            update_step(index, status="skipped", output=f"{script} was not found in {DATA_FOLDER}")
            continue

        update_step(index, status="running")
        started = time.time()
        try:
            result = subprocess.run(
                [sys.executable, str(path), *arguments],
                cwd=DATA_FOLDER,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=STEP_TIMEOUT_S,
                # Agg = no chart windows pop up on your screen
                env={**os.environ, "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8"},
            )
            output = (result.stdout + result.stderr).replace("\r", "\n").strip()
            status = "done" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            output, status = f"Stopped after {STEP_TIMEOUT_S // 60} minutes.", "failed"
        except Exception as error:  # for example a permission problem
            output, status = str(error), "failed"

        if status == "failed":
            all_ok = False
        update_step(index, status=status, seconds=round(time.time() - started, 1), output=output[-1500:])

    with lock:
        state.update(running=False, ok=all_ok, finished=datetime.now().strftime("%H:%M:%S"))


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/api/status":
            self.send_json(200, snapshot())
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/refresh":
            self.send_json(404, {"error": "not found"})
            return

        # Refuse requests coming from other websites open in your browser
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ("localhost", "127.0.0.1"):
            self.send_json(403, {"error": "forbidden"})
            return

        with lock:
            if state["running"]:
                already_running = True
            else:
                already_running = False
                state.update(
                    running=True,
                    started=datetime.now().strftime("%H:%M:%S"),
                    finished=None,
                    ok=None,
                    steps=new_steps(),
                )
        if not already_running:
            threading.Thread(target=run_all, daemon=True).start()
        self.send_json(409 if already_running else 202, snapshot())

    def log_message(self, format, *args):
        pass  # keep the terminal quiet


if __name__ == "__main__":
    print(f"Python server running on http://127.0.0.1:{PORT}  (press Ctrl+C to stop)")
    print(f"Scripts folder: {DATA_FOLDER}")
    print(f"React project:  {REACT_PROJECT}")
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
