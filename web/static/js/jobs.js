// jobs.js — Background job polling for C-MOVE / C-GET / C-STORE
// Extracted from index.html; loaded as a plain script (shared global scope, no modules).
// ─────────────────────────────────────────────────────────────────
// Complements the SocketIO log stream: /api/dicom/move|get|store return a
// job_id that we poll via /api/jobs/<id> so completion state survives a
// page refresh or a dropped WebSocket connection.
// ─────────────────────────────────────────────────────────────────

const _JOBS_KEY = "pacsadmin_active_jobs";

function _jobsLoad() {
  try { return JSON.parse(localStorage.getItem(_JOBS_KEY) || "{}"); }
  catch { return {}; }
}

function _jobsSave(jobs) {
  try { localStorage.setItem(_JOBS_KEY, JSON.stringify(jobs)); }
  catch { /* storage full - ignore */ }
}

function _jobUntrack(jobId) {
  const jobs = _jobsLoad();
  delete jobs[jobId];
  _jobsSave(jobs);
}

/** Start tracking a job returned by a C-MOVE/C-GET/C-STORE request. */
function trackJob(jobId, logBoxId) {
  if (!jobId) return;
  const jobs = _jobsLoad();
  jobs[jobId] = { logBoxId };
  _jobsSave(jobs);
  _pollJob(jobId, logBoxId);
}

async function _pollJob(jobId, logBoxId) {
  let job;
  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (res.status === 404) { _jobUntrack(jobId); return; }
    const data = await res.json();
    job = data.job;
  } catch {
    setTimeout(() => _pollJob(jobId, logBoxId), 3000);
    return;
  }
  if (!job || job.state === "running") {
    setTimeout(() => _pollJob(jobId, logBoxId), 2000);
    return;
  }
  appendLog(logBoxId, now(), job.message, job.state === "completed" ? "ok" : "err");
  _jobUntrack(jobId);
}

/** Resume polling any jobs still tracked from before a page refresh. */
function resumeTrackedJobs() {
  const jobs = _jobsLoad();
  Object.entries(jobs).forEach(([jobId, info]) => _pollJob(jobId, info.logBoxId));
}
