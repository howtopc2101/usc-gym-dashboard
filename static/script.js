// --------- Global state ---------
let todayChart = null;
let historyChart = null;
let historyCache = [];

// --------- Fetch helpers ---------
async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
  return res.json();
}

// --------- Main polling loop ---------
async function refreshDashboard() {
  try {
    // Fetch latest snapshot and recent history
    const [latest, history] = await Promise.all([
      fetchJSON("/api/latest"),
      fetchJSON("/api/history?limit=500")
    ]);

    historyCache = Array.isArray(history) ? history : [];

    updateStatus(latest);
    updateMetrics(latest);
    updateTodayChart(historyCache);
    updateHistoryChart(historyCache);
  } catch (err) {
    console.error("Refresh error:", err);
    setOfflineState();
  }
}

// --------- Status / header ---------
function updateStatus(latest) {
  try {
    const date = new Date(latest.timestamp + "Z");
    const timeString = date.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });

    const label = document.getElementById("last-updated");
    const dot = document.querySelector(".indicator");
    if (label) label.textContent = `Updated ${timeString}`;
    if (dot) {
      dot.style.backgroundColor = "#30d158";
      dot.style.boxShadow = "0 0 10px rgba(48,209,88,0.9)";
    }
  } catch (e) {
    console.warn("Status update failed:", e);
  }
}

function setOfflineState() {
  const label = document.getElementById("last-updated");
  const dot = document.querySelector(".indicator");
  if (label) label.textContent = "Offline";
  if (dot) {
    dot.style.backgroundColor = "#ff453a";
    dot.style.boxShadow = "0 0 0 transparent";
  }
}

// --------- Metrics updates ---------
function updateMetrics(latest) {
  if (!latest || !latest.rooms) return;
  const r = latest.rooms;

  const villageTotal = (r.village_cardio || 0) + (r.village_strength || 0);
  const lyonTotal = (r.lyon_cardio || 0) + (r.lyon_strength || 0);
  const hscTotal = r.hsc_cardio || 0;
  const total = villageTotal + lyonTotal + hscTotal;

  setMetric("total-count", total);
  setMetric("village-total", villageTotal);
  setMetric("lyon-total", lyonTotal);
  setMetric("hsc-total", hscTotal);

  setMetric("village-cardio", r.village_cardio || 0);
  setMetric("village-strength", r.village_strength || 0);
  setMetric("lyon-cardio", r.lyon_cardio || 0);
  setMetric("lyon-strength", r.lyon_strength || 0);
  setMetric("hsc-cardio", r.hsc_cardio || 0);
}

// Single helper that also mirrors values into the flowing gym blocks
function setMetric(id, value) {
  const el = document.getElementById(id);
  const valueStr = String(value);

  if (el) {
    if (el.textContent !== valueStr) {
      el.style.opacity = "0.5";
      el.style.transform = "translateY(1px)";
      setTimeout(() => {
        el.textContent = valueStr;
        el.style.opacity = "1";
        el.style.transform = "translateY(0)";
      }, 140);
    }
  }

  // Keep duplicate displays in sync
  const mirrorMap = {
    "village-cardio": "village-cardio-dup",
    "village-strength": "village-strength-dup",
    "lyon-cardio": "lyon-cardio-dup",
    "lyon-strength": "lyon-strength-dup",
    "hsc-cardio": "hsc-cardio-dup"
  };

  const mirrorId = mirrorMap[id];
  if (mirrorId) {
    const dup = document.getElementById(mirrorId);
    if (dup) dup.textContent = valueStr;
  }
}

// --------- Chart: Today trend ---------
function updateTodayChart(history) {
  if (!Array.isArray(history) || history.length === 0) return;

  // Use the date of the last entry as "today"
  const last = history[history.length - 1];
  if (!last.timestamp) return;

  const lastDateStr = last.timestamp.slice(0, 10); // YYYY-MM-DD

  const todayPoints = history
    .filter((row) => row.timestamp && row.timestamp.slice(0, 10) === lastDateStr)
    .map((row) => {
      const total =
        (row.rooms?.village_cardio || 0) +
        (row.rooms?.village_strength || 0) +
        (row.rooms?.lyon_cardio || 0) +
        (row.rooms?.lyon_strength || 0) +
        (row.rooms?.hsc_cardio || 0);
      return { t: row.timestamp, total };
    });

  if (todayPoints.length === 0) return;

  const labels = todayPoints.map((p) =>
    new Date(p.t + "Z").toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    })
  );
  const values = todayPoints.map((p) => p.total);

  const ctx = document.getElementById("todayChart");
  if (!ctx) return;

  if (todayChart) {
    todayChart.data.labels = labels;
    todayChart.data.datasets[0].data = values;
    todayChart.update();
    return;
  }

  todayChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Total occupancy",
          data: values,
          tension: 0.32,
          borderWidth: 2,
          borderColor: "rgba(10,132,255,0.9)",
          backgroundColor: "rgba(10,132,255,0.22)",
          fill: true,
          pointRadius: 0,
          pointHitRadius: 10
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          mode: "index",
          intersect: false,
          callbacks: {
            label: (ctx) => ` ${ctx.parsed.y} people`
          }
        }
      },
      scales: {
        x: {
          grid: {
            color: "rgba(255,255,255,0.06)"
          },
          ticks: {
            color: "rgba(255,255,255,0.65)",
            maxTicksLimit: 6
          }
        },
        y: {
          beginAtZero: true,
          grid: {
            color: "rgba(255,255,255,0.06)"
          },
          ticks: {
            color: "rgba(255,255,255,0.65)",
            precision: 0
          }
        }
      }
    }
  });
}

// --------- Chart: Daily averages ---------
function updateHistoryChart(history) {
  if (!Array.isArray(history) || history.length === 0) return;

  // Group by date and average total occupancy per day
  const byDate = new Map();

  history.forEach((row) => {
    if (!row.timestamp) return;
    const day = row.timestamp.slice(0, 10); // YYYY-MM-DD

    const total =
      (row.rooms?.village_cardio || 0) +
      (row.rooms?.village_strength || 0) +
      (row.rooms?.lyon_cardio || 0) +
      (row.rooms?.lyon_strength || 0) +
      (row.rooms?.hsc_cardio || 0);

    if (!byDate.has(day)) {
      byDate.set(day, { sum: 0, count: 0 });
    }
    const entry = byDate.get(day);
    entry.sum += total;
    entry.count += 1;
  });

  const sortedDays = Array.from(byDate.keys()).sort();
  const labels = sortedDays.map((d) => d.slice(5)); // MM-DD
  const averages = sortedDays.map((d) => {
    const { sum, count } = byDate.get(d);
    return count ? Math.round(sum / count) : 0;
  });

  const ctx = document.getElementById("historyChart");
  if (!ctx) return;

  if (historyChart) {
    historyChart.data.labels = labels;
    historyChart.data.datasets[0].data = averages;
    historyChart.update();
    return;
  }

  historyChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Daily average occupancy",
          data: averages,
          tension: 0.25,
          borderWidth: 2,
          borderColor: "rgba(255,255,255,0.85)",
          backgroundColor: "rgba(255,255,255,0.08)",
          fill: true,
          pointRadius: 2.5,
          pointBackgroundColor: "rgba(255,255,255,0.95)"
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${ctx.parsed.y} people`
          }
        }
      },
      scales: {
        x: {
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "rgba(255,255,255,0.65)",
            maxTicksLimit: 7
          }
        },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "rgba(255,255,255,0.65)",
            precision: 0
          }
        }
      }
    }
  });
}

// --------- Kickoff ---------
document.addEventListener("DOMContentLoaded", () => {
  refreshDashboard();
  setInterval(refreshDashboard, 10_000);
});
