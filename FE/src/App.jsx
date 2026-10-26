import { useCallback, useEffect, useState } from "react";
import "./App.css";

// export_for_web.py (Python) writes these files into  public/data/
// Everything inside public/ is served from the site root, so /data/runs.json works.
const DATA_FOLDER = "/data";

const CHARTS = [
  { file: "running_summary.png", title: "Monthly summary" },
  {
    file: "track_analysis.png",
    title: "Best efforts, heart rate drift and zones",
  },
  { file: "routes.png", title: "My routes" },
];

const STEP_ICONS = {
  waiting: "○",
  running: "⏳",
  done: "✓",
  failed: "✗",
  skipped: "–",
};

function ChartImage({ file, title, version }) {
  const [missing, setMissing] = useState(false);
  if (missing) return null; // hide charts that Python has not created yet

  return (
    <figure>
      <img
        src={`${DATA_FOLDER}/${file}?v=${encodeURIComponent(version)}`}
        alt={title}
        onError={() => setMissing(true)}
      />
      <figcaption>{title}</figcaption>
    </figure>
  );
}

function JobSteps({ job }) {
  if (!job.steps.length) return null;

  return (
    <ul className="steps">
      {job.steps.map((step) => (
        <li key={step.script} className={step.status}>
          {STEP_ICONS[step.status]} {step.name}
          {step.seconds != null && ` (${step.seconds} s)`}
          {(step.status === "failed" || step.status === "skipped") &&
            step.output && <pre>{step.output}</pre>}
        </li>
      ))}
    </ul>
  );
}

function App() {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [job, setJob] = useState(null); // status sent by server.py
  const [starting, setStarting] = useState(false);
  const [refreshError, setRefreshError] = useState("");

  const running = Boolean(job?.running);

  // Read the JSON file that Python wrote
  const loadData = useCallback(() => {
    return fetch(`${DATA_FOLDER}/runs.json`, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json(); // fails if the file is missing (the dev server then returns index.html)
      })
      .then((json) => {
        setData(json);
        setLoadError("");
      })
      .catch(() => {
        setLoadError(
          'No data yet. Press "Reload data" to run the Python scripts.',
        );
      });
  }, []);

  // When the page opens: show the current data, and pick up a job that is already running
  useEffect(() => {
    loadData();
    fetch("/api/status")
      .then((response) => response.json())
      .then((status) => {
        if (status.running) setJob(status);
      })
      .catch(() => {}); // the Python server is not started, which is fine until the button is used
  }, [loadData]);

  // While Python is running, ask the server for its progress every second
  useEffect(() => {
    if (!running) return undefined;

    const timer = setInterval(() => {
      fetch("/api/status")
        .then((response) => response.json())
        .then((status) => {
          setJob(status);
          if (!status.running) loadData(); // finished: load the new numbers
        })
        .catch(() => {
          setJob(null);
          setRefreshError(
            'Lost the connection to the Python server (is "python server.py" still running?).',
          );
        });
    }, 1000);

    return () => clearInterval(timer);
  }, [running, loadData]);

  // The button: ask the Python server to run the scripts
  function refresh() {
    setRefreshError("");
    setStarting(true);
    fetch("/api/refresh", { method: "POST" })
      .then((response) => response.json()) // 202 = started, 409 = already running; both return the status
      .then(setJob)
      .catch(() => {
        setRefreshError(
          'Could not reach the Python server. Start it with "python server.py" in your Strava folder, then try again.',
        );
      })
      .finally(() => setStarting(false));
  }

  const meta = data?.meta;
  const lastMonths = data ? data.monthly.slice(-12) : [];
  const maxKm = Math.max(...lastMonths.map((month) => month.km), 1);

  return (
    <main className="app">
      <h1>My running data</h1>

      {meta && (
        <p className="muted">
          {meta.runs} runs · {meta.total_km} km · {meta.first_run} to{" "}
          {meta.last_run}
          <br />
          Updated {meta.generated}
        </p>
      )}

      <div className="toolbar">
        <button
          type="button"
          onClick={refresh}
          disabled={starting || running}
          className="Upload-button"
        >
          {starting || running ? "Running Python…" : "Upload data"}
        </button>
        {job && !running && job.ok === true && (
          <span className="muted">Done at {job.finished}</span>
        )}
        {job && !running && job.ok === false && (
          <span className="error-text">
            Finished with errors at {job.finished}
          </span>
        )}
      </div>

      {refreshError && <p className="error">{refreshError}</p>}
      {job && <JobSteps job={job} />}

      {!data && <p className="muted">{loadError || "Loading…"}</p>}

      {data && (
        <>
          <section>
            <h2>Race time predictions</h2>
            <p className="muted">
              Riegel formula on runs from the last {meta.prediction_days} days.
              Estimates only.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Race</th>
                  <th>Best case</th>
                  <th>Pace/km</th>
                  <th>Likely</th>
                  <th>Pace/km</th>
                  <th>Based on</th>
                </tr>
              </thead>
              <tbody>
                {data.predictions.map((p) => (
                  <tr key={p.race}>
                    <td>{p.race}</td>
                    {p.best ? (
                      <>
                        <td>{p.best}</td>
                        <td>{p.best_pace}</td>
                        <td>{p.likely}</td>
                        <td>{p.likely_pace}</td>
                        <td className="muted">
                          {p.based_on.km} km on {p.based_on.date}
                        </td>
                      </>
                    ) : (
                      <td colSpan={5} className="muted">
                        no recent run long enough
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2>Last 12 months</h2>
            <table>
              <thead>
                <tr>
                  <th>Month</th>
                  <th>Runs</th>
                  <th>km</th>
                  <th></th>
                  <th>Pace/km</th>
                  <th>Avg HR</th>
                </tr>
              </thead>
              <tbody>
                {lastMonths.map((month) => (
                  <tr key={month.month}>
                    <td>{month.month}</td>
                    <td>{month.runs}</td>
                    <td>{month.km.toFixed(1)}</td>
                    <td className="bar-cell">
                      <div
                        className="bar"
                        style={{ width: `${(month.km / maxKm) * 100}%` }}
                      />
                    </td>
                    <td>{month.pace}</td>
                    <td>{month.avg_hr ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2>Charts</h2>
            {CHARTS.map((chart) => (
              // the key contains the version, so a chart that was missing is tried again after a reload
              <ChartImage
                key={chart.file + meta.generated}
                {...chart}
                version={meta.generated}
              />
            ))}
          </section>
        </>
      )}
    </main>
  );
}

export default App;
