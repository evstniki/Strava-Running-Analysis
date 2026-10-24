import { useEffect, useState } from 'react'
import './App.css'

// export_for_web.py (Python) writes these files into  public/data/
// Everything inside public/ is served from the site root, so /data/runs.json works.
const DATA_FOLDER = '/data'

const CHARTS = [
  { file: 'running_summary.png', title: 'Monthly summary' },
  { file: 'track_analysis.png', title: 'Best efforts, heart rate drift and zones' },
  { file: 'routes.png', title: 'My routes' },
]

function ChartImage({ file, title, version }) {
  const [missing, setMissing] = useState(false)
  if (missing) return null // hide charts that Python has not created yet

  return (
    <figure>
      <img
        src={`${DATA_FOLDER}/${file}?v=${version}`}
        alt={title}
        onError={() => setMissing(true)}
      />
      <figcaption>{title}</figcaption>
    </figure>
  )
}

function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`${DATA_FOLDER}/runs.json`, { cache: 'no-store' })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() // fails if the file is missing (the dev server then returns index.html)
      })
      .then(setData)
      .catch(() =>
        setError(
          `Could not load ${DATA_FOLDER}/runs.json. Run "python export_for_web.py" first, then reload this page.`
        )
      )
  }, [])

  if (error) {
    return (
      <main className="app">
        <p className="error">{error}</p>
      </main>
    )
  }

  if (!data) {
    return (
      <main className="app">
        <p>Loading…</p>
      </main>
    )
  }

  const { meta, monthly, predictions } = data
  const lastMonths = monthly.slice(-12)
  const maxKm = Math.max(...lastMonths.map((month) => month.km), 1)

  return (
    <main className="app">
      <h1>My running data</h1>
      <p className="muted">
        {meta.runs} runs · {meta.total_km} km · {meta.first_run} to {meta.last_run}
        <br />
        Updated {meta.generated}
      </p>

      <section>
        <h2>Race time predictions</h2>
        <p className="muted">
          Riegel formula on runs from the last {meta.prediction_days} days. Estimates only.
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
            {predictions.map((p) => (
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
                  <div className="bar" style={{ width: `${(month.km / maxKm) * 100}%` }} />
                </td>
                <td>{month.pace}</td>
                <td>{month.avg_hr ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Charts</h2>
        {CHARTS.map((chart) => (
          <ChartImage key={chart.file} {...chart} version={meta.generated} />
        ))}
      </section>
    </main>
  )
}

export default App
