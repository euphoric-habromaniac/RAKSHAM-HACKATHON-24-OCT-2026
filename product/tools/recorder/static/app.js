'use strict';
// Asli Awaaz recorder page. Nothing is kept in the browser: every clip is PUT to the local recorder server,
// which writes <recordings dir>/<Speaker Name>/N.wav. Sections: pure helpers, upload queue, state, screens, capture.

const TARGET_RATE = 16000;
const MIN_SECONDS = 1.5;
const CLIP_LEVEL = 0.99;
const QUIET_PEAK = 0.02;
const PING_MS = 4000;
const PROMPT_COUNT = 100;

// ---------- pure helpers (no DOM; tested under node by tests/test_recorder_js.py) ----------
function peakOf(pcm) {
  let peak = 0;
  for (let i = 0; i < pcm.length; i++) peak = Math.max(peak, Math.abs(pcm[i]));
  return peak;
}

function audioStats(pcm) {
  let sum = 0;
  for (let i = 0; i < pcm.length; i++) sum += pcm[i] * pcm[i];
  const rms = Math.sqrt(sum / (pcm.length || 1)), peak = peakOf(pcm);
  return { peak, rms_dbfs: rms > 0 ? 20 * Math.log10(rms) : -120, clipped: peak >= CLIP_LEVEL };
}

function takeWarning(pcm) {
  const dur = pcm.length / TARGET_RATE, peak = peakOf(pcm);
  if (dur < MIN_SECONDS) return `Too short (${dur.toFixed(1)} s, need ${MIN_SECONDS}+ s). Please redo.`;
  if (peak >= CLIP_LEVEL) return 'Clipped (too loud). Please redo a little further from the mic.';
  if (peak < QUIET_PEAK) return 'Very quiet. Check the mic and redo.';
  return '';
}

function concatChunks(chunks) {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.length; }
  return out;
}

// plain linear resampling; the page prefers the browser's OfflineAudioContext and uses this only as a fallback
function resampleLinear(pcm, fromRate, toRate) {
  if (fromRate === toRate) return pcm;
  const n = Math.floor(pcm.length * toRate / fromRate), out = new Float32Array(n), step = fromRate / toRate;
  for (let i = 0; i < n; i++) {
    const pos = i * step, i0 = Math.floor(pos), i1 = Math.min(i0 + 1, pcm.length - 1), f = pos - i0;
    out[i] = pcm[i0] * (1 - f) + pcm[i1] * f;
  }
  return out;
}

// 16 kHz mono 16-bit PCM WAV
function wavBytes(pcm) {
  const buf = new ArrayBuffer(44 + pcm.length * 2), v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + pcm.length * 2, true); str(8, 'WAVE');
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, TARGET_RATE, true); v.setUint32(28, TARGET_RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, 'data'); v.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) v.setInt16(44 + i * 2, Math.round(Math.max(-1, Math.min(1, pcm[i])) * 32767), true);
  return buf;
}

function normName(x) {
  return String(x || '').normalize('NFC').toLowerCase().replace(/[^\p{L}\p{N}\p{M}\s]/gu, '').replace(/\s+/g, ' ').trim();
}

// 0-based index of the first sentence (numbers 1..total) that is not in doneNumbers; total when all are done
function firstUndoneIndex(total, doneNumbers) {
  const done = new Set(doneNumbers);
  for (let n = 1; n <= total; n++) if (!done.has(n)) return n - 1;
  return total;
}

const clipUrl = (name, n) => `/api/clip?name=${encodeURIComponent(name)}&n=${n}`;
const zipUrl = name => (name ? `/api/zip?name=${encodeURIComponent(name)}` : '/api/zip');
const pad2 = n => String(n).padStart(2, '0');
const fmtTime = d => `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
const progressText = (done, total) => `${done}/${total} saved`;

// {ok, text} of the status bar
function statusInfo(s) {
  if (!s.serverOk) {
    const wait = s.pending ? ` | ${s.pending} clip(s) waiting in memory: keep this page open` : '';
    return { ok: false, text: `NOT SAVING: server unreachable${wait}` };
  }
  const who = s.name ? `${s.doneCount}/${s.total} saved for ${s.name}` : 'no speaker selected';
  return { ok: true, text: `SAVING TO DISK: ${s.dir} | last saved ${s.lastSaved || 'none yet'} | ${who}` };
}

// ---------- upload queue: serial, retries forever on network/5xx errors with backoff ----------
// opts: send(item) -> Promise (rejects with {permanent:true} for 4xx), onAck(item, res), onFail(item, err),
//       onChange(), sleep(ms) -> Promise
function createUploader(opts) {
  const queue = [];
  let running = false, failing = false, wake = null, waiters = [];
  const sleep = opts.sleep || (ms => new Promise(r => { wake = r; setTimeout(r, ms); }));
  const backoff = attempts => Math.min(15000, 1000 * 2 ** Math.min(attempts - 1, 4));
  const change = () => { if (opts.onChange) opts.onChange(); };

  async function attempt(item) {
    item.attempts += 1;
    try {
      const res = await opts.send(item);
      queue.shift(); failing = false; opts.onAck(item, res);
    } catch (err) {
      if (err && err.permanent) { queue.shift(); opts.onFail(item, err); return; }
      failing = true; change();
      await sleep(backoff(item.attempts));
    }
  }

  async function run() {
    if (running) return;
    running = true;
    while (queue.length) { await attempt(queue[0]); change(); }
    running = false;
    waiters.forEach(w => w());
    waiters = [];
    change();
  }

  return {
    enqueue(item) {
      const dup = queue.findIndex((q, i) => i > 0 && q.name === item.name && q.n === item.n); // not the one in flight
      if (dup > 0) queue.splice(dup, 1);
      queue.push(Object.assign({ attempts: 0 }, item));
      change();
      run();
    },
    pending: () => queue.length,
    failing: () => failing,
    retryNow() { if (wake) wake(); run(); },
    whenIdle(ms) {
      if (!queue.length && !running) return Promise.resolve(true);
      return new Promise(resolve => { waiters.push(() => resolve(true)); setTimeout(() => resolve(false), ms); });
    },
  };
}

// ---------- server calls ----------
async function apiJson(path, init) {
  const r = await fetch(path, init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok || body.ok === false) {
    const e = new Error(body.error || `HTTP ${r.status}`);
    e.status = r.status;
    e.permanent = r.status >= 400 && r.status < 500;
    throw e;
  }
  return body;
}

const sendClip = item => apiJson(clipUrl(item.name, item.n), { method: 'PUT', headers: { 'Content-Type': 'audio/wav' }, body: item.blob });

// ---------- state (memory only, lost on reload; the truth is on disk) ----------
const app = { prompts: [], speakers: [], dir: '', serverOk: false, lastSaved: '', note: '', noteTimer: 0,
  profile: null, done: new Set(), takes: new Map(), states: new Map(), idx: 0, resumeNote: '', previewUrl: '' };
const rec = { ctx: null, stream: null, node: null, chunks: [], on: false };
let uploader = null;
const $ = id => document.getElementById(id);
const show = (id, on) => $(id).classList.toggle('hidden', !on);
const stateKey = (name, n) => `${name}\u0000${n}`;

// ---------- status bar and zip links ----------
function renderStatus() {
  const info = statusInfo({ serverOk: app.serverOk, pending: uploader ? uploader.pending() : 0, dir: app.dir, lastSaved: app.lastSaved,
    name: app.profile ? app.profile.name : '', doneCount: app.done.size, total: PROMPT_COUNT });
  $('save-bar').className = 'save-bar ' + (info.ok ? 'on' : 'off');
  $('save-text').textContent = info.text + (app.note ? ` | ${app.note}` : '');
  show('btn-retry', !info.ok);
  const link = $('zip-speaker');
  link.setAttribute('aria-disabled', app.profile ? 'false' : 'true');
  link.href = app.profile ? zipUrl(app.profile.name) : '#';
  $('complete-zip').href = link.href;
}

function flash(text) {
  app.note = text;
  clearTimeout(app.noteTimer);
  app.noteTimer = setTimeout(() => { app.note = ''; renderStatus(); }, 8000);
  renderStatus();
}

function guardZip(e) {
  const pending = uploader.pending();
  if (e.currentTarget.getAttribute('aria-disabled') === 'true') e.preventDefault();
  else if (pending > 0) { e.preventDefault(); flash(`${pending} clip(s) still saving: press Download zip again in a moment`); }
}

function triggerDownload(url) {
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ---------- connection ----------
async function connect() {
  try {
    if (!app.prompts.length) app.prompts = await apiJson('/api/prompts');
    const info = await apiJson('/api/info');
    app.dir = info.dir;
    const was = app.serverOk;
    app.serverOk = true;
    if (!was) await refreshSpeakers();
    if (!was || uploader.failing()) uploader.retryNow();
  } catch (err) {
    app.serverOk = false;
  }
  renderStatus();
}

// ---------- start screen ----------
function option(value, text) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = text;
  return o;
}

async function refreshSpeakers() {
  try { app.speakers = await apiJson('/api/speakers'); } catch (err) { return; }
  const sel = $('speaker-list');
  sel.textContent = '';
  sel.appendChild(option('', app.speakers.length ? 'Choose a speaker...' : 'No speakers yet: use New speaker below'));
  for (const s of app.speakers) sel.appendChild(option(s.name, `${s.name}  -  ${s.done}/${PROMPT_COUNT} done`));
  $('btn-continue').disabled = !app.speakers.length;
}

function readForm() {
  return { name: $('full-name').value.trim(), age_band: $('age-band').value, gender: $('gender').value, accent_group: $('accent-group').value,
    device: $('device').value.trim(), consent_language: $('language').value, allow_recording: $('c-rec').checked,
    allow_spoof_testing: $('c-spoof').checked, allow_voice_cloning: $('c-clone').checked };
}

function formProblem(f) {
  if (!f.name) return 'Type the full name as signature.';
  if (!f.age_band || !f.accent_group || !f.device || !f.consent_language) return 'Fill age band, accent group, device and consent language.';
  if (!f.allow_recording) return 'Recording consent must be ticked to continue.';
  return '';
}

function onNameTyped() {
  const key = normName($('full-name').value);
  const hit = key ? app.speakers.find(s => normName(s.name) === key) : null;
  show('exists-note', !!hit);
  if (hit) $('exists-note').textContent = `A speaker named "${hit.name}" already exists (${hit.done}/${PROMPT_COUNT} saved). Signing continues that speaker, keeps the same speaker ID and resumes where they stopped.`;
}

async function signAndStart() {
  const form = readForm(), problem = formProblem(form);
  $('profile-error').textContent = problem;
  if (problem) return;
  try {
    const view = await apiJson('/api/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
    enterSpeaker(view, view.existing ? 'Existing speaker continued' : 'New speaker saved');
  } catch (err) {
    $('profile-error').textContent = err.status ? err.message : 'Cannot reach the recorder server. Is it still running?';
  }
}

async function continueSelected() {
  const name = $('speaker-list').value;
  $('continue-note').textContent = name ? '' : 'Choose a speaker first.';
  if (!name) return;
  try {
    enterSpeaker(await apiJson(`/api/continue?name=${encodeURIComponent(name)}`, { method: 'POST', body: '' }), '');
  } catch (err) {
    $('continue-note').textContent = err.status ? err.message : 'Cannot reach the recorder server. Is it still running?';
  }
}

function resetForm() {
  for (const id of ['full-name', 'age-band', 'gender', 'accent-group', 'device', 'language']) $(id).value = '';
  for (const id of ['c-rec', 'c-spoof', 'c-clone']) $(id).checked = false;
  for (const id of ['profile-error', 'continue-note']) $(id).textContent = '';
  show('exists-note', false);
}

function enterSpeaker(view, lead) {
  app.profile = view.profile;
  app.done = new Set(view.done);
  app.takes = new Map();
  const k = app.done.size;
  app.resumeNote = k ? `Resuming: ${k} of ${PROMPT_COUNT} already saved` : `${lead || 'Starting'}: speaker ID ${view.profile.speaker_id}`;
  if (k >= PROMPT_COUNT) app.resumeNote = `All ${PROMPT_COUNT} sentences are already saved. Redo any you like.`;
  show('step-profile', false);
  show('step-complete', false);
  show('step-prompts', true);
  showPrompt(Math.min(firstUndoneIndex(PROMPT_COUNT, view.done), PROMPT_COUNT - 1));
  renderStatus();
}

async function switchSpeaker() {
  if (rec.on) return;
  app.profile = null;
  app.done = new Set();
  app.takes = new Map();
  resetForm();
  show('step-prompts', false);
  show('step-complete', false);
  show('step-profile', true);
  await refreshSpeakers();
  renderStatus();
}

// ---------- sentences ----------
const nOf = idx => idx + 1;

function showPrompt(idx) {
  app.idx = idx;
  const p = app.prompts[idx];
  $('prompt-counter').textContent = `Sentence ${nOf(idx)} of ${PROMPT_COUNT}`;
  $('prompt-category').textContent = `${p.lang} / ${p.topic}`;
  $('active-prompt-text').textContent = p.text;
  $('progress-fill').style.width = `${(app.done.size / PROMPT_COUNT) * 100}%`;
  $('jump-to').value = nOf(idx);
  $('btn-back').disabled = idx === 0;
  $('speaker-line').textContent = `${app.profile.name} (ID ${app.profile.speaker_id})`;
  show('btn-finish', idx + 1 >= PROMPT_COUNT);
  showTake();
}

function takeStateText() {
  const n = nOf(app.idx), st = app.states.get(stateKey(app.profile.name, n));
  if (st === 'saving') return { cls: 'saving', text: 'Saving to disk...' };
  if (st && st.failed) return { cls: 'failed', text: `NOT SAVED: ${st.failed}. Press Redo and record again.` };
  if (app.done.has(n)) return { cls: 'saved', text: '✓ saved to disk' };
  return { cls: '', text: '' };
}

function setPreview(url) {
  if (app.previewUrl.startsWith('blob:')) URL.revokeObjectURL(app.previewUrl);
  app.previewUrl = url || '';
  show('playback-container', !!url);
  if (url) $('audio-preview').src = url; else $('audio-preview').removeAttribute('src');
}

// the saved/saving line and the progress counters (cheap: does not touch the audio element)
function updateTakeState() {
  const st = takeStateText();
  $('take-state').textContent = st.text;
  $('take-state').className = 'take-state ' + st.cls;
  $('progress-note').textContent = `${app.resumeNote} | ${progressText(app.done.size, PROMPT_COUNT)}`;
  $('progress-fill').style.width = `${(app.done.size / PROMPT_COUNT) * 100}%`;
}

function showTake() {
  const n = nOf(app.idx), take = app.takes.get(n), done = app.done.has(n);
  $('take-warning').textContent = take ? take.warning : (done ? 'Already saved. Press Record to replace it.' : '');
  updateTakeState();
  if (take) setPreview(URL.createObjectURL(take.blob));
  else if (done) setPreview(`${clipUrl(app.profile.name, n)}&t=${Date.now()}`);
  else setPreview('');
  setButtons({ rec: !take, stop: false, redo: !!take, next: true });
  const last = app.idx + 1 >= PROMPT_COUNT;
  $('btn-next').textContent = last ? 'Finish' : (take || done ? 'Next →' : 'Skip →');
}

function setButtons(s) {
  $('btn-rec').disabled = !s.rec;
  $('btn-stop').disabled = !s.stop;
  $('btn-redo').disabled = !s.redo;
  $('btn-next').disabled = !s.next;
}

function redoTake() { app.takes.delete(nOf(app.idx)); showTake(); }
function prevPrompt() { if (app.idx > 0 && !rec.on) showPrompt(app.idx - 1); }

function jumpPrompt() {
  const n = parseInt($('jump-to').value, 10);
  if (!rec.on && n >= 1 && n <= PROMPT_COUNT) showPrompt(n - 1);
}

function nextPrompt() {
  if (rec.on) return;
  if (app.idx + 1 < PROMPT_COUNT) showPrompt(app.idx + 1); else showComplete();
}

function showComplete() {
  const k = app.done.size;
  show('step-prompts', false);
  show('step-complete', true);
  $('complete-title').textContent = k >= PROMPT_COUNT ? 'All sentences saved' : `${k} of ${PROMPT_COUNT} sentences saved`;
  $('complete-text').textContent = `${app.profile.name}: everything is already on disk in ${app.dir}. The zip below is only a copy to move or share.`;
  renderStatus();
}

async function finishAndZip() {
  if (rec.on) return;
  flash('Waiting for the last clip to be saved...');
  if (!(await uploader.whenIdle(20000))) return flash('Some clips are still saving. Check the status bar, then try again.');
  triggerDownload(zipUrl(app.profile.name));
  showComplete();
}

// ---------- saving (in the background, after every Stop) ----------
function onAck(item, res) {
  app.serverOk = true;
  app.lastSaved = fmtTime(new Date());
  app.states.delete(stateKey(item.name, item.n));
  if (app.profile && app.profile.name === item.name) {
    app.done.add(item.n);
    updateTakeState();
  }
  renderStatus();
}

function onFail(item, err) {
  app.states.set(stateKey(item.name, item.n), { failed: err.message });
  if (app.profile && app.profile.name === item.name) updateTakeState();
  renderStatus();
}

function onUploadChange() {
  if (uploader.failing()) app.serverOk = false;
  renderStatus();
}

function queueClip(n, take) {
  const name = app.profile.name;
  app.states.set(stateKey(name, n), 'saving');
  uploader.enqueue({ name, n, blob: take.blob });
}

// ---------- capture (raw PCM through Web Audio) ----------
async function startRecording() {
  if (!navigator.mediaDevices) {
    $('take-warning').textContent = 'Microphone unavailable: open the address printed by the recorder window in Chrome or Edge (not the HTML file itself).';
    return;
  }
  try {
    rec.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } });
  } catch (err) {
    $('take-warning').textContent = 'Microphone error: ' + err.message;
    return;
  }
  rec.ctx = new (window.AudioContext || window.webkitAudioContext)();
  await rec.ctx.resume();
  const src = rec.ctx.createMediaStreamSource(rec.stream);
  rec.node = rec.ctx.createScriptProcessor(4096, 1, 1);
  rec.chunks = [];
  rec.node.onaudioprocess = onAudioChunk;
  src.connect(rec.node);
  rec.node.connect(rec.ctx.destination);
  rec.on = true;
  $('take-warning').textContent = 'Recording...';
  setButtons({ rec: false, stop: true, redo: false, next: false });
}

function onAudioChunk(e) {
  if (!rec.on) return;
  const data = new Float32Array(e.inputBuffer.getChannelData(0));
  rec.chunks.push(data);
  const peak = peakOf(data);
  $('meter-fill').style.width = `${Math.min(100, peak * 100)}%`;
  $('meter-fill').style.background = peak >= CLIP_LEVEL ? 'var(--red)' : 'var(--teal)';
}

async function resampleTo16k(pcm, rate) {
  if (rate === TARGET_RATE) return pcm;
  if (typeof OfflineAudioContext === 'undefined') return resampleLinear(pcm, rate, TARGET_RATE);
  const off = new OfflineAudioContext(1, Math.ceil(pcm.length * TARGET_RATE / rate), TARGET_RATE);
  const buf = off.createBuffer(1, pcm.length, rate);
  buf.copyToChannel(pcm, 0);
  const src = off.createBufferSource();
  src.buffer = buf;
  src.connect(off.destination);
  src.start();
  return (await off.startRendering()).getChannelData(0);
}

function makeTake(pcm) {
  return { blob: new Blob([wavBytes(pcm)], { type: 'audio/wav' }), duration: pcm.length / TARGET_RATE, warning: takeWarning(pcm), stats: audioStats(pcm) };
}

// the take is queued for saving before the screen is updated
async function stopRecording() {
  rec.on = false;
  rec.node.disconnect();
  rec.stream.getTracks().forEach(t => t.stop());
  const rate = rec.ctx.sampleRate;
  await rec.ctx.close();
  $('meter-fill').style.width = '0%';
  const pcm = await resampleTo16k(concatChunks(rec.chunks), rate);
  const n = nOf(app.idx), take = makeTake(pcm);
  app.takes.set(n, take);
  queueClip(n, take);
  showTake();
}

// ---------- boot ----------
function wire() {
  const on = (id, fn, ev = 'click') => $(id).addEventListener(ev, fn);
  on('btn-sign', signAndStart); on('btn-continue', continueSelected); on('btn-retry', () => { connect(); uploader.retryNow(); });
  on('full-name', onNameTyped, 'input');
  on('btn-rec', startRecording); on('btn-stop', stopRecording); on('btn-redo', redoTake); on('btn-next', nextPrompt);
  on('btn-back', prevPrompt); on('btn-jump', jumpPrompt); on('btn-switch', switchSpeaker); on('btn-switch2', switchSpeaker);
  on('btn-finish', finishAndZip); on('btn-back-prompts', () => { show('step-complete', false); show('step-prompts', true); showTake(); });
  for (const id of ['zip-speaker', 'zip-all', 'complete-zip']) on(id, guardZip);
  window.addEventListener('beforeunload', e => { if (rec.on || uploader.pending() > 0) { e.preventDefault(); e.returnValue = ''; } });
}

function boot() {
  uploader = createUploader({ send: sendClip, onAck, onFail, onChange: onUploadChange });
  wire();
  renderStatus();
  connect();
  setInterval(connect, PING_MS);
}

if (typeof document !== 'undefined') boot();
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { peakOf, audioStats, takeWarning, concatChunks, resampleLinear, wavBytes, normName, firstUndoneIndex, clipUrl, zipUrl,
    fmtTime, progressText, statusInfo, createUploader, TARGET_RATE, PROMPT_COUNT };
}
