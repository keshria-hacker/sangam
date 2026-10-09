/**
 * Job store — tracks all long-running work (Sangam-native).
 *
 * Jobs outlive views: a code-agent run keeps going when you switch tabs.
 * Each job: { id, kind, title, status, startedAt, endedAt, tokens, cost,
 *   model, progress, error, abort }
 * Status: running | needs-you | done | failed | paused
 *
 * UI: the Activity Tray renders from this store.
 */
console.log('[Module] jobs.js loaded');

const jobs = new Map(); // id -> job
const listeners = new Set();
let seq = 0;

function emit() {
  const list = [...jobs.values()].sort((a, b) => b.startedAt - a.startedAt);
  for (const fn of listeners) { try { fn(list); } catch {} }
  document.dispatchEvent(new CustomEvent('sangam:jobs-changed', { detail: { jobs: list } }));
}

export function onJobsChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getJobs() {
  return [...jobs.values()].sort((a, b) => b.startedAt - a.startedAt);
}

export function getActiveJobs() {
  return getJobs().filter((j) => j.status === 'running' || j.status === 'needs-you' || j.status === 'paused');
}

/** Start a job. Returns the job id. */
export function startJob({ kind, title, model = '', abort = null }) {
  const id = `job-${Date.now().toString(36)}-${++seq}`;
  const job = {
    id, kind, title, model,
    status: 'running',
    startedAt: Date.now(),
    endedAt: null,
    tokens: 0,
    cost: 0,
    progress: 0,
    error: null,
    abort,
    seen: false,
  };
  jobs.set(id, job);
  emit();
  maybeNotify(`Started: ${title}`);
  return id;
}

/** Update a job's fields. */
export function updateJob(id, patch) {
  const job = jobs.get(id);
  if (!job) return;
  Object.assign(job, patch);
  emit();
}

/** Mark a job done/failed. */
export function finishJob(id, status = 'done', error = null) {
  const job = jobs.get(id);
  if (!job) return;
  job.status = status;
  job.endedAt = Date.now();
  job.error = error;
  job.progress = status === 'done' ? 1 : job.progress;
  emit();
  if (status === 'done') maybeNotify(`Done: ${job.title}`);
  else if (status === 'failed') maybeNotify(`Failed: ${job.title}`);
  else if (status === 'needs-you') maybeNotify(`Needs you: ${job.title}`, true);
}

/** Stop a job via its abort handle. */
export function stopJob(id) {
  const job = jobs.get(id);
  if (!job) return;
  try { job.abort?.(); } catch {}
  finishJob(id, 'done');
}

/** Stop all running jobs. */
export function stopAllJobs() {
  for (const job of getActiveJobs()) stopJob(job.id);
}

/** Mark a job as seen (clears the unread dot). */
export function markSeen(id) {
  const job = jobs.get(id);
  if (job) { job.seen = true; emit(); }
}

function maybeNotify(message, urgent = false) {
  try {
    const enabled = JSON.parse(localStorage.getItem('sangam:settings-cache') || '{}').notifyOnDone;
    if (!enabled && !urgent) return;
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('Sangam', { body: message });
    }
  } catch {}
}

/** Prune finished jobs older than 24h. */
export function pruneJobs() {
  const cutoff = Date.now() - 24 * 3600 * 1000;
  for (const [id, job] of jobs) {
    if (job.endedAt && job.endedAt < cutoff) jobs.delete(id);
  }
  emit();
}
