/* ClipperOS — app.js v1.4.2
   Changes from v1.4:
   - showStatus() renders real yt-dlp progress percentage from job.progress
   - pollJob onDone handler shows output_path + Open Folder button
   - openFolder() calls POST /api/open-folder
   - Download/clip/audio onDone handlers updated to show file path
   Everything else is identical to v1.4.
*/
'use strict';

const $ = id => document.getElementById(id);

/* ═══════════════════════════════════════════════════
   TAB SWITCHING
═══════════════════════════════════════════════════ */
function switchTab(tab) {
  document.querySelectorAll('.nav-btn, .mobile-nav-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('active', p.id === 'tab-' + tab);
  });
  if (tab === 'history')  loadHistory();
  if (tab === 'settings') loadAuthStatus();
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
  const input = $(inputId), badge = $(badgeId);
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
      } catch { badge.classList.add('hidden'); }
    }, 400);
  });
}

setupPlatformDetect('dl-url', 'dl-platform-badge');
setupPlatformDetect('au-url', 'au-platform-badge');
setupPlatformDetect('tr-url', 'tr-platform-badge');

/* ═══════════════════════════════════════════════════
   STATUS BLOCK
   — now renders real progress % from job.progress
   — shows output path + Open Folder button on done
═══════════════════════════════════════════════════ */
function showStatus(id, state, msg, progress = null, result = null) {
  const el = $(id);
  if (!el) return;

  const icons = { running: '⏳', done: '✅', error: '❌' };
  const isRunning  = state === 'running';
  const isProcessing = isRunning && msg && msg.toLowerCase().startsWith('process');

  // Progress bar
  let barHtml = '';
  if (isRunning) {
    const hasReal   = progress !== null && progress > 0;
    const indet     = !hasReal || isProcessing;
    const fillClass = indet ? 'indeterminate' : '';
    const width     = indet ? 40 : progress;
    barHtml = `
      <div class="status-progress">
        <div class="status-progress-fill ${fillClass}" style="width:${width}%"></div>
      </div>`;
  }

  // Output path + Open Folder (shown on done when result has output_path)
  let pathHtml = '';
  if (state === 'done' && result && result.output_path) {
    const p = esc(result.output_path);
    pathHtml = `
      <div class="status-output-path">
        <span class="status-path-label">📁</span>
        <span class="status-path-text" title="${p}">${p}</span>
        <button class="btn-open-folder" onclick="openFolder(${JSON.stringify(result.output_path)})">
          Open folder
        </button>
      </div>`;
  }

  el.className = `status-block ${state}`;
  el.innerHTML = `
    <div class="status-msg">${icons[state] || ''} ${msg}</div>
    ${barHtml}
    ${pathHtml}
  `;
}

async function fetchJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error('Could not reach the server. Is ClipperOS running?');
  }

  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    if (response.status === 404) {
      throw new Error(
        'The server is running an old version. Stop ClipperOS (Ctrl+C), then run: python webapp.py'
      );
    }
    throw new Error(`Server returned an unexpected response (${response.status}). Restart ClipperOS.`);
  }

  return { response, data };
}

/* ═══════════════════════════════════════════════════
   OPEN FOLDER
═══════════════════════════════════════════════════ */
async function openFolder(filePath) {
  try {
    const r = await fetch('/api/open-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath, select_file: true }),
    });
    const data = await r.json();
    if (!data.ok) {
      alert('Could not open folder: ' + (data.error || 'Unknown error'));
    }
  } catch {
    alert('Could not reach the server. Is ClipperOS running?');
  }
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
  clip: '✂ Clip', full: '↓ Video',
  audio: '♪ Audio', transcript: '📄 Transcript', ai: '✦ AI',
};

async function refreshJobsPanel() {
  try {
    const r = await fetch('/api/jobs');
    const jobs = await r.json();
    const list = $('jobs-list');
    const count = $('jobs-count');
    if (!list) return;
    if (count) count.textContent = jobs.length;

    if (!jobs.length) {
      list.innerHTML = `
        <div class="jobs-empty">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          <p>No downloads yet</p><span>Jobs will appear here</span>
        </div>`;
      return;
    }

    list.innerHTML = jobs.slice(0, 12).map(job => {
      const isRunning = job.status === 'running';
      const hasReal   = isRunning && job.progress > 0;
      const indet     = isRunning && !hasReal;
      const bar = isRunning ? `
        <div class="job-bar">
          <div class="job-bar-fill ${indet ? 'indeterminate' : ''}"
               style="width:${indet ? 0 : job.progress}%"></div>
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
   DOWNLOAD — two-step
═══════════════════════════════════════════════════ */
const DL_STEPS = ['step-url-dl', 'step-options-dl', 'step-done-dl'];

function setStep(steps, active) {
  steps.forEach((id, i) => {
    const el = $(id);
    if (!el) return;
    el.classList.remove('active', 'done');
    if (i < active)  el.classList.add('done');
    if (i === active) el.classList.add('active');
  });
}

$('dl-url-continue').addEventListener('click', () => {
  const url = $('dl-url').value.trim();
  const err = $('dl-url-error');
  if (!url || !url.startsWith('http')) {
    err.textContent = !url ? '⚠ Paste a video URL to continue.' : '⚠ That doesn\'t look like a valid URL.';
    err.classList.remove('hidden');
    return;
  }
  err.classList.add('hidden');
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

$('dl-clip-toggle').addEventListener('change', e => {
  $('dl-clip-fields').classList.toggle('hidden', !e.target.checked);
});

$('btn-download').addEventListener('click', async () => {
  const url      = $('dl-url').value.trim();
  const filename = $('dl-filename').value.trim() || 'video';
  const quality  = $('dl-quality').value;
  const isClip   = $('dl-clip-toggle').checked;
  const start    = $('dl-start').value.trim();
  const end      = $('dl-end').value.trim();

  if (isClip) {
    if (!start) { showStatus('dl-status', 'error', 'Enter a start time (HH:MM:SS).'); $('dl-status').classList.remove('hidden'); return; }
    if (!end)   { showStatus('dl-status', 'error', 'Enter an end time (HH:MM:SS).');  $('dl-status').classList.remove('hidden'); return; }
  }

  const endpoint = isClip ? '/api/download/clip' : '/api/download/full';
  const body     = isClip ? { url, filename, quality, start, end } : { url, filename, quality };

  showStatus('dl-status', 'running', isClip ? `Clipping ${start} → ${end}…` : 'Downloading…');
  $('dl-status').classList.remove('hidden');

  try {
    const r = await fetch(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const { job_id, error } = await r.json();
    if (error) { showStatus('dl-status', 'error', error); return; }

    pollJob(job_id,
      job => showStatus('dl-status', 'running', job.message, job.progress),
      job => {
        showStatus('dl-status', 'done', job.message, null, job.result);
        setStep(DL_STEPS, 2);
      },
      job => showStatus('dl-status', 'error', job.error || 'Download failed.')
    );
  } catch {
    showStatus('dl-status', 'error', 'Could not reach the server. Is ClipperOS running?');
  }
});

/* ═══════════════════════════════════════════════════
   AUDIO — two-step
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
  const err = $('au-url-error');
  if (!url) { err.textContent = '⚠ Paste a video URL to continue.'; err.classList.remove('hidden'); return; }
  err.classList.add('hidden');
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

  showStatus('au-status', 'running', `Extracting ${selectedFormat.toUpperCase()} audio…`);
  $('au-status').classList.remove('hidden');

  try {
    const r = await fetch('/api/download/audio', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, filename, format: selectedFormat }),
    });
    const { job_id, error } = await r.json();
    if (error) { showStatus('au-status', 'error', error); return; }

    pollJob(job_id,
      job => showStatus('au-status', 'running', job.message, job.progress),
      job => showStatus('au-status', 'done', job.message, null, job.result),
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
    showStatus('tr-status', 'running', 'Downloading transcript…');
    $('tr-status').classList.remove('hidden');
    $('tr-result').classList.add('hidden');

    try {
      const r = await fetch('/api/transcript', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const { job_id, error } = await r.json();
      if (error) { showStatus('tr-status', 'error', error); return; }

      pollJob(job_id,
        job => showStatus('tr-status', 'running', job.message, job.progress),
        job => { showStatus('tr-status', 'done', job.message); renderTranscript(job.result); },
        job => showStatus('tr-status', 'error', job.error || 'Transcript download failed.')
      );
    } catch {
      showStatus('tr-status', 'error', 'Could not reach the server. Is ClipperOS running?');
    }
  });
}

function renderTranscript(result) {
  if (!result) return;
  const el  = $('tr-result');
  const tag = result.cached
    ? ' <span style="font-size:10px;background:#d1fae5;color:#065f46;padding:1px 6px;border-radius:10px;font-weight:600">cached</span>'
    : '';
  el.innerHTML = `
    <div class="tc-header">
      <span class="tc-title">${esc(result.title || result.video_id)}${tag}</span>
      <span class="tc-meta">${(result.word_count||0).toLocaleString()} words · ${esc(result.platform)}</span>
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
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
          <p>No history yet</p><span>Your downloads will appear here</span>
        </div>`;
      return;
    }
    const kindMap = { CLIP: 'kind-clip', FULL: 'kind-full', AUDIO: 'kind-audio' };
    el.innerHTML = entries.map(e => {
      if (!e.kind) return `<div class="history-card"><div class="history-body"><div class="history-name">${esc(e.raw)}</div></div></div>`;
      const time = (e.time || '').split(' ')[1] || e.time;
      return `
      <div class="history-card">
        <span class="history-kind ${kindMap[e.kind] || 'kind-full'}">${esc(e.kind)}</span>
        <div class="history-body">
          <div class="history-name">${esc(e.name)}</div>
          <div class="history-detail">${esc(e.platform)} · ${esc(e.url.slice(0,60))}${e.url.length>60?'…':''}</div>
        </div>
        <span class="history-time">${esc(time)}</span>
      </div>`;
    }).join('');
  } catch {
    el.innerHTML = '<p style="color:var(--text-tertiary);font-size:13px;padding:20px 0">Could not load history.</p>';
  }
}

/* ═══════════════════════════════════════════════════
   AUTH — unchanged from v1.4
═══════════════════════════════════════════════════ */
let _authMethod = 'cookies_file';

function setAuthMethod(method) {
  _authMethod = method;
  document.querySelectorAll('.auth-method-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.method === method);
  });
  $('auth-panel-cookies')?.classList.toggle('hidden', method !== 'cookies_file');
  $('auth-panel-browser')?.classList.toggle('hidden', method !== 'browser_cookies');
  const howText = $('auth-how-it-works-text');
  if (howText) {
    howText.textContent = method === 'browser_cookies'
      ? 'ClipperOS reads cookies from your browser profile via yt-dlp. May not work on Windows with recent Chromium versions.'
      : 'Export cookies once from your browser. ClipperOS stores the file locally and never exposes cookie values.';
  }
}

document.querySelectorAll('.auth-method-tab').forEach(tab => {
  tab.addEventListener('click', () => setAuthMethod(tab.dataset.method));
});

function formatCookiesUpdated(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: 'numeric', minute: '2-digit',
    });
  } catch { return ''; }
}

async function uploadCookies(fileInput, msgEl, onSuccess) {
  const file = fileInput?.files?.[0];
  if (!file) {
    showStatus('auth-msg', 'error', 'Choose a cookies.txt file first.');
    msgEl?.classList.remove('hidden');
    return false;
  }
  showStatus('auth-msg', 'running', 'Uploading cookies and verifying your YouTube session…');
  msgEl?.classList.remove('hidden');
  const form = new FormData();
  form.append('cookies', file);
  try {
    const { data: result } = await fetchJson('/api/auth/cookies', { method: 'POST', body: form });
    if (result.connected) {
      showStatus('auth-msg', 'done', 'YouTube connected. Downloads will use your cookies until they expire.');
      fileInput.value = '';
      await onSuccess?.();
      return true;
    }
    showStatus('auth-msg', 'error',
      result.detail || result.error || 'Could not verify your YouTube session. Export fresh cookies and try again.');
    return false;
  } catch (err) {
    showStatus('auth-msg', 'error', err.message || 'Request failed.');
    return false;
  }
}

async function loadAuthStatus() {
  const pill         = $('auth-status-pill');
  const dot          = $('auth-status-dot');
  const label        = $('auth-status-label');
  const connState    = $('auth-connected-state');
  const connDetail   = $('auth-connected-detail');
  const connForm     = $('auth-connect-form');
  const refreshPanel = $('auth-refresh-panel');
  const refreshBtn   = $('btn-refresh-cookies');
  const browserSel   = $('auth-browser-select');
  const sidebarDot   = $('sidebar-auth-dot');
  const howItWorks   = $('auth-how-it-works');
  if (!pill) return;
  try {
    const { data: status } = await fetchJson('/api/auth/status');
    if (!status.providers) {
      showStatus('auth-msg', 'error',
        'ClipperOS is running an old version. Stop it (Ctrl+C), then run: python webapp.py');
      $('auth-msg')?.classList.remove('hidden');
    }
    if (browserSel && status.browsers && status.browsers.length) {
      const current = status.browser || '';
      browserSel.innerHTML = '<option value="">Select a browser...</option>' +
        status.browsers.map(b =>
          `<option value="${esc(b.id || b)}" ${(b.id || b) === current ? 'selected' : ''}>${esc(b.label || b)}</option>`
        ).join('');
    } else if (browserSel) {
      browserSel.innerHTML = '<option value="">No browsers detected</option>';
    }
    if (status.connected) {
      pill.className = 'auth-status-pill connected';
      dot.style.background = 'var(--green)';
      label.textContent    = 'Connected';
      connState.classList.remove('hidden');
      connForm.classList.add('hidden');
      howItWorks?.classList.add('hidden');
      if (status.provider === 'cookies_file') {
        const updated = formatCookiesUpdated(status.cookies_updated_at);
        connDetail.textContent = updated
          ? `Using cookies.txt · updated ${updated}`
          : (status.detail || 'Using cookies.txt');
        refreshBtn?.classList.remove('hidden');
        refreshPanel?.classList.add('hidden');
      } else {
        connDetail.textContent = `Using ${status.browser || 'browser'}${status.profile ? ' · ' + status.profile : ''}`;
        refreshBtn?.classList.add('hidden');
        refreshPanel?.classList.add('hidden');
      }
      if (sidebarDot) sidebarDot.classList.remove('hidden');
    } else {
      pill.className = 'auth-status-pill';
      dot.style.background = 'var(--text-tertiary)';
      label.textContent    = 'Not connected';
      connState.classList.add('hidden');
      connForm.classList.remove('hidden');
      refreshPanel?.classList.add('hidden');
      howItWorks?.classList.remove('hidden');
      setAuthMethod(status.cookies_configured ? 'cookies_file' : _authMethod);
      if (sidebarDot) sidebarDot.classList.add('hidden');
    }
  } catch {
    if (label) label.textContent = 'Unavailable';
  }
}

const btnUploadConnect = $('btn-upload-cookies-connect');
if (btnUploadConnect) {
  btnUploadConnect.addEventListener('click', async () => {
    btnUploadConnect.classList.add('loading');
    btnUploadConnect.textContent = '⏳ Verifying…';
    try {
      await uploadCookies($('auth-cookies-file-connect'), $('auth-msg'), loadAuthStatus);
    } finally {
      btnUploadConnect.classList.remove('loading');
      btnUploadConnect.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/>
          <line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
        Upload &amp; Connect`;
    }
  });
}

const btnRefreshCookies = $('btn-refresh-cookies');
if (btnRefreshCookies) {
  btnRefreshCookies.addEventListener('click', () => {
    $('auth-refresh-panel')?.classList.toggle('hidden');
  });
}

const btnUploadRefresh = $('btn-upload-cookies');
if (btnUploadRefresh) {
  btnUploadRefresh.addEventListener('click', async () => {
    btnUploadRefresh.classList.add('loading');
    btnUploadRefresh.textContent = '⏳ Verifying…';
    try {
      const ok = await uploadCookies($('auth-cookies-file'), $('auth-msg'), loadAuthStatus);
      if (ok) $('auth-refresh-panel')?.classList.add('hidden');
    } finally {
      btnUploadRefresh.classList.remove('loading');
      btnUploadRefresh.textContent = 'Upload & Verify';
    }
  });
}

const btnConnect = $('btn-connect');
if (btnConnect) {
  btnConnect.addEventListener('click', async () => {
    const browser = $('auth-browser-select')?.value?.trim();
    const profile = $('auth-profile-input')?.value?.trim() || null;
    const msgEl   = $('auth-msg');
    if (!browser) {
      showStatus('auth-msg', 'error', 'Select a browser first.');
      msgEl.classList.remove('hidden');
      return;
    }
    btnConnect.classList.add('loading');
    btnConnect.textContent = '⏳ Verifying session…';
    showStatus('auth-msg', 'running', 'Connecting to YouTube via your browser session. This may take a few seconds…');
    msgEl.classList.remove('hidden');
    try {
      const { data: result } = await fetchJson('/api/auth/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'browser_cookies', browser, profile }),
      });
      if (result.connected) {
        showStatus('auth-msg', 'done', 'YouTube connected successfully. Downloads will now use your browser session.');
        await loadAuthStatus();
      } else {
        showStatus('auth-msg', 'error',
          result.detail || result.error || 'Could not verify your YouTube session. Try the cookies file method instead.');
      }
    } catch (err) {
      showStatus('auth-msg', 'error', err.message || 'Request failed.');
    } finally {
      btnConnect.classList.remove('loading');
      btnConnect.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
          <polyline points="10 17 15 12 10 7"/>
          <line x1="15" y1="12" x2="3" y2="12"/>
        </svg>
        Connect YouTube`;
    }
  });
}

const btnDisconnect = $('btn-disconnect');
if (btnDisconnect) {
  btnDisconnect.addEventListener('click', async () => {
    const msgEl = $('auth-msg');
    try {
      await fetch('/api/auth/disconnect', { method: 'POST' });
      showStatus('auth-msg', 'done', 'Disconnected. ClipperOS will no longer use your YouTube session.');
      msgEl.classList.remove('hidden');
      await loadAuthStatus();
    } catch {
      showStatus('auth-msg', 'error', 'Disconnect failed. Try restarting ClipperOS.');
      msgEl.classList.remove('hidden');
    }
  });
}

/* ═══════════════════════════════════════════════════
   UTILS
═══════════════════════════════════════════════════ */
function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
