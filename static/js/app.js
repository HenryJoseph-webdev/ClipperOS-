/* ClipperOS frontend — app.js v1.3 */

const $ = id => document.getElementById(id);

/* ── Tab switching ──────────────────────────────────────────────────────────*/
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'history') loadHistory();
  });
});

/* ── Platform detection ─────────────────────────────────────────────────────*/
const PLATFORM_LABELS = { youtube: '▶ YouTube', twitch: '● Twitch', kick: '⚡ Kick' };

function setupPlatformDetect(inputId, badgeId) {
  let timer = null;
  const input = $(inputId), badge = $(badgeId);
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const url = input.value.trim();
      if (!url) { badge.classList.add('hidden'); return; }
      try {
        const r = await fetch('/api/detect', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });
        const { platform } = await r.json();
        if (platform && platform !== 'unknown') {
          badge.textContent = PLATFORM_LABELS[platform] || platform;
          badge.classList.remove('hidden');
        } else { badge.classList.add('hidden'); }
      } catch { badge.classList.add('hidden'); }
    }, 400);
  });
}

setupPlatformDetect('dl-url', 'dl-platform');
setupPlatformDetect('au-url', 'au-platform');
setupPlatformDetect('tr-url', 'tr-platform');
setupPlatformDetect('ai-url', 'ai-platform');

/* ── Job polling ────────────────────────────────────────────────────────────*/
const activePolls = {};

function pollJob(jobId, onUpdate, onDone, onError) {
  if (activePolls[jobId]) return;
  activePolls[jobId] = setInterval(async () => {
    try {
      const r = await fetch(`/api/job/${jobId}`);
      const job = await r.json();
      onUpdate(job);
      if (job.status === 'done') {
        clearInterval(activePolls[jobId]); delete activePolls[jobId];
        onDone(job); refreshJobsList();
      } else if (job.status === 'error') {
        clearInterval(activePolls[jobId]); delete activePolls[jobId];
        onError(job); refreshJobsList();
      }
    } catch {}
  }, 800);
}

/* ── Status card ────────────────────────────────────────────────────────────*/
function showStatus(cardId, state, msg, progress = null) {
  const el = $(cardId);
  el.className = `status-card ${state}`;
  const icons = { running: '⏳', done: '✅', error: '❌' };
  const barHTML = state === 'running'
    ? `<div class="progress-bar"><div class="progress-fill ${progress === null ? 'indeterminate' : ''}" style="width:${progress ?? 0}%"></div></div>`
    : '';
  el.innerHTML = `<span class="status-msg">${icons[state] || ''} ${msg}${barHTML}</span>`;
}

/* ── Download clip ──────────────────────────────────────────────────────────*/
$('btn-clip').addEventListener('click', async () => {
  const url = $('dl-url').value.trim(), start = $('dl-start').value.trim(),
        end = $('dl-end').value.trim(), filename = $('dl-filename').value.trim() || 'clip',
        quality = $('dl-quality').value;
  if (!url || !start || !end) {
    showStatus('dl-status', 'error', !url ? 'Paste a video URL first.' : !start ? 'Enter a start time.' : 'Enter an end time.');
    return;
  }
  showStatus('dl-status', 'running', `Clipping ${start} → ${end}...`);
  try {
    const r = await fetch('/api/download/clip', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, start, end, filename, quality }),
    });
    const { job_id, error } = await r.json();
    if (error) { showStatus('dl-status', 'error', error); return; }
    pollJob(job_id,
      job => showStatus('dl-status', 'running', job.message, job.progress),
      job => showStatus('dl-status', 'done', `Saved as <strong>${job.result?.filename}</strong> · ${quality}`),
      job => showStatus('dl-status', 'error', job.error || 'Download failed.')
    );
  } catch { showStatus('dl-status', 'error', 'Network error — is the server running?'); }
});

/* ── Download full ──────────────────────────────────────────────────────────*/
$('btn-full').addEventListener('click', async () => {
  const url = $('dl-url').value.trim(), filename = $('dl-filename').value.trim() || 'video',
        quality = $('dl-quality').value;
  if (!url) { showStatus('dl-status', 'error', 'Paste a video URL first.'); return; }
  showStatus('dl-status', 'running', 'Downloading full video...');
  try {
    const r = await fetch('/api/download/full', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, filename, quality }),
    });
    const { job_id, error } = await r.json();
    if (error) { showStatus('dl-status', 'error', error); return; }
    pollJob(job_id,
      job => showStatus('dl-status', 'running', job.message, job.progress),
      job => showStatus('dl-status', 'done', `Saved as <strong>${job.result?.filename}</strong> · ${quality}`),
      job => showStatus('dl-status', 'error', job.error || 'Download failed.')
    );
  } catch { showStatus('dl-status', 'error', 'Network error — is the server running?'); }
});

/* ── Audio only ─────────────────────────────────────────────────────────────*/
$('btn-audio').addEventListener('click', async () => {
  const url = $('au-url').value.trim(), filename = $('au-filename').value.trim() || 'audio',
        format = $('au-format').value;
  if (!url) { showStatus('au-status', 'error', 'Paste a video URL first.'); return; }
  showStatus('au-status', 'running', `Extracting ${format.toUpperCase()} audio...`);
  try {
    const r = await fetch('/api/download/audio', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, filename, format }),
    });
    const { job_id, error } = await r.json();
    if (error) { showStatus('au-status', 'error', error); return; }
    pollJob(job_id,
      job => showStatus('au-status', 'running', job.message, job.progress),
      job => showStatus('au-status', 'done', `Saved as <strong>${job.result?.filename}</strong>`),
      job => showStatus('au-status', 'error', job.error || 'Audio extraction failed.')
    );
  } catch { showStatus('au-status', 'error', 'Network error — is the server running?'); }
});

/* ── Transcript ─────────────────────────────────────────────────────────────*/
$('btn-transcript') && $('btn-transcript').addEventListener('click', async () => {
  const url = $('tr-url').value.trim();
  if (!url) { showStatus('tr-status', 'error', 'Paste a YouTube URL first.'); return; }
  showStatus('tr-status', 'running', 'Downloading transcript...');
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
  } catch { showStatus('tr-status', 'error', 'Network error — is the server running?'); }
});

function renderTranscript(result) {
  if (!result) return;
  const el = $('tr-result');
  const cachedBadge = result.cached ? '<span class="cache-badge" style="margin-left:8px">cached</span>' : '';
  el.innerHTML = `
    <div class="tr-header">
      <span class="tr-title">${escHtml(result.title || result.video_id)}${cachedBadge}</span>
      <span class="tr-meta">${result.word_count.toLocaleString()} words · ${result.platform}</span>
    </div>
    <div class="tr-preview">${escHtml(result.preview || '')}</div>
    ${result.file_path ? `<div class="tr-path">📁 ${escHtml(result.file_path)}</div>` : ''}
  `;
  el.classList.remove('hidden');
}

/* ── AI Analyze ─────────────────────────────────────────────────────────────*/
$('btn-analyze').addEventListener('click', async () => {
  const url = $('ai-url').value.trim(), prompt_type = $('ai-prompt').value;
  if (!url) { showStatus('ai-status', 'error', 'Paste a video URL first.'); return; }
  showStatus('ai-status', 'running', 'Starting analysis...');
  $('ai-results').classList.add('hidden');
  try {
    const r = await fetch('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, prompt_type }),
    });
    const { job_id, error } = await r.json();
    if (error) { showStatus('ai-status', 'error', error); return; }
    pollJob(job_id,
      job => showStatus('ai-status', 'running', job.message, job.progress),
      job => { showStatus('ai-status', 'done', job.message); renderClips(job.result); },
      job => showStatus('ai-status', 'error', job.error || 'Analysis failed.')
    );
  } catch { showStatus('ai-status', 'error', 'Network error — is the server running?'); }
});

/* ── Render AI clips (with download button on each) ─────────────────────────*/
function renderClips(result) {
  if (!result || !result.clips || !result.clips.length) return;
  const { clips, cached, url: sourceUrl } = result;
  $('ai-results-count').textContent = `${clips.length} clips found`;
  $('ai-results-badge').textContent = cached ? 'cached' : 'fresh';
  $('ai-results').classList.remove('hidden');

  $('ai-clips-list').innerHTML = clips.map(clip => {
    const scoreClass = clip.score >= 8 ? 'score-high' : clip.score >= 6 ? 'score-mid' : 'score-low';
    const dur = calcDuration(clip.start, clip.end);
    const clipJson = escAttr(JSON.stringify(clip));
    const urlJson  = escAttr(JSON.stringify(sourceUrl || ''));
    return `
    <div class="clip-card">
      <div class="clip-rank">${clip.rank}</div>
      <div class="clip-body">
        <div class="clip-title">${escHtml(clip.title)}</div>
        <div class="clip-reason">${escHtml(clip.reason)}</div>
        <div class="clip-meta">
          <span class="clip-time">${clip.start} → ${clip.end}</span>
          <span class="clip-duration">${dur}</span>
          <span class="clip-score ${scoreClass}">⭐ ${clip.score.toFixed(1)}</span>
        </div>
      </div>
      <div class="clip-dl-btn">
        <button class="btn btn-primary btn-sm"
          onclick='openClipModal(${clipJson}, ${urlJson})'>
          ↓ Clip
        </button>
      </div>
    </div>`;
  }).join('');
}

function calcDuration(start, end) {
  const toSec = ts => { const p = ts.split(':'); return +p[0]*3600 + +p[1]*60 + parseFloat(p[2]); };
  try { const d = Math.round(toSec(end) - toSec(start)); return `${Math.floor(d/60)}m ${d%60}s`; }
  catch { return ''; }
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function escAttr(s) {
  return String(s).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

/* ── Clip download modal ────────────────────────────────────────────────────*/
let pendingClip = null;

function openClipModal(clip, sourceUrl) {
  pendingClip = clip;
  $('modal-title').textContent = clip.title;
  $('modal-meta').textContent  = `${clip.start} → ${clip.end}  ·  score ${clip.score.toFixed(1)}  ·  ${calcDuration(clip.start, clip.end)}`;
  $('modal-url').value      = sourceUrl || $('ai-url').value || '';
  $('modal-filename').value = (clip.title || 'clip').replace(/\s+/g,'_').replace(/[^\w]/g,'').slice(0,60);
  $('modal-status').className = 'status-card hidden';
  $('clip-modal').classList.remove('hidden');
  $('modal-overlay').classList.remove('hidden');
}

function closeModal() {
  $('clip-modal').classList.add('hidden');
  $('modal-overlay').classList.add('hidden');
  pendingClip = null;
}

$('modal-close').addEventListener('click', closeModal);
$('modal-cancel').addEventListener('click', closeModal);
$('modal-overlay').addEventListener('click', closeModal);

$('modal-download').addEventListener('click', async () => {
  if (!pendingClip) return;
  const url = $('modal-url').value.trim(), filename = $('modal-filename').value.trim() || 'clip',
        quality = $('modal-quality').value;
  if (!url) { showStatus('modal-status', 'error', 'Paste the video URL above.'); return; }
  showStatus('modal-status', 'running', 'Starting download...');
  try {
    const r = await fetch('/api/download/clip', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, filename, quality, start: pendingClip.start, end: pendingClip.end }),
    });
    const { job_id, error } = await r.json();
    if (error) { showStatus('modal-status', 'error', error); return; }
    pollJob(job_id,
      job => showStatus('modal-status', 'running', job.message, job.progress),
      job => { showStatus('modal-status', 'done', `Saved as ${job.result?.filename}`); setTimeout(closeModal, 1800); },
      job => showStatus('modal-status', 'error', job.error || 'Download failed.')
    );
  } catch { showStatus('modal-status', 'error', 'Network error.'); }
});

/* ── Jobs sidebar ───────────────────────────────────────────────────────────*/
const TYPE_LABEL = { clip: '✂ Clip', full: '↓ Full', audio: '♪ Audio', transcript: '📄 Transcript', ai: '✦ AI' };

async function refreshJobsList() {
  try {
    const r = await fetch('/api/jobs');
    const jobs = await r.json();
    const el = $('jobs-list');
    if (!jobs.length) { el.innerHTML = '<p class="empty-hint">No jobs yet</p>'; return; }
    el.innerHTML = jobs.slice(0, 8).map(job => `
      <div class="job-chip ${job.status}">
        <div class="job-dot"></div>
        <span class="job-label">${TYPE_LABEL[job.type] || job.type} · ${escHtml((job.message || '').slice(0,26))}</span>
        <span class="job-time">${job.created_at}</span>
      </div>`).join('');
  } catch {}
}

setInterval(refreshJobsList, 3000);
refreshJobsList();

/* ── History ────────────────────────────────────────────────────────────────*/
async function loadHistory() {
  const el = $('history-list');
  try {
    const r = await fetch('/api/history');
    const entries = await r.json();
    if (!entries.length) { el.innerHTML = '<p class="empty-hint">No downloads yet.</p>'; return; }
    el.innerHTML = entries.map(e => {
      if (!e.kind) return `<div class="history-entry">${escHtml(e.raw)}</div>`;
      const kindClass = e.kind === 'CLIP' ? 'kind-clip' : 'kind-full';
      return `
      <div class="history-card">
        <span class="history-kind ${kindClass}">${e.kind}</span>
        <div class="history-body">
          <div class="history-name">${escHtml(e.name)}</div>
          <div class="history-detail">${escHtml(e.platform)} · <a href="${escHtml(e.url)}" style="color:var(--text-3)">${escHtml(e.url.slice(0,55))}${e.url.length > 55 ? '...' : ''}</a></div>
        </div>
        <span class="history-time">${e.time.split(' ')[1] || e.time}</span>
      </div>`;
    }).join('');
  } catch { el.innerHTML = '<p class="empty-hint">Could not load history.</p>'; }
}
