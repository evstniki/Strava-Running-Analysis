# Strava Running Analysis

I am an enthusiast runner, and this is my first attempt to get better by using the data from my runs.

The script reads my exported Strava activities and shows how my running changes month by month:

- total distance (km)
- average pace (min/km)
- average heart rate (bpm)

It prints a table in the terminal and saves a chart as `running_summary.png`.

## What you need

- Python 3
- A Strava data export (`activities.csv`)
- The `matplotlib` package (the rest uses the Python standard library)

## Setup

### 1. Get your data from Strava

1. On the Strava website, go to **Settings → My Account → Download or Delete Your Account → Get Started**.
2. Click **Request Your Archive**. Strava sends you an email with a zip file.
3. Unzip it and copy `activities.csv` into this project folder.

### 2. Create a virtual environment

```bash
cd ~/strava_data
python3 -m venv venv
source venv/bin/activate
```

Your prompt should now start with `(venv)`. Run `source venv/bin/activate` again each time you open a new terminal.

If `venv` fails on Debian or Ubuntu, run `sudo apt install python3-full` first.

### 3. Install the package

```bash
pip install matplotlib
```

## Run it

```bash
python analysis.py
```

You will see a monthly table like this:

```
month          km  pace/km  avg HR
2026-08      96.4     5:38     151
2026-09     110.2     5:31     149
```

and a new file, `running_summary.png`, with three charts: distance, pace and heart rate.

## My plots

![Monthly running summary: distance, pace and heart rate](running_summary.png)

The image above is created by the script. Run `python analysis.py` once so that `running_summary.png` exists in the same folder as this README. Each time you run the script, the image is replaced with an updated version.

## How to read the results

- **Pace** is total time divided by total distance for the month, so long runs count more than short ones. The pace axis is flipped, so a line going up means you are getting faster.
- **Heart rate** is averaged only over runs that have heart rate data, weighted by time.
- If your pace gets faster while your heart rate stays the same or drops, that is a rough sign your fitness is improving. Heat, hills and the mix of easy runs and workouts also affect these numbers.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `externally-managed-environment` when installing | Use the virtual environment from step 2 |
| `ValueError: ... is not in list` | Column names differ in your export. Add `print(headers)` after `headers = next(reader)` and adjust the names in the script |
| `Unsupported activity date` | Your date format is different. Add it to the list of formats in `parse_date` |
| No chart window appears | The chart is saved as `running_summary.png`, so open that file |

## Ideas for next steps

- Weekly instead of monthly view
- Compare years
- Include trail runs (`Trail Run` activity type)
- Look at single runs (splits, heart rate drift) using the GPX/FIT files from the export