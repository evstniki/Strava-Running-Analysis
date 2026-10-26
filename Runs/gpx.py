"""
Deeper analysis of single runs, using the GPX / FIT files from the Strava export.

  1. Best efforts      fastest 1 km, 1 mile, 5 km, 10 km, half marathon inside any run
  2. Pacing            negative or positive splits (first half vs second half)
  3. Heart rate drift  how much your heart rate "drifts" up on long runs
  4. Heart rate zones  how much time you spend easy vs hard
  5. Route map         all your runs on one map (routes_map.html)

Needs: numpy and matplotlib (already installed with matplotlib)
Optional: fitparse (for .fit files) and folium (for the route map)
    pip install fitparse folium
"""

import csv
import gzip
import io
import pickle
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter

try:
    from fitparse import FitFile
except ImportError:
    FitFile = None

# ---------------- Settings (change these) ----------------
# Folder with activities.csv and the activities/ folder. By default this is the folder
# where this script is saved, so it works no matter where you start it from.
# To use another folder, write it here, for example: Path("C:/Users/me/Strava")
try:
    DATA_FOLDER = Path(__file__).resolve().parent
except NameError:  # running inside Jupyter
    DATA_FOLDER = Path.cwd()
ACTIVITY_TYPES = ("Run",)
MAX_FILES = None            # e.g. 50 = only the newest 50 runs (good for a first test)
MAX_HR = 190                # CHANGE THIS to your own maximum heart rate
HR_ZONE_LIMITS = (0.6, 0.7, 0.8, 0.9)  # zone borders as a share of MAX_HR
RECENT_DAYS = 90            # "recent" window for the best efforts table
PACING_MIN_KM = 5           # runs at least this long are used for split analysis
DRIFT_MIN_KM = 8            # runs at least this long are used for heart rate drift
WARMUP_SEC = 600            # first 10 minutes are ignored for heart rate drift
MAX_GAP_S = 30              # a gap longer than this between points counts as a pause
MAX_SPEED_MS = 10           # ignore GPS jumps faster than 10 m/s (1:40 per km)
MIN_PACE_SEC_PER_KM = 150   # ignore best efforts faster than 2:30/km (GPS errors)
CACHE_FILE = DATA_FOLDER / "track_cache.pkl"

EFFORT_DISTANCES = {
    "1 km": 1000,
    "1 mile": 1609.344,
    "5 km": 5000,
    "10 km": 10000,
    "Half marathon": 21097.5,
    "30K": 30000,
    "Marathon": 42195,
}

SEMICIRCLES = 180 / 2**31   # FIT files store coordinates in semicircles


# ---------------- Helpers ----------------
def format_time(seconds):
    seconds = round(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_pace(seconds_per_km):
    minutes, seconds = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{seconds:02d}"


def local_name(tag):
    return tag.rsplit("}", 1)[-1]  # remove the XML namespace

def parse_timestamp(text):
    parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()

def track_date(track):
    return datetime.fromtimestamp(track["start"], tz=timezone.utc).replace(tzinfo=None)


def ffill(values):
    """Fill missing (NaN) values with the last known value."""
    values = values.copy()
    missing = np.isnan(values)
    index = np.where(~missing, np.arange(len(values)), 0)
    np.maximum.accumulate(index, out=index)
    values = values[index]
    values[np.isnan(values)] = values[~np.isnan(values)][0]  # leading NaNs
    return values


def haversine_steps(lat, lon):
    """Distance in metres between each point and the previous one."""
    lat, lon = np.radians(lat), np.radians(lon)
    prev_lat = np.concatenate(([lat[0]], lat[:-1]))
    dlat = lat - prev_lat
    dlon = np.diff(lon, prepend=lon[0])
    a = np.sin(dlat / 2) ** 2 + np.cos(lat) * np.cos(prev_lat) * np.sin(dlon / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(a))


# ---------------- Reading GPX and FIT files ----------------
def parse_gpx(data):
    root = ET.fromstring(data)
    times, lats, lons, hrs = [], [], [], []
    for point in root.iter():
        if local_name(point.tag) != "trkpt":
            continue
        time_text, heart_rate = None, np.nan
        for child in point.iter():
            name = local_name(child.tag)
            if name == "time" and child.text:
                time_text = child.text
            elif name == "hr" and child.text:
                heart_rate = float(child.text)
        if time_text is None:
            continue
        times.append(parse_timestamp(time_text))
        lats.append(float(point.get("lat")))
        lons.append(float(point.get("lon")))
        hrs.append(heart_rate)
    return times, lats, lons, hrs, [np.nan] * len(times)


def parse_fit(data):
    if FitFile is None:
        raise RuntimeError("fitparse is not installed (run: pip install fitparse)")
    times, lats, lons, hrs, dists = [], [], [], [], []
    for record in FitFile(io.BytesIO(data)).get_messages("record"):
        values = record.get_values()
        stamp = values.get("timestamp")
        if stamp is None:
            continue
        times.append(stamp.replace(tzinfo=timezone.utc).timestamp())
        lat, lon = values.get("position_lat"), values.get("position_long")
        lats.append(lat * SEMICIRCLES if lat is not None else np.nan)
        lons.append(lon * SEMICIRCLES if lon is not None else np.nan)
        hr, dist = values.get("heart_rate"), values.get("distance")
        hrs.append(float(hr) if hr is not None else np.nan)
        dists.append(float(dist) if dist is not None else np.nan)
    return times, lats, lons, hrs, dists


def build_track(times, lats, lons, hrs, dists):
    """Turn raw points into arrays: moving time t (s), distance d (m), heart rate hr."""
    if len(times) < 60:
        return None
    times = np.asarray(times, dtype=float)
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    hrs = np.asarray(hrs, dtype=float)
    dists = np.asarray(dists, dtype=float)

    if np.isfinite(dists).mean() > 0.9:  # FIT files usually have a distance field
        filled = ffill(dists)
        step = np.maximum(np.diff(filled, prepend=filled[0]), 0)
    elif np.isfinite(lats).mean() > 0.9 and np.isfinite(lons).mean() > 0.9:
        step = haversine_steps(ffill(lats), ffill(lons))
    else:
        return None  # no GPS and no distance (e.g. treadmill without sensor)

    dt = np.maximum(np.diff(times, prepend=times[0]), 0)
    gap = dt > MAX_GAP_S  # pauses are removed from both time and distance
    dt[gap] = 0
    step[gap] = 0
    with np.errstate(divide="ignore", invalid="ignore"):
        step[(dt > 0) & (step / dt > MAX_SPEED_MS)] = 0  # GPS jumps

    t = np.cumsum(dt)
    d = np.cumsum(step) + np.arange(len(step)) * 1e-6  # tiny ramp keeps d strictly increasing
    if d[-1] < 1000:
        return None

    with np.errstate(invalid="ignore"):
        hr = np.where((hrs >= 40) & (hrs <= 230), hrs, np.nan)  # drop sensor glitches

    points = np.column_stack([lats, lons])
    good = np.isfinite(points).all(axis=1) & ~(points == 0).all(axis=1)
    points = points[good]
    route = points[:: max(1, len(points) // 300)] if len(points) else points

    return {"start": float(times[0]), "t": t, "d": d, "hr": hr, "route": route}


def find_file(relative_path):
    """Find a track file. Also works when the file was unzipped (or zipped) differently
    from what activities.csv says, or when the folder layout is slightly different."""
    relative = Path(relative_path.replace("\\", "/"))
    name = relative.name
    other_name = name[:-3] if name.endswith(".gz") else name + ".gz"
    for folder in (DATA_FOLDER / relative.parent, DATA_FOLDER / "activities"):
        for candidate_name in (name, other_name):
            candidate = folder / candidate_name
            if candidate.is_file():
                return candidate
    return None


def load_track(relative_path):
    path = find_file(relative_path)
    if path is None:
        raise FileNotFoundError(relative_path)
    name, data = path.name.lower(), path.read_bytes()
    if name.endswith(".gz"):
        data, name = gzip.decompress(data), name[:-3]
    if name.endswith(".gpx"):
        raw = parse_gpx(data)
    elif name.endswith(".fit"):
        raw = parse_fit(data)
    else:
        return None
    return build_track(*raw)


def list_run_files():
    csv_path = DATA_FOLDER / "activities.csv"
    if not csv_path.exists():
        raise SystemExit(
            f"activities.csv not found in {DATA_FOLDER}\n"
            "Save this script next to activities.csv, or set DATA_FOLDER at the top of the script."
        )
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        type_index = headers.index("Activity Type")
        file_index = headers.index("Filename")
        return [
            row[file_index].strip()
            for row in reader
            if len(row) > max(type_index, file_index)
            and row[type_index] in ACTIVITY_TYPES
            and row[file_index].strip()
        ]


# ---------------- Analyses ----------------
def best_effort(t, d, target_m):
    """Fastest time (s) to cover target_m metres anywhere inside the run."""
    if d[-1] < target_m:
        return None
    ends = np.nonzero(d >= target_m)[0]
    durations = t[ends] - np.interp(d[ends] - target_m, d, t)
    durations = durations[durations >= target_m / 1000 * MIN_PACE_SEC_PER_KM]
    return float(durations.min()) if durations.size else None


def split_difference(track):
    """% difference between first and second half. Positive = second half faster."""
    t, d = track["t"], track["d"]
    if d[-1] < PACING_MIN_KM * 1000:
        return None
    first = float(np.interp(d[-1] / 2, d, t))
    second = t[-1] - first
    return (first - second) / first * 100


def hr_drift(track):
    """% drop in speed-per-heartbeat between the 1st and 2nd half (after warm-up).
    Under about 5% is good aerobic fitness for that effort."""
    t, d, hr = track["t"], track["d"], track["hr"]
    if d[-1] < DRIFT_MIN_KM * 1000 or np.isfinite(hr).mean() < 0.8:
        return None
    start = int(np.searchsorted(t, WARMUP_SEC))
    if start >= len(t) - 120:
        return None
    middle = int(np.searchsorted(d, (d[start] + d[-1]) / 2))
    dt = np.diff(t, prepend=t[0])

    def efficiency(a, b):
        ok = np.isfinite(hr[a:b]) & (dt[a:b] > 0)
        if ok.sum() < 60 or t[b - 1] <= t[a]:
            return None
        avg_hr = np.average(hr[a:b][ok], weights=dt[a:b][ok])
        speed = (d[b - 1] - d[a]) / (t[b - 1] - t[a])
        return speed / avg_hr, avg_hr

    first, second = efficiency(start, middle), efficiency(middle, len(t))
    if first is None or second is None:
        return None
    return (first[0] - second[0]) / first[0] * 100, (first[1] + second[1]) / 2


def make_route_map(tracks):
    try:
        import folium
    except ImportError:
        print("Route map skipped (run: pip install folium)")
        return
    routes = [track["route"] for track in tracks if len(track["route"]) > 1]
    if not routes:
        print("Route map skipped (no GPS data found)")
        return
    center = np.median(np.vstack(routes), axis=0).tolist()
    # OpenStreetMap's own tile server blocks pages opened directly from disk (error 403),
    # so use map backgrounds that allow it. The layer button (top right) switches between them.
    route_map = folium.Map(location=center, zoom_start=13, tiles=None)
    carto_attr = "&copy; OpenStreetMap contributors &copy; CARTO"
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        attr=carto_attr, name="Light map",
    ).add_to(route_map)
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr=carto_attr, name="Dark map", show=False,
    ).add_to(route_map)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri", name="Satellite", show=False,
    ).add_to(route_map)
    folium.LayerControl().add_to(route_map)
    for route in routes:
        folium.PolyLine(route.tolist(), color="#e03131", weight=2, opacity=0.25).add_to(route_map)
    route_map.save(str(DATA_FOLDER / "routes_map.html"))
    print(f"Saved routes_map.html ({len(routes)} routes; streets you run most look darker)")


# ---------------- Load all tracks (with cache) ----------------
settings_signature = (MAX_GAP_S, MAX_SPEED_MS, 2)  # 2 = cache version
cache = {}
if Path(CACHE_FILE).exists():
    try:
        with open(CACHE_FILE, "rb") as f:
            saved = pickle.load(f)
        if saved.get("settings") == settings_signature:
            cache = saved["tracks"]
    except Exception:
        cache = {}

files = list_run_files()
if MAX_FILES:
    files = files[-MAX_FILES:]
if not files:
    raise SystemExit("No GPX/FIT files listed in activities.csv (check the 'Filename' column)")

tracks, errors, missing = [], {}, []
for number, relative_path in enumerate(files, 1):
    if relative_path in cache:
        track = cache[relative_path]
    else:
        try:
            track = load_track(relative_path)
            cache[relative_path] = track  # None here means: file found but not usable
        except FileNotFoundError:
            missing.append(relative_path)  # not cached, so it is retried next time
            track = None
        except Exception as error:
            errors[str(error)[:90]] = errors.get(str(error)[:90], 0) + 1
            track = None
    if track is not None:
        tracks.append(track)
    if number % 25 == 0 or number == len(files):
        print(f"Reading files: {number}/{len(files)}", end="\r")
print()

with open(CACHE_FILE, "wb") as f:
    pickle.dump({"settings": settings_signature, "tracks": cache}, f)

if missing:
    print(f"  {len(missing)} of {len(files)} files not found.")
    print(f"  activities.csv says: {missing[0]}")
    print(f"  Looked in: {DATA_FOLDER}  (and {DATA_FOLDER / 'activities'})")
for message, count in errors.items():
    print(f"  {count} file(s) skipped: {message}")
if not tracks:
    raise SystemExit("No usable tracks found")

tracks.sort(key=lambda track: track["start"])
latest = track_date(tracks[-1])
print(f"Loaded {len(tracks)} runs from {track_date(tracks[0]):%Y-%m-%d} to {latest:%Y-%m-%d}\n")

# ---------------- 1. Best efforts ----------------
efforts = {name: [] for name in EFFORT_DISTANCES}
for track in tracks:
    for name, meters in EFFORT_DISTANCES.items():
        duration = best_effort(track["t"], track["d"], meters)
        if duration:
            efforts[name].append((duration, track_date(track)))

print("BEST EFFORTS (fastest section inside any run)")
print(f"{'Distance':<15}{'All-time':>10}{'Pace/km':>9}  {'Date':<12}{f'Last {RECENT_DAYS} days':>14}")
recent_start = latest - timedelta(days=RECENT_DAYS)
for name, meters in EFFORT_DISTANCES.items():
    if not efforts[name]:
        print(f"{name:<15}{'-':>10}")
        continue
    best, best_date = min(efforts[name])
    recent = [duration for duration, date in efforts[name] if date >= recent_start]
    recent_text = format_time(min(recent)) if recent else "-"
    print(
        f"{name:<15}{format_time(best):>10}{format_pace(best / (meters / 1000)):>9}  "
        f"{best_date:%Y-%m-%d}  {recent_text:>14}"
    )

# ---------------- 2. Pacing ----------------
splits = [value for value in (split_difference(track) for track in tracks) if value is not None]
print(f"\nPACING (runs of {PACING_MIN_KM} km or more)")
if splits:
    negative = sum(1 for value in splits if value > 0)
    print(f"  {len(splits)} runs: {negative} negative splits ({negative / len(splits):.0%}), "
          f"{len(splits) - negative} positive splits")
    print(f"  Median difference: {np.median(splits):+.1f}% "
          "(positive = second half faster, negative = you slow down)")
else:
    print("  Not enough long runs")

# ---------------- 3. Heart rate drift ----------------
drift_runs = []
for track in tracks:
    result = hr_drift(track)
    if result:
        drift_runs.append((track_date(track), track["d"][-1] / 1000, result[0], result[1]))

print(f"\nHEART RATE DRIFT (runs of {DRIFT_MIN_KM} km or more with heart rate data)")
if drift_runs:
    values = [run[2] for run in drift_runs]
    print(f"  {len(drift_runs)} runs, median drift {np.median(values):.1f}%, "
          f"{sum(1 for v in values if v < 5) / len(values):.0%} of runs under 5%")
    print("  Most recent runs:")
    for date, km, drift, avg_hr in drift_runs[-5:]:
        print(f"    {date:%Y-%m-%d}  {km:5.1f} km  avg HR {avg_hr:3.0f}  drift {drift:+5.1f}%")
else:
    print("  No long runs with heart rate data")

# ---------------- 4. Heart rate zones ----------------
zone_seconds = np.zeros(5)
for track in tracks:
    hr, dt = track["hr"], np.diff(track["t"], prepend=track["t"][0])
    ok = np.isfinite(hr)
    if ok.any():
        zones = np.digitize(hr[ok], np.array(HR_ZONE_LIMITS) * MAX_HR)
        zone_seconds += np.bincount(zones, weights=dt[ok], minlength=5)

zone_names = ["Z1 very easy", "Z2 easy", "Z3 moderate", "Z4 hard", "Z5 max"]
print(f"\nHEART RATE ZONES (max heart rate set to {MAX_HR})")
if zone_seconds.sum() > 0:
    share = zone_seconds / zone_seconds.sum() * 100
    for name, hours, percent in zip(zone_names, zone_seconds / 3600, share):
        print(f"  {name:<14}{hours:7.1f} h  {percent:5.1f}%")
    print(f"  Easy (Z1+Z2): {share[:2].sum():.0f}%   Moderate (Z3): {share[2]:.0f}%   "
          f"Hard (Z4+Z5): {share[3:].sum():.0f}%")
    print("  A common guideline is about 80% easy and 20% hard.")
else:
    print("  No heart rate data found")

# ---------------- Chart ----------------
fig, (ax_effort, ax_drift, ax_zones) = plt.subplots(1, 3, figsize=(17, 5))
pace_format = FuncFormatter(lambda v, _: format_pace(v * 60))

for name in ("1 km", "5 km"):
    if efforts.get(name):
        meters = EFFORT_DISTANCES[name]
        ax_effort.scatter(
            [date for _, date in efforts[name]],
            [duration / (meters / 1000) / 60 for duration, _ in efforts[name]],
            s=14, alpha=0.7, label=f"fastest {name} in each run",
        )
ax_effort.invert_yaxis()
ax_effort.yaxis.set_major_formatter(pace_format)
ax_effort.set_ylabel("pace (min/km)")
ax_effort.set_title("Best efforts over time")
ax_effort.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, fontsize=8)
ax_effort.tick_params(axis="x", rotation=45)

if drift_runs:
    ax_drift.scatter([run[0] for run in drift_runs], [run[2] for run in drift_runs],
                     s=14, color="tab:red", alpha=0.7)
    ax_drift.axhline(5, color="gray", linestyle="--", linewidth=1)
    ax_drift.text(0.98, 5.1, "5%", transform=ax_drift.get_yaxis_transform(),
                  ha="right", va="bottom", color="gray")
else:
    ax_drift.text(0.5, 0.5, "no heart rate data", ha="center", transform=ax_drift.transAxes)
ax_drift.set_ylabel("drift (%)")
ax_drift.set_title("Heart rate drift on long runs")
ax_drift.tick_params(axis="x", rotation=45)

colors = ["#9ecae1", "#6baed6", "#fdd835", "#fb8c00", "#e53935"]
ax_zones.bar(range(5), zone_seconds / 3600, color=colors)
ax_zones.set_xticks(range(5))
ax_zones.set_xticklabels(["Z1", "Z2", "Z3", "Z4", "Z5"])
ax_zones.set_ylabel("hours")
ax_zones.set_title("Time in heart rate zones")

fig.tight_layout()
fig.savefig(DATA_FOLDER / "track_analysis.png")
print("\nSaved track_analysis.png")

make_route_map(tracks)
