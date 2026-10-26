"""
Export your running stats for the React app.

Writes  <react project>/public/data/runs.json   (monthly stats + race predictions)
Copies  the chart images (running_summary.png, track_analysis.png, routes.png)

Usage:
    python export_for_web.py                   # uses REACT_PROJECT below
    python export_for_web.py ../my-react-app   # or give the project folder
"""

import csv
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

try:
    DATA_FOLDER = Path("Runs").resolve().parent
except NameError:  # running inside Jupyter
    DATA_FOLDER = Path.cwd()

# ---------------- Settings ----------------
# CHANGE THIS: the folder of your React app (the one that contains package.json)
REACT_PROJECT = DATA_FOLDER.parent / "FE"  # or give the folder on the command line

IMAGES = ["running_summary.png", "track_analysis.png", "routes.png"]

RECENT_DAYS = 120          # race predictions use runs from the last N days
MIN_RUN_KM = 3.0           # ignore very short runs
MIN_PACE_SEC_PER_KM = 150  # ignore runs faster than 2:30/km (GPS errors)
RIEGEL_EXPONENT = 1.06
REFERENCE_FRACTION = 0.2   # reference run must be at least 20% of the race distance...
MAX_REFERENCE_RATIO = 4    # ...and at most 4x the race distance

TARGETS = {
    "5K": 5.0,
    "10K": 10.0,
    "Half marathon": 21.0975,
    "30K": 30.0,
    "Marathon": 42.195,
}


def parse_date(value):
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for date_format in ("%b %d, %Y, %I:%M:%S %p", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(value, date_format)
                break
            except ValueError:
                pass
    if parsed is None:
        raise ValueError(f"Unsupported activity date: {value!r}")
    return parsed.replace(tzinfo=None)


def format_time(seconds):
    seconds = round(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_pace(seconds_per_km):
    minutes, seconds = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{seconds:02d}"


def to_float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


# ---------------- Read runs from activities.csv ----------------
csv_path = DATA_FOLDER / "activities.csv"
if not csv_path.exists():
    raise SystemExit(f"activities.csv not found in {DATA_FOLDER}")

runs = []  # (date, km, seconds, average heart rate or 0)
with open(csv_path, newline="", encoding="utf-8-sig") as activities_file:
    reader = csv.reader(activities_file)
    headers = next(reader)

    distance_columns = [
        index for index, name in enumerate(headers)
        if name == "Distance" or name.startswith("Distance.")
    ]
    if len(distance_columns) < 2:
        raise SystemExit("Expected two Distance columns in activities.csv")

    date_index = headers.index("Activity Date")
    type_index = headers.index("Activity Type")
    distance_index = distance_columns[1]  # second Distance column is in metres
    moving_time_index = headers.index("Moving Time")
    hr_index = headers.index("Average Heart Rate") if "Average Heart Rate" in headers else None

    for row in reader:
        if row[type_index] != "Run":
            continue
        km = to_float(row[distance_index]) / 1000
        seconds = to_float(row[moving_time_index])
        if km <= 0 or seconds <= 0:
            continue
        heart_rate = to_float(row[hr_index]) if hr_index is not None else 0.0
        runs.append((parse_date(row[date_index]), km, seconds, heart_rate))

if not runs:
    raise SystemExit("No runs found in activities.csv")

# ---------------- Monthly stats ----------------
months = defaultdict(lambda: {"km": 0.0, "seconds": 0.0, "hr_weighted": 0.0, "hr_seconds": 0.0, "runs": 0})
for date, km, seconds, heart_rate in runs:
    month = months[date.strftime("%Y-%m")]
    month["km"] += km
    month["seconds"] += seconds
    month["runs"] += 1
    if heart_rate > 0:
        month["hr_weighted"] += heart_rate * seconds
        month["hr_seconds"] += seconds

monthly = []
for name in sorted(months):
    month = months[name]
    pace = month["seconds"] / month["km"]
    monthly.append({
        "month": name,
        "runs": month["runs"],
        "km": round(month["km"], 1),
        "pace": format_pace(pace),
        "pace_seconds": round(pace),
        "avg_hr": round(month["hr_weighted"] / month["hr_seconds"]) if month["hr_seconds"] else None,
    })

# ---------------- Race predictions (Riegel formula) ----------------
latest = max(run[0] for run in runs)
recent = [run for run in runs
          if run[0] >= latest - timedelta(days=RECENT_DAYS)
          and run[1] >= MIN_RUN_KM and run[2] / run[1] >= MIN_PACE_SEC_PER_KM]

predictions = []
for race, target_km in TARGETS.items():
    candidates = []
    for date, km, seconds, _ in recent:
        if km < target_km * REFERENCE_FRACTION or km > target_km * MAX_REFERENCE_RATIO:
            continue
        candidates.append((seconds * (target_km / km) ** RIEGEL_EXPONENT, date, km))
    if not candidates:
        predictions.append({"race": race, "distance_km": target_km, "best": None})
        continue
    candidates.sort()
    best, best_date, best_km = candidates[0]
    top = candidates[:3]
    likely = sum(item[0] for item in top) / len(top)
    predictions.append({
        "race": race,
        "distance_km": target_km,
        "best": format_time(best),
        "best_pace": format_pace(best / target_km),
        "likely": format_time(likely),
        "likely_pace": format_pace(likely / target_km),
        "based_on": {"km": round(best_km, 1), "date": best_date.strftime("%Y-%m-%d")},
    })

output = {
    "meta": {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "runs": len(runs),
        "total_km": round(sum(run[1] for run in runs)),
        "first_run": min(run[0] for run in runs).strftime("%Y-%m-%d"),
        "last_run": latest.strftime("%Y-%m-%d"),
        "prediction_days": RECENT_DAYS,
    },
    "monthly": monthly,
    "predictions": predictions,
}

# ---------------- Write into the React project ----------------
project = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else REACT_PROJECT
if not (project / "package.json").exists():
    raise SystemExit(
        f"No React project found at {project}\n"
        "Give the folder that contains package.json, for example:\n"
        "    python export_for_web.py ../my-react-app\n"
        "or change REACT_PROJECT at the top of this script."
    )

target = project / "public" / "data"
target.mkdir(parents=True, exist_ok=True)
(target / "runs.json").write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")
print(f"Wrote {target / 'runs.json'}  ({len(runs)} runs, {len(monthly)} months)")

for image in IMAGES:
    source = DATA_FOLDER / image
    if source.exists():
        shutil.copy2(source, target / image)
        print(f"Copied {image}")
    else:
        print(f"Skipped {image} (not found; run the script that creates it first)")
