/* ClipperOS — app.js */
'use strict';

const $ = id => document.getElementById(id);

/* ═══════════════════════════════════════════════════
   TAB SWITCHING — sidebar + mobile nav in sync
═══════════════════════════════════════════════════ */
function switchTab(tab) {
  document.querySelectorAll('.nav-btn, .mobile-nav-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('active', p.id === 'tab-' + tab);
  });
  if (tab === 'history') loadHistory();
}

document.querySelectorAll('.nav-btn, .mobile-nav-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

/* ═══════════════════════════════════════════════════
   PLATFORM DETECTION
═══════════════════════════════════════════════════ */
const PLATFORM_LABELS = {
  youtube: '▶ YouTube',
  twitch:  '● Twitch',
  kick:    '⚡ Kick',
};

function setupPlatformDetect(inputId, badgeId) {
  let timer = null;
  const input = $(inputId);
  const badge = $(badgeId);
  if (!input || !badge) return;

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const url = input.value.trim();
      if (!url) { badge.classList.add('hidden'); return; }
      try {
        const r = await fetch('/api/detect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });
        const { platform } = await r.json();
        if (platform && platform !== 'unknown') {
          badge.textContent = PLATFORM_LABELS[platform] || platform;
          badge.classList.remove('hidden');
        } else {
          badge.classList.add('hidden');
        }
      } catch {
        badge.classList.add('hidden');
      }
    }, 400);
  });
}

setupPlatformDetect('dl-url', 'dl-platform-badge');
setupPlatformDetect('au-url', 'au-platform-badge');
setupPlatformDetect('tr-url', 'tr-platform-badge');

/* ═══════════════════════════════════════════════════
   WORKFLOW STEPS
═══════════════════════════════════════════════════ */
function setStep(steps, active) {
  steps.forEach((id, i) => {
    const el = $(id);
    if (!el) return;
    el.classList.remove('active', 'done');
    if (i < active)  el.classList.add('done');
    if (i === active) el.classList.add('active');
  });
}

/* ═══════════════════════════════════════════════════
   STATUS BLOCK
═══════════════════════════════════════════════════ */
function showStatus(id, state, msg, progress = null) {
  const el = $(id);
  if (!el) return;
  const icons = { running: '⏳', done: '✅', error: '❌' };
  const isRunning = state === 'running';
  const isIndeterminate = isRunning && progress === null;
  const pct = progress ?? 0;

  el.className = `status-block ${state}`;
  el.innerHTML = `
    <div class="status-msg">${icons[state] || ''} ${msg}</div>
    ${isRunning ? `
    <div class="status-progress">
      <div class="status-progress-fill ${isIndeterminate ? 'indeterminate' : ''}" style="width:${isIndeterminate ? 40 : pct}%"></div>
    </div>` : ''}
  `;
}

/* ═══════════════════════════════════════════════════
   JOB POLLING
═══════════════════════════════════════════════════ */
const polls = {};

function pollJob(jobId, onUpdate, onDone, onError) {
  if (polls[jobId]) return;
  polls[jobId] = setInterval(async () => {
    try {
      const r = await fetch(`/api/job/${jobId}`);
      if (!r.ok) return;
      const job = await r.json();
      onUpdate(job);
      if (job.status === 'done') {
        clearInterval(polls[jobId]); delete polls[jobId];
        onDone(job); refreshJobsPanel();
      } else if (job.status === 'error') {
        clearInterval(polls[jobId]); delete polls[jobId];
        onError(job); refreshJobsPanel();
      }
    } catch {}
  }, 800);
}

/* ═══════════════════════════════════════════════════
   JOBS PANEL
═══════════════════════════════════════════════════ */
const TYPE_LABEL = {
  clip:       '✂ Clip',
  full:       '↓ Video',
  audio:      '♪ Audio',
  transcript: '📄 Transcript',
  ai:         '✦ AI',
};

async function refreshJobsPanel() {
  try {
    const r = await fetch('/api/jobs');
    const jobs = await r.json();
    const list = $('jobs-list');
    const count = $('jobs-count');
    if (!list) return;

    const running = jobs.filter(j => j.status === 'running').length;
    if (count) count.textContent = jobs.length;

    if (!jobs.length) {
      list.innerHTML = `
        <div class="jobs-empty">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <p>No downloads yet</p>
          <span>Jobs will appear here</span>
        </div>`;
      return;
    }

    list.innerHTML = jobs.slice(0, 12).map(job => {
      const isRunning = job.status === 'running';
      const bar = isRunning ? `
        <div class="job-bar">
          <div class="job-bar-fill ${job.progress === null || job.progress === 0 ? 'indeterminate' : ''}" style="width:${job.progress || 0}%"></div>
        </div>` : '';
      return `
      <div class="job-card">
        <div class="job-card-top">
          <div class="job-dot ${job.status}"></div>
          <span class="job-type">${TYPE_LABEL[job.type] || job.type}</span>
          <span class="job-time">${job.created_at}</span>
        </div>
        <div class="job-msg">${esc(job.message || '')}</div>
        ${bar}
      </div>`;
    }).join('');
  } catch {}
}

setInterval(refreshJobsPanel, 2500);
refreshJobsPanel();

/* ═══════════════════════════════════════════════════
   DOWNLOAD — two-step flow
═══════════════════════════════════════════════════ */
const DL_STEPS = ['step-url-dl', 'step-options-dl', 'step-done-dl'];

// Step 1 → 2
$('dl-url-continue').addEventListener('click', () => {
  const url = $('dl-url').value.trim();
  const errEl = $('dl-url-error');

  if (!url) {
    errEl.textContent = '⚠ Paste a video URL to continue.';
    errEl.classList.remove('hidden');
    return;
  }
  if (!url.startsWith('http')) {
    errEl.textContent = '⚠ That doesn\'t look like a valid URL.';
    errEl.classList.remove('hidden');
    return;
  }

  errEl.classList.add('hidden');
  $('dl-url-preview').textContent = url;
  $('dl-step1').classList.add('hidden');
  $('dl-step2').classList.remove('hidden');
  setStep(DL_STEPS, 1);
});

$('dl-back').addEventListener('click', () => {
  $('dl-step2').classList.add('hidden');
  $('dl-step1').classList.remove('hidden');
  $('dl-status').classList.add('hidden');
  setStep(DL_STEPS, 0);
});

// Clip toggle
$('dl-clip-toggle').addEventListener('change', e => {
  $('dl-clip-fields').classList.toggle('hidden', !e.target.checked);
});

// Download
$('btn-download').addEventListener('click', async () => {
  const url      = $('dl-url').value.trim();
  const filename = $('dl-filename').value.trim() || 'video';
  const quality  = $('dl-quality').value;
  const isClip   = $('dl-clip-toggle').checked;
  const start    = $('dl-start').value.trim();
  const end      = $('dl-end').value.trim();

  if (isClip) {
    if (!start) { showStatus('dl-status', 'error', 'Enter a start time (HH:MM:SS).'); return; }
    if (!end)   { showStatus('dl-status', 'error', 'Enter an end time (HH:MM:SS).'); return; }
  }

  const endpoint = isClip ? '/api/download/clip' : '/api/download/full';
  const body = isClip
    ? { url, filename, quality, start, end }
    : { url, filename, quality };

  showStatus('dl-status', 'running', isClip ? `Clipping ${start} → ${end}...` : 'Downloading video...');
  $('dl-status').classList.remove('hidden');

  try {
    const r = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const { job_id, error } = await r.json();
    if (error) { showStatus('dl-status', 'error', error); return; }

    pollJob(job_id,
      job => showStatus('dl-status', 'running', job.message, job.progress),
      job => {
        showStatus('dl-status', 'done', `Saved as ${job.result?.filename || filename}`);
        setStep(DL_STEPS, 2);
      },
      job => showStatus('dl-status', 'error', job.error || 'Download failed.')
    );
  } catch {
    showStatus('dl-status', 'error', 'Could not reach the server. Is ClipperOS running?');
  }
});

/* ═══════════════════════════════════════════════════
   AUDIO — two-step flow
═══════════════════════════════════════════════════ */
let selectedFormat = 'mp3';

document.querySelectorAll('.format-card').forEach(card => {
  card.addEventListener('click', () => {
    document.querySelectorAll('.format-card').forEach(c => c.classList.remove('active'));
    card.classList.add('active');
    selectedFormat = card.dataset.format;
  });
});

$('au-url-continue').addEventListener('click', () => {
  const url = $('au-url').value.trim();
  const errEl = $('au-url-error');

  if (!url) {
    errEl.textContent = '⚠ Paste a video URL to continue.';
    errEl.classList.remove('hidden');
    return;
  }

  errEl.classList.add('hidden');
  $('au-url-preview').textContent = url;
  $('au-step1').classList.add('hidden');
  $('au-step2').classList.remove('hidden');
});

$('au-back').addEventListener('click', () => {
  $('au-step2').classList.add('hidden');
  $('au-step1').classList.remove('hidden');
  $('au-status').classList.add('hidden');
});

$('btn-audio').addEventListener('click', async () => {
  const url      = $('au-url').value.trim();
  const filename = $('au-filename').value.trim() || 'audio';

  showStatus('au-status', 'running', `Extracting ${selectedFormat.toUpperCase()} audio...`);
  $('au-status').classList.remove('hidden');

  try {
    const r = await fetch('/api/download/audio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, filename, format: selectedFormat }),
    });
    const { job_id, error } = await r.json();
    if (error) { showStatus('au-status', 'error', error); return; }

    pollJob(job_id,
      job => showStatus('au-status', 'running', job.message, job.progress),
      job => showStatus('au-status', 'done', `Saved as ${job.result?.filename || filename + '.' + selectedFormat}`),
      job => showStatus('au-status', 'error', job.error || 'Audio extraction failed.')
    );
  } catch {
    showStatus('au-status', 'error', 'Could not reach the server. Is ClipperOS running?');
  }
});

/* ═══════════════════════════════════════════════════
   TRANSCRIPT
═══════════════════════════════════════════════════ */
const trBtn = $('btn-transcript');
if (trBtn) {
  trBtn.addEventListener('click', async () => {
    const url = $('tr-url').value.trim();
    if (!url) {
      showStatus('tr-status', 'error', 'Paste a YouTube URL first.');
      $('tr-status').classList.remove('hidden');
      return;
    }

    showStatus('tr-status', 'running', 'Downloading transcript...');
    $('tr-status').classList.remove('hidden');
    $('tr-result').classList.add('hidden');

    try {
      const r = await fetch('/api/transcript', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const { job_id, error } = await r.json();
      if (error) { showStatus('tr-status', 'error', error); return; }

      pollJob(job_id,
        job => showStatus('tr-status', 'running', job.message, job.progress),
        job => {
          showStatus('tr-status', 'done', job.message);
          renderTranscript(job.result);
        },
        job => showStatus('tr-status', 'error', job.error || 'Transcript download failed.')
      );
    } catch {
      showStatus('tr-status', 'error', 'Could not reach the server. Is ClipperOS running?');
    }
  });
}

function renderTranscript(result) {
  if (!result) return;
  const el = $('tr-result');
  const cached = result.cached ? ' <span style="font-size:10px;background:#d1fae5;color:#065f46;padding:1px 6px;border-radius:10px;font-weight:600">cached</span>' : '';
  el.innerHTML = `
    <div class="tc-header">
      <span class="tc-title">${esc(result.title || result.video_id)}${cached}</span>
      <span class="tc-meta">${(result.word_count || 0).toLocaleString()} words · ${esc(result.platform)}</span>
    </div>
    <div class="tc-preview">${esc(result.preview || '')}</div>
    ${result.file_path ? `<div class="tc-footer">📁 ${esc(result.file_path)}</div>` : ''}
  `;
  el.classList.remove('hidden');
}

/* ═══════════════════════════════════════════════════
   HISTORY
═══════════════════════════════════════════════════ */
async function loadHistory() {
  const el = $('history-list');
  if (!el) return;

  try {
    const r = await fetch('/api/history');
    const entries = await r.json();

    if (!entries.length) {
      el.innerHTML = `
        <div class="jobs-empty">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          <p>No history yet</p>
          <span>Your downloads will appear here</span>
        </div>`;
      return;
    }

    el.innerHTML = entries.map(e => {
      if (!e.kind) return `<div class="history-card"><div class="history-body"><div class="history-name">${esc(e.raw)}</div></div></div>`;
      const kindMap = { CLIP: 'kind-clip', FULL: 'kind-full' };
      const kindClass = kindMap[e.kind] || 'kind-full';
      const time = (e.time || '').split(' ')[1] || e.time;
      return `
      <div class="history-card">
        <span class="history-kind ${kindClass}">${esc(e.kind)}</span>
        <div class="history-body">
          <div class="history-name">${esc(e.name)}</div>
          <div class="history-detail">${esc(e.platform)} · ${esc(e.url.slice(0, 60))}${e.url.length > 60 ? '…' : ''}</div>
        </div>
        <span class="history-time">${esc(time)}</span>
      </div>`;
    }).join('');
  } catch {
    el.innerHTML = '<p style="color:var(--text-tertiary);font-size:13px;padding:20px 0">Could not load history.</p>';
  }
}

/* ═══════════════════════════════════════════════════
   UTILS
═══════════════════════════════════════════════════ */
function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
