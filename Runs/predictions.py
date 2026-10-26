import csv
from datetime import datetime, timedelta

# ---------------- Settings (change these to experiment) ----------------
RECENT_DAYS = 800          # only use runs from the last N days before your latest run
MIN_RUN_KM = 3.0           # ignore very short runs
MIN_PACE_SEC_PER_KM = 150  # ignore runs faster than 2:30/km (GPS errors)
RIEGEL_EXPONENT = 1.06     # standard value; higher = slower predictions for long races
REFERENCE_FRACTION = 0.2   # a run must be at least 20% of the race distance to be used
                           # (so a 5 km jog is not used to predict a marathon)
MAX_REFERENCE_RATIO = 4    # ...and at most 4x the race distance
                           # (so a 21 km run is not used to predict a 5K)

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
    return parsed.replace(tzinfo=None)  # avoid timezone-aware vs naive comparison errors


def format_time(seconds):
    seconds = round(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_pace(seconds_per_km):
    minutes, seconds = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{seconds:02d}"


# ---------------- Read runs from activities.csv ----------------
runs = []  # (date, km, seconds)
with open("activities.csv", newline="", encoding="utf-8-sig") as activities_file:
    reader = csv.reader(activities_file)
    headers = next(reader)

    distance_columns = [
        index for index, name in enumerate(headers)
        if name == "Distance" or name.startswith("Distance.")
    ]
    if len(distance_columns) < 2:
        raise ValueError("Expected two Distance columns in activities.csv")

    date_index = headers.index("Activity Date")
    type_index = headers.index("Activity Type")
    distance_index = distance_columns[1]  # second Distance column is in metres
    moving_time_index = headers.index("Moving Time")

    for row in reader:
        if row[type_index] != "Run":
            continue
        km = float(row[distance_index] or 0) / 1000
        seconds = float(row[moving_time_index] or 0)
        if km < MIN_RUN_KM or seconds <= 0:
            continue
        if seconds / km < MIN_PACE_SEC_PER_KM:
            continue
        runs.append((parse_date(row[date_index]), km, seconds))

if not runs:
    raise SystemExit("No usable runs found in activities.csv")

# Only keep recent runs, counted back from your latest run
latest = max(run[0] for run in runs)
cutoff = latest - timedelta(days=RECENT_DAYS)
recent = [run for run in runs if run[0] >= cutoff]

print(
    f"Using {len(recent)} runs from {cutoff:%Y-%m-%d} to {latest:%Y-%m-%d} "
    f"(Riegel exponent {RIEGEL_EXPONENT})\n"
)

# ---------------- Predict race times ----------------
print(f"{'Race':<14} {'Best case':>10} {'Pace/km':>8} {'Likely':>10} {'Pace/km':>8}  Based on")
for name, target_km in TARGETS.items():
    candidates = []
    for date, km, seconds in recent:
        if km < target_km * REFERENCE_FRACTION or km > target_km * MAX_REFERENCE_RATIO:
            continue
        # Riegel formula: T2 = T1 * (D2 / D1) ** exponent
        predicted = seconds * (target_km / km) ** RIEGEL_EXPONENT
        candidates.append((predicted, date, km))

    if not candidates:
        print(f"{name:<14} {'no recent run long enough':>10}")
        continue

    candidates.sort()
    best, best_date, best_km = candidates[0]
    top = candidates[:3]
    likely = sum(item[0] for item in top) / len(top)  # average of the 3 best predictions

    print(
        f"{name:<14} {format_time(best):>10} {format_pace(best / target_km):>8} "
        f"{format_time(likely):>10} {format_pace(likely / target_km):>8}  "
        f"{best_km:.1f} km on {best_date:%Y-%m-%d}"
    )

print(
    "\nBest case = your strongest recent run, scaled to the race distance.\n"
    "Likely = average of your 3 strongest. These are estimates: long races also depend on\n"
    "weekly mileage, hills, weather and pacing, and a marathon needs specific training."
)
