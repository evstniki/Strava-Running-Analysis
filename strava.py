import csv
from collections import defaultdict
from datetime import datetime

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def parse_date(value):
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for date_format in ("%b %d, %Y, %I:%M:%S %p", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, date_format)
            except ValueError:
                pass
    raise ValueError(f"Unsupported activity date: {value!r}")


def format_pace(seconds_per_km):
    minutes, seconds = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{seconds:02d}"


monthly = defaultdict(
    lambda: {"km": 0.0, "seconds": 0.0, "hr_weighted": 0.0, "hr_seconds": 0.0}
)

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
    distance_index = distance_columns[1]
    moving_time_index = headers.index("Moving Time")
    hr_index = headers.index("Average Heart Rate")

    for row in reader:
        if row[type_index] != "Run":
            continue

        km = float(row[distance_index] or 0) / 1000
        seconds = float(row[moving_time_index] or 0)
        if km <= 0 or seconds <= 0:
            continue

        month = parse_date(row[date_index]).strftime("%Y-%m")
        totals = monthly[month]
        totals["km"] += km
        totals["seconds"] += seconds

        heart_rate = float(row[hr_index] or 0)
        if heart_rate > 0:
            totals["hr_weighted"] += heart_rate * seconds
            totals["hr_seconds"] += seconds

months = sorted(monthly)[-48:]
km_values, pace_values, hr_values = [], [], []

print(f"{'month':<8} {'km':>8} {'pace/km':>8} {'avg HR':>7}")
for month in months:
    totals = monthly[month]
    pace = totals["seconds"] / totals["km"]  # seconds per km
    hr = (
        totals["hr_weighted"] / totals["hr_seconds"]
        if totals["hr_seconds"] else float("nan")
    )
    km_values.append(totals["km"])
    pace_values.append(pace / 60)  # minutes per km, for plotting
    hr_values.append(hr)
    hr_text = f"{hr:.0f}" if hr == hr else "-"
    print(f"{month:<8} {totals['km']:>8.1f} {format_pace(pace):>8} {hr_text:>7}")

fig, (ax_km, ax_pace, ax_hr) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

ax_km.bar(months, km_values)
ax_km.set_ylabel("km per month")
ax_km.set_title("Monthly running summary")

ax_pace.plot(months, pace_values, marker="o")
ax_pace.invert_yaxis() 
ax_pace.yaxis.set_major_formatter(FuncFormatter(lambda v, _: format_pace(v * 60)))
ax_pace.set_ylabel("average pace (min/km)")

ax_hr.plot(months, hr_values, marker="o", color="tab:red")
ax_hr.set_ylabel("average heart rate (bpm)")

ax_hr.tick_params(axis="x", rotation=90)
fig.tight_layout()
fig.savefig("running_summary.png")
print("Saved running_summary.png")