/* ComfyUI Studio — Chrome Extension */

// ── Storage helpers ──

function getSettings() {
  return new Promise(resolve => {
    chrome.storage.local.get(['runpodKey', 'studioUrl', 'studioKey'], resolve);
  });
}

function saveSettings(data) {
  return new Promise(resolve => chrome.storage.local.set(data, resolve));
}

// ── RunPod GraphQL ──

async function runpodQuery(query, variables = {}) {
  const settings = await getSettings();
  if (!settings.runpodKey) throw new Error('RunPod API key not configured');
  const r = await fetch('https://api.runpod.io/graphql', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${settings.runpodKey}`,
    },
    body: JSON.stringify({ query, variables }),
  });
  if (!r.ok) throw new Error('RunPod API error: ' + r.status);
  const data = await r.json();
  if (data.errors) throw new Error(data.errors[0].message);
  if (!data.data) throw new Error('No data returned — check your API key');
  return data.data;
}

async function runpodMutation(query, variables = {}) {
  return runpodQuery(query, variables);
}

// ── Studio API ──

async function studioGet(path) {
  const settings = await getSettings();
  if (!settings.studioUrl || !settings.studioKey) throw new Error('Studio not configured');
  const url = settings.studioUrl.replace(/\/$/, '') + path;
  const r = await fetch(url, { headers: { 'X-API-Key': settings.studioKey } });
  if (!r.ok) throw new Error(`Studio ${r.status}`);
  return r.json();
}

async function studioPost(path, body) {
  const settings = await getSettings();
  if (!settings.studioUrl || !settings.studioKey) throw new Error('Studio not configured');
  const url = settings.studioUrl.replace(/\/$/, '') + path;
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': settings.studioKey },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`Studio ${r.status}`);
  return r.json();
}

// ── CivitAI page detection ──

async function detectCivitaiPage() {
  return new Promise(resolve => {
    chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
      if (!tabs.length || !tabs[0].url) { resolve({ type: null }); return; }
      const url = tabs[0].url;
      var m;
      if ((m = url.match(/civitai\.com\/models\/(\d+)/))) {
        var versionId = null;
        var vm;
        if ((vm = url.match(/modelVersionId=(\d+)/))) versionId = parseInt(vm[1]);
        else if ((vm = url.match(/\/models\/\d+\/(\d+)/))) versionId = parseInt(vm[1]);
        resolve({ type: 'model', id: parseInt(m[1]), versionId: versionId });
      } else if ((m = url.match(/civitai\.com\/images\/(\d+)/))) {
        resolve({ type: 'image', id: parseInt(m[1]) });
      } else {
        resolve({ type: null });
      }
    });
  });
}

// ── UI helpers ──

function $(id) { return document.getElementById(id); }

// Side panel mode detection
if (window.location.search.includes('mode=panel')) {
  document.body.classList.add('panel-mode');
}

// ── Width monitor ──
var MIN_WIDTH = 680;
var _tooNarrow = false;
var _widthHideTimer = null;

function _checkWidth() {
  var w = window.innerWidth;
  var overlay = $('tooNarrowOverlay');
  var overlayW = $('overlayWidth');
  var widthEl = $('statusBarWidth');

  if (w < MIN_WIDTH) {
    if (!_tooNarrow) {
      overlay.style.display = 'flex';
      document.body.classList.add('too-narrow');
      _tooNarrow = true;
    }
    overlayW.textContent = w + 'px';
    widthEl.textContent = w + 'px';
    widthEl.style.opacity = '1';
    if (_widthHideTimer) clearTimeout(_widthHideTimer);
  } else {
    if (_tooNarrow) {
      overlay.style.display = 'none';
      document.body.classList.remove('too-narrow');
      _tooNarrow = false;
    }
    widthEl.textContent = w + 'px';
    widthEl.style.opacity = '1';
    if (_widthHideTimer) clearTimeout(_widthHideTimer);
    _widthHideTimer = setTimeout(function() {
      widthEl.style.opacity = '0';
    }, 5000);
  }
}

window.addEventListener('resize', _checkWidth);
new ResizeObserver(_checkWidth).observe(document.body);
_checkWidth();


var _statusTimer = null;
function showStatus(msg, type) {
  const el = $('statusBanner');
  // Flash effect: briefly go white then settle
  el.className = 'status-banner';
  el.offsetHeight;
  el.textContent = msg;
  el.title = msg;
  el.className = 'status-banner visible flash ' + (type || '');
  // Reset progress bar animation
  el.style.animation = 'none';
  el.offsetHeight;
  el.style.animation = '';
  if (_statusTimer) clearTimeout(_statusTimer);
  _statusTimer = setTimeout(() => { el.className = 'status-banner'; }, 6000);
}

function formatBytes(bytes) {
  if (bytes >= 1e12) return (bytes / 1e12).toFixed(1) + ' TB';
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
  return bytes + ' B';
}

function formatUptime(ms) {
  if (!ms) return '?';
  var s = Math.floor(ms / 1000);
  var h = Math.floor(s / 3600);
  var m = Math.floor((s % 3600) / 60);
  return h > 0 ? h + 'h ' + m + 'm' : m + 'm';
}

// ── Header tab navigation ──

function switchTab(tabName) {
  document.querySelectorAll('.header-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  var tab = document.querySelector('.header-tab[data-tab="' + tabName + '"]');
  if (tab) tab.classList.add('active');
  var panel = $('panel-' + tabName);
  if (panel) panel.classList.add('active');
}

document.querySelectorAll('.header-tab').forEach(tab => {
  tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

// ── Sub-tab navigation ──

document.querySelectorAll('.subtab').forEach(tab => {
  tab.addEventListener('click', () => {
    var parent = tab.closest('.tab-panel');
    parent.querySelectorAll('.subtab').forEach(t => t.classList.remove('active'));
    parent.querySelectorAll('.subpanel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    $('subpanel-' + tab.dataset.subtab).classList.add('active');
  });
});

// ── Pods panel ──

var _pollTimer = null;
var _podTimers = {};      // podId → { start: timestamp }
var _podJustReady = {};   // podId → { at: timestamp, elapsed: seconds }

function _scheduleAutoPoll(hasTransitional) {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  if (hasTransitional || Object.keys(_podTimers).length) {
    _pollTimer = setInterval(loadPods, 5000);
  }
}

function _startPodTimer(podId) {
  _podTimers[podId] = { start: Date.now() };
}

function _tickerHtml(podId) {
  // Pod just became ready — show "required Xs" for 10s
  if (_podJustReady[podId]) {
    var jr = _podJustReady[podId];
    if (Date.now() - jr.at > 10000) {
      delete _podJustReady[podId];
      return '';
    }
    return '<span class="pod-timer pod-timer-done">' + jr.elapsed + 's required</span>';
  }
  // Pod still starting — show elapsed
  if (_podTimers[podId]) {
    var elapsed = Math.round((Date.now() - _podTimers[podId].start) / 1000);
    return '<span class="pod-timer">' + elapsed + 's...</span>';
  }
  return '';
}

var _currentStudioUrl = '';

async function loadPods() {
  const el = $('podsList');
  var s = await getSettings();
  _currentStudioUrl = (s.studioUrl || '').replace(/\/$/, '');
  try {
    const data = await runpodQuery(`query {
      myself {
        clientBalance currentSpendPerHr
        pods {
          id name desiredStatus
          runtime { uptimeInSeconds gpus { id gpuUtilPercent memoryUtilPercent } }
          machine { podHostId gpuDisplayName }
          costPerHr
          networkVolume { id name size }
        }
      }
    }`);

    // Account summary
    const summary = $('accountSummary');
    const balance = data.myself?.clientBalance;
    const spendHr = data.myself?.currentSpendPerHr;
    if (balance != null) {
      const etaHrs = spendHr > 0 ? balance / spendHr : 0;
      const etaStr = etaHrs > 0 ? (etaHrs >= 1 ? Math.floor(etaHrs) + 'h ' + Math.round((etaHrs % 1) * 60) + 'm' : Math.round(etaHrs * 60) + 'm') : '';
      summary.innerHTML =
        '<span><span class="balance">$' + balance.toFixed(2) + '</span> credit</span>' +
        '<span class="spend">' + (spendHr > 0 ? '$' + spendHr.toFixed(2) + '/hr' : 'idle') + '</span>' +
        '<span class="eta">' + (etaStr ? '~' + etaStr + ' left' : '') + '</span>' +
        '<span style="grid-column:1/-1;display:flex;justify-content:space-between;font-size:10px;margin-top:2px;">' +
          '<a href="https://www.runpod.io/console/user/billing" target="_blank" style="color:var(--accent);text-decoration:none;">+ Add Credit</a>' +
          '<a href="https://www.runpod.io/console/pods" target="_blank" style="color:var(--muted);text-decoration:none;">Dashboard ↗</a>' +
        '</span>';
    } else {
      summary.innerHTML = '';
    }
    const pods = data.myself?.pods || [];
    if (!pods.length) {
      el.innerHTML = '<div class="empty">No pods found</div>';
      return;
    }
    el.innerHTML = '';
    var hasTransitional = false;
    pods.forEach(pod => {
      const running = pod.desiredStatus === 'RUNNING';
      const stopped = pod.desiredStatus === 'EXITED';
      const transitional = !running && !stopped;
      if (transitional) hasTransitional = true;

      // Detect pod that just became ready
      if (running && _podTimers[pod.id]) {
        var elapsed = Math.round((Date.now() - _podTimers[pod.id].start) / 1000);
        _podJustReady[pod.id] = { at: Date.now(), elapsed: elapsed };
        delete _podTimers[pod.id];
        logEvent('ok', 'pod ready — ' + (pod.name || pod.id) + ' (' + elapsed + 's)');
        if (_notifyConfig.onPodReady) sendNotification('pod_ready', { podName: pod.name || pod.id, gpu: pod.machine?.gpuDisplayName || '?', message: 'Pod is ready (' + elapsed + 's)' });
      }
      var timerHtml = _tickerHtml(pod.id);
      const gpu = pod.machine?.gpuDisplayName || '?';
      const uptimeSec = pod.runtime?.uptimeInSeconds || 0;
      const uptime = uptimeSec ? formatUptime(uptimeSec * 1000) : '-';
      const cost = pod.costPerHr ? '$' + pod.costPerHr.toFixed(2) + '/hr' : '';
      const spent = (pod.costPerHr && uptimeSec) ? '$' + (pod.costPerHr * uptimeSec / 3600).toFixed(2) + ' spent' : '';
      const vol = pod.networkVolume ? pod.networkVolume.name + ' (' + pod.networkVolume.size + 'GB)' : '';
      const linksBox = running
        ? '<div class="card-links">' +
            `<a href="https://${pod.id}-8000.proxy.runpod.net" target="_blank">Studio :8000 ↗</a>` +
            `<a href="https://${pod.id}-8188.proxy.runpod.net" target="_blank">ComfyUI :8188 ↗</a>` +
          '</div>'
        : '';

      const badgeClass = running ? 'badge-running' : (transitional ? 'badge-starting' : 'badge-exited');
      const statusLabel = transitional
        ? '<span class="spinner"></span> ' + pod.desiredStatus
        : pod.desiredStatus;

      var podUrl = 'https://' + pod.id + '-8000.proxy.runpod.net';
      var isLinked = _currentStudioUrl && _currentStudioUrl.replace(/\/$/, '') === podUrl;
      var linkBtn = '<button class="link-status ' + (isLinked ? 'linked' : 'unlinked') + '" data-pod-id="' + pod.id + '" data-pod-url="' + podUrl + '" title="' + (isLinked ? 'Linked instance' : 'Not linked') + '"><span class="icon icon-link"></span></button>';

      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-title">' + (pod.name || pod.id) +
          ' <span class="pod-id" title="Click to copy pod ID" data-copy="' + pod.id + '">' + pod.id + '</span>' +
        '</div>' +
        '<div class="card-body">' +
          '<div>' +
            '<div class="card-row">' +
              '<span class="badge ' + badgeClass + '">' + statusLabel + '</span>' +
              timerHtml +
              '<span class="gpu-badge">' + gpu + '</span>' +
              (vol ? '<span class="vol-badge">' + vol + '</span>' : '') +
            '</div>' +
            '<div class="card-row">' +
              '<span class="card-meta" style="padding:4px 6px;">' + uptime + ' · ' + cost + (spent ? ' · ' + spent : '') + '</span>' +
            '</div>' +
          '</div>' +
          linksBox +
        '</div>' +
        '<div class="card-actions">' +
          (running
            ? '<button class="btn btn-sm btn-danger" data-action="stop" data-id="' + pod.id + '">Stop</button>'
            : '<button class="btn btn-sm" data-action="resume" data-id="' + pod.id + '">Resume</button>') +
          '<button class="btn btn-sm btn-danger" data-action="terminate" data-id="' + pod.id + '">Terminate</button>' +
          linkBtn +
        '</div>' +
        _retryBarHtml(pod.id);
      el.appendChild(card);
    });

    // Auto-poll while pods are in transitional state
    _scheduleAutoPoll(hasTransitional);

    // Wire copy pod ID
    el.querySelectorAll('.pod-id').forEach(span => {
      span.addEventListener('click', () => {
        navigator.clipboard.writeText(span.dataset.copy);
        span.textContent = 'copied!';
        setTimeout(() => { span.textContent = span.dataset.copy; }, 1500);
      });
    });

    // Wire pod actions
    el.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const action = btn.dataset.action;
        const id = btn.dataset.id;
        btn.disabled = true;
        btn.textContent = '...';
        try {
          if (action === 'stop') {
            await runpodMutation(`mutation { podStop(input: {podId: "${id}"}) { id } }`);
          } else if (action === 'resume') {
            await runpodMutation(`mutation { podResume(input: {podId: "${id}", gpuCount: 1}) { id } }`);
            _startPodTimer(id);
          } else if (action === 'terminate') {
            await runpodMutation(`mutation { podTerminate(input: {podId: "${id}"}) }`);
          }
          showStatus('Pod ' + action + ' OK', 'success');
          logEvent('ok', 'pod ' + action + ' — ' + id);
          setTimeout(loadPods, 2000);
        } catch (e) {
          if (action === 'resume' && _isGpuUnavailable(e.message)) {
            showStatus(e.message + ' — auto-retrying', 'error');
            logEvent('warn', 'pod resume — no GPU, retrying — ' + id);
            _startRetry(id);
          } else {
            showStatus('Error: ' + e.message, 'error');
            logEvent('err', 'pod ' + action + ' failed — ' + e.message);
          }
          btn.disabled = false;
        }
      });
    });

    // Wire retry stop buttons
    el.querySelectorAll('[data-retry-stop]').forEach(btn => {
      btn.addEventListener('click', () => _stopRetry(btn.dataset.retryStop));
    });

    // Wire link-status buttons
    el.querySelectorAll('.link-status.unlinked').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Are you sure you want to use this pod\'s URL in Settings?\nMake sure the registered API key is correct.')) return;
        var newUrl = btn.dataset.podUrl;
        await saveSettings({ studioUrl: newUrl });
        $('studioUrl').value = newUrl;
        _currentStudioUrl = newUrl;
        showStatus('Settings > URL updated successfully', 'success');
        logEvent('ok', 'link — URL set to ' + newUrl);
        checkStudio();
        loadPods();
      });
    });
  } catch (e) {
    el.innerHTML = '<div class="empty">' + e.message + '</div>';
  }
}

// ── GPU unavailable check ──

function _isGpuUnavailable(msg) {
  if (!msg) return false;
  var m = msg.toLowerCase();
  return m.includes('not enough free gpu') || m.includes('no longer any instances available') || m.includes('no available gpu');
}

// ── Resume retry ──

var _retryState = {}; // podId → { tick, ticks, attempt, timer, cancelled, globalStart }
var TICK_MS = 100; // clock resolution
var RETRY_TICKS = 50; // 50 x 100ms = 5s between retries

function _fmtRetryTime(ms) {
  var totalSec = Math.floor(ms / 1000);
  var m = Math.min(99, Math.floor(totalSec / 60));
  var s = totalSec % 60;
  return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
}

function _startRetry(podId) {
  if (_retryState[podId]) return;
  _retryState[podId] = { tick: 0, ticks: RETRY_TICKS, attempt: 0, timer: null, cancelled: false, globalStart: Date.now() };
  _runRetryTick(podId);
  loadPods();
}

function _stopRetry(podId) {
  var state = _retryState[podId];
  if (!state) return;
  state.cancelled = true;
  if (state.timer) clearInterval(state.timer);
  delete _retryState[podId];
  loadPods();
}

function _runRetryTick(podId) {
  var state = _retryState[podId];
  if (!state || state.cancelled) return;
  state.tick = 0;

  state.timer = setInterval(async () => {
    if (state.cancelled) return;
    state.tick++;

    // Update bar
    var bar = document.querySelector('[data-retry-bar="' + podId + '"]');
    if (bar) bar.style.width = (state.tick / state.ticks * 100) + '%';

    // Update elapsed
    var elSpan = document.querySelector('[data-retry-elapsed="' + podId + '"]');
    if (elSpan) elSpan.textContent = _fmtRetryTime(Date.now() - state.globalStart);

    // When bar reaches 100%, fire the retry
    if (state.tick >= state.ticks) {
      clearInterval(state.timer);
      state.attempt++;

      try {
        await runpodMutation(`mutation { podResume(input: {podId: "${podId}", gpuCount: 1}) { id } }`);
        _startPodTimer(podId);
        delete _retryState[podId];
        showStatus('Resume succeeded after ' + state.attempt + ' attempt' + (state.attempt > 1 ? 's' : ''), 'success');
        logEvent('ok', 'resume retry — succeeded after ' + state.attempt + ' attempts');
        if (_notifyConfig.onRetrySuccess) sendNotification('resume_retry_success', { podName: podId, gpu: '', message: 'Resume succeeded after ' + state.attempt + ' attempts' });
        setTimeout(loadPods, 2000);
      } catch (e) {
        if (_isGpuUnavailable(e.message)) {
          showStatus('Retry #' + state.attempt + ' — no GPU, retrying...', 'error');
          logEvent('warn', 'resume retry #' + state.attempt + ' — no GPU');
          state.tick = 0;
          loadPods();
          _runRetryTick(podId);
        } else {
          showStatus('Retry failed: ' + e.message, 'error');
          logEvent('err', 'resume retry failed — ' + e.message);
          delete _retryState[podId];
          loadPods();
        }
      }
    }
  }, TICK_MS);
}

function _retryBarHtml(podId) {
  var state = _retryState[podId];
  if (!state) return '';
  return '<div class="retry-box">' +
    '<div class="retry-info">' +
      '<span>Retrying... #' + (state.attempt + 1) + ' · <span data-retry-elapsed="' + podId + '">' + _fmtRetryTime(Date.now() - state.globalStart) + '</span></span>' +
      '<button class="btn btn-sm retry-stop" data-retry-stop="' + podId + '">Stop</button>' +
    '</div>' +
    '<div class="retry-bar-track"><div class="retry-bar-fill" data-retry-bar="' + podId + '"></div></div>' +
  '</div>';
}

// ── Launch retry ──

var _launchRetry = null; // { tick, ticks, attempt, timer, cancelled, globalStart, mutation }

function _startLaunchRetry(mutation) {
  if (_launchRetry) _stopLaunchRetry();
  _launchRetry = { tick: 0, ticks: RETRY_TICKS, attempt: 0, timer: null, cancelled: false, globalStart: Date.now(), mutation: mutation };
  $('launchBtn').disabled = true;
  _renderLaunchRetryBar();
  _runLaunchRetryTick();
}

function _stopLaunchRetry() {
  if (!_launchRetry) return;
  _launchRetry.cancelled = true;
  if (_launchRetry.timer) clearInterval(_launchRetry.timer);
  _launchRetry = null;
  $('launchBtn').disabled = false;
  var el = $('launchRetryBox');
  if (el) el.style.display = 'none';
}

function _renderLaunchRetryBar() {
  var el = $('launchRetryBox');
  if (!el) {
    var container = $('launchBtn').parentElement;
    var div = document.createElement('div');
    div.id = 'launchRetryBox';
    div.className = 'retry-box';
    div.style.marginTop = '8px';
    div.innerHTML = '<div class="retry-info">' +
      '<span>Retrying launch... #<span id="launchRetryAttempt">1</span> · <span id="launchRetryElapsed">00:00</span></span>' +
      '<select id="launchRetryInterval" class="retry-interval-select">' +
        '<option value="50">5s</option><option value="100">10s</option><option value="150">15s</option>' +
        '<option value="200">20s</option><option value="250">25s</option><option value="300">30s</option>' +
      '</select>' +
      '<button class="btn btn-sm retry-stop" id="launchRetryStop">Stop</button>' +
    '</div><div class="retry-bar-track"><div class="retry-bar-fill" id="launchRetryBar"></div></div>';
    container.appendChild(div);
    $('launchRetryStop').addEventListener('click', _stopLaunchRetry);
    $('launchRetryInterval').addEventListener('change', function() {
      if (_launchRetry) _launchRetry.ticks = parseInt(this.value);
    });
  } else {
    el.style.display = '';
  }
}

function _runLaunchRetryTick() {
  if (!_launchRetry || _launchRetry.cancelled) return;
  _launchRetry.tick = 0;

  _launchRetry.timer = setInterval(async () => {
    if (!_launchRetry || _launchRetry.cancelled) return;
    _launchRetry.tick++;

    var bar = $('launchRetryBar');
    if (bar) bar.style.width = (_launchRetry.tick / _launchRetry.ticks * 100) + '%';

    var el = $('launchRetryElapsed');
    if (el) el.textContent = _fmtRetryTime(Date.now() - _launchRetry.globalStart);
    var att = $('launchRetryAttempt');
    if (att) att.textContent = _launchRetry.attempt + 1;

    if (_launchRetry.tick >= _launchRetry.ticks) {
      clearInterval(_launchRetry.timer);
      _launchRetry.attempt++;

      try {
        var data = await runpodMutation(_launchRetry.mutation);
        var pod = data.podFindAndDeployOnDemand;
        _startPodTimer(pod.id);
        var attempts = _launchRetry.attempt;
        _stopLaunchRetry();
        showStatus('Pod launched after ' + attempts + ' attempt' + (attempts > 1 ? 's' : '') + ': ' + (pod.name || pod.id), 'success');
        logEvent('ok', 'launch retry — succeeded after ' + attempts + ' attempts: ' + (pod.name || pod.id));
        if (_notifyConfig.onRetrySuccess) sendNotification('launch_retry_success', { podName: pod.name || pod.id, gpu: '', message: 'Launch succeeded after ' + attempts + ' attempts' });
        setTimeout(loadPods, 3000);
      } catch (e) {
        if (_isGpuUnavailable(e.message)) {
          showStatus('Launch retry #' + _launchRetry.attempt + ' — no GPU, retrying...', 'error');
          logEvent('warn', 'launch retry #' + _launchRetry.attempt + ' — no GPU');
          _launchRetry.tick = 0;
          _runLaunchRetryTick();
        } else {
          showStatus('Launch retry failed: ' + e.message, 'error');
          logEvent('err', 'launch retry failed — ' + e.message);
          _stopLaunchRetry();
        }
      }
    }
  }, TICK_MS);
}

// ── Storage panel ──

async function loadStorage() {
  const el = $('storageList');
  try {
    const data = await runpodQuery(`query {
      myself {
        networkVolumes { id name size dataCenterId }
      }
    }`);
    const vols = data.myself?.networkVolumes || [];
    if (!vols.length) {
      el.innerHTML = '<div class="empty">No network volumes</div>';
      return;
    }
    // Storage cost summary
    const totalGB = vols.reduce((sum, v) => sum + (v.size || 0), 0);
    const rate = totalGB > 1000 ? 0.05 : 0.07; // RunPod pricing tiers
    const monthlyCost = totalGB * rate;
    const dailyCost = monthlyCost / 30;
    const summary = $('storageSummary');
    summary.innerHTML =
      '<span><span class="balance">' + totalGB + ' GB</span> storage</span>' +
      '<span class="spend">$' + monthlyCost.toFixed(0) + '/mo</span>' +
      '<span class="eta">~$' + dailyCost.toFixed(2) + '/day</span>';

    el.innerHTML = '';
    vols.forEach(vol => {
      const volRate = (vol.size || 0) > 1000 ? 0.05 : 0.07;
      const volMo = (vol.size || 0) * volRate;
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-title">' + (vol.name || vol.id) + '</div>' +
        '<div class="card-meta">' + vol.size + ' GB · ' + (vol.dataCenterId || 'unknown region') + ' · $' + volMo.toFixed(0) + '/mo</div>';
      el.appendChild(card);
    });

    // Also populate volume selector in Launch tab
    const volSelect = $('volumeSelect');
    volSelect.innerHTML = '<option value="" data-region="">-- No volume --</option>';
    vols.forEach(vol => {
      const o = document.createElement('option');
      o.value = vol.id;
      o.dataset.region = vol.dataCenterId || '';
      const name = (vol.name || vol.id) + ' (' + vol.size + 'GB)';
      const region = vol.dataCenterId || '?';
      const pad = Math.max(1, 40 - name.length - region.length);
      o.textContent = name + '\u00A0'.repeat(pad) + region;
      volSelect.appendChild(o);
    });

    // Volume → force region
    volSelect.addEventListener('change', () => {
      const opt = volSelect.options[volSelect.selectedIndex];
      const volRegion = opt ? opt.dataset.region : '';
      if (volRegion) {
        $('regionSelect').value = volRegion;
      }
    });

    // Region → deselect volume if mismatch
    $('regionSelect').addEventListener('change', () => {
      const regionVal = $('regionSelect').value;
      const volOpt = volSelect.options[volSelect.selectedIndex];
      const volRegion = volOpt ? volOpt.dataset.region : '';
      if (regionVal && volRegion && volRegion !== regionVal) {
        volSelect.value = '';
      }
    });
  } catch (e) {
    el.innerHTML = '<div class="empty">' + e.message + '</div>';
  }
}

// ── Launch panel ──

var _gpuCache = [];
var _gpuSortAsc = true;
var _gpuFavIds = ['NVIDIA B200', 'NVIDIA RTX 6000 Ada Generation', 'NVIDIA RTX A6000',
                  'NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition',
                  'NVIDIA RTX PRO 6000 Blackwell Server Edition',
                  'NVIDIA RTX PRO 6000 Blackwell Workstation Edition'];

async function loadGpuTypes() {
  const sel = $('gpuSelect');
  try {
    const data = await runpodQuery(`query {
      gpuTypes { id displayName memoryInGb securePrice communityPrice }
    }`);
    _gpuCache = (data.gpuTypes || []).filter(g => g.securePrice > 0 || g.communityPrice > 0);
    renderGpuList();
  } catch (e) {
    sel.innerHTML = '<option value="">Error loading GPUs</option>';
  }
}

function renderGpuList() {
  const sel = $('gpuSelect');
  const sortBy = $('gpuSort').value;
  const dir = _gpuSortAsc ? 1 : -1;
  const selected = sel.value;

  const sorted = [..._gpuCache].sort((a, b) => {
    if (sortBy === 'price') return dir * ((a.securePrice || a.communityPrice || 99) - (b.securePrice || b.communityPrice || 99));
    if (sortBy === 'memory') return dir * ((a.memoryInGb || 0) - (b.memoryInGb || 0));
    return dir * (a.displayName || '').localeCompare(b.displayName || '');
  });

  const favs = sorted.filter(g => _gpuFavIds.includes(g.id));
  const rest = sorted.filter(g => !_gpuFavIds.includes(g.id));

  function makeOption(g) {
    const price = g.securePrice ? '$' + g.securePrice.toFixed(2) + '/hr' : (g.communityPrice ? '$' + g.communityPrice.toFixed(2) + '/hr com.' : '');
    const o = document.createElement('option');
    o.value = g.id;
    o.textContent = g.displayName + ' (' + g.memoryInGb + 'GB) — ' + price;
    if (g.id === selected) o.selected = true;
    return o;
  }

  sel.innerHTML = '<option value="">-- Select GPU --</option>';
  if (favs.length) {
    const fg = document.createElement('optgroup');
    fg.label = '\u2605 Favorites';
    favs.forEach(g => fg.appendChild(makeOption(g)));
    sel.appendChild(fg);
  }
  const og = document.createElement('optgroup');
  og.label = 'All GPUs';
  rest.forEach(g => og.appendChild(makeOption(g)));
  sel.appendChild(og);
}

$('gpuSort').addEventListener('change', () => {
  // Set sensible default direction per sort type
  const s = $('gpuSort').value;
  _gpuSortAsc = (s === 'price' || s === 'name'); // price/name asc, memory desc
  $('gpuSortDir').textContent = _gpuSortAsc ? '\u25B2' : '\u25BC';
  renderGpuList();
});
$('gpuSortDir').addEventListener('click', () => {
  _gpuSortAsc = !_gpuSortAsc;
  $('gpuSortDir').textContent = _gpuSortAsc ? '\u25B2' : '\u25BC';
  renderGpuList();
});

async function loadRegions() {
  const sel = $('regionSelect');
  try {
    const data = await runpodQuery(`query { dataCenters { id name location } }`);
    const dcs = data.dataCenters || [];
    sel.innerHTML = '<option value="">Any region</option>';
    // Group by location
    const groups = {};
    dcs.forEach(dc => {
      const loc = dc.location || 'Other';
      if (!groups[loc]) groups[loc] = [];
      groups[loc].push(dc);
    });
    Object.keys(groups).sort().forEach(loc => {
      const og = document.createElement('optgroup');
      og.label = loc;
      groups[loc].forEach(dc => {
        const o = document.createElement('option');
        o.value = dc.id;
        o.textContent = dc.id;
        og.appendChild(o);
      });
      sel.appendChild(og);
    });
  } catch (e) {
    sel.innerHTML = '<option value="">Error loading regions</option>';
  }
}

var STUDIO_TEMPLATE_NAME = 'comfyui-studio';

async function loadTemplates() {
  const sel = $('templateSelect');
  try {
    const data = await runpodQuery(`query { myself { podTemplates { id name imageName isPublic } } }`);
    const templates = data.myself?.podTemplates || [];
    const mine = templates.filter(t => !t.isPublic);
    const pub = templates.filter(t => t.isPublic);

    function makeOption(t) {
      const o = document.createElement('option');
      o.value = t.id;
      o.textContent = t.name + (t.imageName ? ' — ' + t.imageName.split('/').pop().split(':')[0] : '');
      return o;
    }

    sel.innerHTML = '<option value="">-- Select Template --</option>';

    // Find and put comfyui-studio first
    const studio = pub.find(t => t.name.toLowerCase() === STUDIO_TEMPLATE_NAME);
    if (studio) {
      const o = makeOption(studio);
      o.selected = true;
      sel.appendChild(o);
    }

    if (mine.length) {
      const og = document.createElement('optgroup');
      og.label = 'My Templates';
      mine.forEach(t => og.appendChild(makeOption(t)));
      sel.appendChild(og);
    }

    const restPub = pub.filter(t => t !== studio);
    if (restPub.length) {
      const og = document.createElement('optgroup');
      og.label = 'Public Templates';
      restPub.forEach(t => og.appendChild(makeOption(t)));
      sel.appendChild(og);
    }
  } catch (e) {
    sel.innerHTML = '<option value="">Error loading templates</option>';
  }
}

$('checkAvailBtn').addEventListener('click', async () => {
  const gpuId = $('gpuSelect').value;
  const result = $('availResult');
  if (!gpuId) { result.textContent = 'Select a GPU first'; result.style.color = 'var(--muted)'; return; }

  const btn = $('checkAvailBtn');
  btn.disabled = true;
  btn.textContent = 'Checking...';
  result.textContent = '';

  try {
    const cloudType = $('cloudType').value;
    const data = await runpodQuery(`query { gpuTypes(input: {id: "${gpuId}"}) { id displayName communityCloud secureCloud securePrice communityPrice } }`);
    const gpu = (data.gpuTypes || [])[0];
    if (!gpu) { result.textContent = 'Not found'; result.style.color = 'var(--error)'; return; }

    const available = cloudType === 'SECURE' ? gpu.secureCloud : gpu.communityCloud;
    const price = cloudType === 'SECURE' ? gpu.securePrice : gpu.communityPrice;

    if (available) {
      result.innerHTML = '<span style="color:var(--success);">\u2713 Available</span>' + (price ? ' — $' + price.toFixed(2) + '/hr' : '');
      logEvent('ok', 'gpu check — ' + gpu.displayName + ' available' + (price ? ' $' + price.toFixed(2) + '/hr' : ''));
    } else {
      result.innerHTML = '<span style="color:var(--error);">\u2717 Not available</span>';
      logEvent('warn', 'gpu check — ' + gpu.displayName + ' not available');
    }
  } catch (e) {
    result.textContent = 'Error: ' + e.message;
    result.style.color = 'var(--error)';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Check Availability';
  }
});

$('launchBtn').addEventListener('click', async () => {
  const gpuId = $('gpuSelect').value;
  const cloudType = $('cloudType').value;
  const regionId = $('regionSelect').value;
  const volumeId = $('volumeSelect').value;
  const templateId = $('templateSelect').value;
  const settings = await getSettings();

  if (!gpuId) { showStatus('Select a GPU', 'error'); return; }
  if (!templateId) { showStatus('Select a template', 'error'); return; }

  const btn = $('launchBtn');
  btn.disabled = true;
  btn.textContent = 'Launching...';

  const launchMutation = `mutation {
    podFindAndDeployOnDemand(input: {
      cloudType: ${cloudType}
      gpuTypeId: "${gpuId}"
      gpuCount: 1
      templateId: "${templateId}"
      ${regionId ? `dataCenterId: "${regionId}"` : ''}
      ${volumeId ? `networkVolumeId: "${volumeId}"` : ''}
    }) { id name desiredStatus machine { podHostId } }
  }`;

  try {
    const data = await runpodMutation(launchMutation);
    const pod = data.podFindAndDeployOnDemand;
    _startPodTimer(pod.id);
    showStatus('Pod launched: ' + (pod.name || pod.id), 'success');
    logEvent('ok', 'launch — pod ' + (pod.name || pod.id) + ' on ' + $('gpuSelect').value);
    if (_notifyConfig.onLaunchSuccess) sendNotification('pod_launched', { podName: pod.name || pod.id, gpu: $('gpuSelect').value, message: 'Pod launched successfully' });
    setTimeout(loadPods, 3000);
  } catch (e) {
    if (_isGpuUnavailable(e.message)) {
      showStatus(e.message + ' — auto-retrying', 'error');
      logEvent('warn', 'launch — no GPU, auto-retrying');
      _startLaunchRetry(launchMutation);
    } else {
      showStatus('Launch failed: ' + e.message, 'error');
      logEvent('err', 'launch failed — ' + e.message);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = 'Launch Pod';
  }
});

// ── Find running pod ──

$('findPodBtn').addEventListener('click', async () => {
  const btn = $('findPodBtn');
  const picker = $('podPicker');
  btn.disabled = true;
  btn.innerHTML = '&#8987;';

  try {
    const data = await runpodQuery(`query {
      myself {
        pods {
          id name desiredStatus
          machine { podHostId }
        }
      }
    }`);
    const running = (data.myself?.pods || []).filter(p => p.desiredStatus === 'RUNNING');

    if (!running.length) {
      showStatus('No running pods found', 'error');
      logEvent('warn', 'find pod — no running pods');
      picker.style.display = 'none';
      return;
    }

    picker.innerHTML = '<option value="">-- Select pod --</option>';
    running.forEach(pod => {
      const o = document.createElement('option');
      const url = 'https://' + pod.id + '-8000.proxy.runpod.net';
      o.value = url;
      o.textContent = (pod.name || pod.id);
      picker.appendChild(o);
    });
    picker.style.display = '';

    picker.onchange = function() {
      if (picker.value) {
        $('studioUrl').value = picker.value;
        picker.style.display = 'none';
      }
    };
  } catch (e) {
    showStatus('Error: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="icon icon-search" style="width:12px;height:12px;"></span>';
  }
});

// ── Settings panel ──

$('saveSettingsBtn').addEventListener('click', async () => {
  await saveSettings({
    runpodKey: $('runpodKey').value.trim(),
    studioUrl: $('studioUrl').value.trim(),
    studioKey: $('studioKey').value.trim(),
  });
  showStatus('Settings saved', 'success');
  logEvent('ok', 'settings saved');
  init().then(initStudio);
});

// Populate settings on load
getSettings().then(s => {
  $('runpodKey').value = s.runpodKey || '';
  $('studioUrl').value = s.studioUrl || '';
  $('studioKey').value = s.studioKey || '';
});

// ── Notifications ──

var _notifyConfig = {};

async function loadNotifyConfig() {
  return new Promise(resolve => {
    chrome.storage.local.get(['notifyConfig'], r => {
      _notifyConfig = r.notifyConfig || {};
      if ($('notifyUrl')) $('notifyUrl').value = _notifyConfig.url || '';
      if ($('notifyMethod')) $('notifyMethod').value = _notifyConfig.method || 'POST';
      if ($('notifyHeaders')) $('notifyHeaders').value = _notifyConfig.headers || 'Content-Type: application/json';
      if ($('notifyBody')) $('notifyBody').value = _notifyConfig.body || '{"key":"YOUR_KEY","msg":"{event}: {message}"}';
      if ($('notifyOnPodReady')) $('notifyOnPodReady').checked = _notifyConfig.onPodReady !== false;
      if ($('notifyOnLaunchSuccess')) $('notifyOnLaunchSuccess').checked = _notifyConfig.onLaunchSuccess !== false;
      if ($('notifyOnRetrySuccess')) $('notifyOnRetrySuccess').checked = _notifyConfig.onRetrySuccess !== false;
      resolve();
    });
  });
}

function saveNotifyConfig() {
  _notifyConfig = {
    url: $('notifyUrl').value.trim(),
    method: $('notifyMethod').value,
    headers: $('notifyHeaders').value.trim(),
    body: $('notifyBody').value.trim(),
    onPodReady: $('notifyOnPodReady').checked,
    onLaunchSuccess: $('notifyOnLaunchSuccess').checked,
    onRetrySuccess: $('notifyOnRetrySuccess').checked,
  };
  chrome.storage.local.set({ notifyConfig: _notifyConfig }, function() {
    console.log('Saved notifyConfig:', _notifyConfig);
  });
  showStatus('Notification settings saved', 'success');
  logEvent('ok', 'notification settings saved');
}

async function sendNotification(event, vars) {
  console.log('sendNotification called, config:', _notifyConfig);
  if (!_notifyConfig.url) return null;
  var tpl = _notifyConfig.body || '';
  var allVars = Object.assign({ event: event, timestamp: new Date().toISOString() }, vars || {});
  for (var k in allVars) {
    tpl = tpl.replace(new RegExp('\\{' + k + '\\}', 'g'), allVars[k] || '');
  }

  var headers = {};
  (_notifyConfig.headers || '').split('\n').forEach(function(line) {
    var idx = line.indexOf(':');
    if (idx > 0) headers[line.substring(0, idx).trim()] = line.substring(idx + 1).trim();
  });

  try {
    var opts = { method: _notifyConfig.method || 'POST', headers: headers };
    if (opts.method === 'POST') {
      opts.body = tpl;
    }
    var url = _notifyConfig.url;
    if (opts.method === 'GET' && tpl) {
      url += (url.includes('?') ? '&' : '?') + 'data=' + encodeURIComponent(tpl);
    }
    var r = await fetch(url, opts);
    return await r.json();
  } catch (e) {
    console.error('Notification failed:', e);
    return null;
  }
}

$('saveNotifyBtn').addEventListener('click', saveNotifyConfig);
$('testNotifyBtn').addEventListener('click', async function() {
  $('notifyTestResult').textContent = 'Sending...';
  try {
    var result = await sendNotification('test', { podName: 'test-pod', gpu: 'NVIDIA Test', message: 'This is a test notification' });
    $('notifyTestResult').textContent = result ? JSON.stringify(result) : 'No URL configured';
    $('notifyTestResult').style.color = (result && result.status === 'sent') ? 'var(--success)' : 'var(--error)';
  } catch (e) {
    $('notifyTestResult').textContent = 'Error: ' + e.message;
    $('notifyTestResult').style.color = 'var(--error)';
  }
});
loadNotifyConfig();

// ── Studio status dot ──

var _studioConnected = false;
var _studioCheckDone = null;

// ── Event Log ──

$('eventLogHeader').addEventListener('click', function() {
  $('eventLogContainer').classList.toggle('collapsed');
  chrome.storage.local.set({ eventLogCollapsed: $('eventLogContainer').classList.contains('collapsed') });
});
chrome.storage.local.get(['eventLogCollapsed'], function(r) {
  if (r.eventLogCollapsed) $('eventLogContainer').classList.add('collapsed');
});

var _evFilter = 'all';

document.querySelectorAll('.ev-filter').forEach(function(btn) {
  btn.dataset.label = btn.textContent;
  btn.addEventListener('click', function() {
    document.querySelectorAll('.ev-filter').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    _evFilter = btn.dataset.filter;
    // Show/hide existing entries
    $('eventLog').querySelectorAll('.ev').forEach(function(el) {
      el.style.display = _matchFilter(el.dataset.cat, el.dataset.level) ? '' : 'none';
    });
  });
});

function _matchFilter(cat, level) {
  if (_evFilter === 'all') return true;
  if (_evFilter === 'errors') return level === 'err' || level === 'warn';
  return cat === _evFilter;
}

var _evCounts = { all: 0, health: 0, pods: 0, civitai: 0, settings: 0, errors: 0 };

function _updateFilterCounts() {
  document.querySelectorAll('.ev-filter').forEach(function(btn) {
    var f = btn.dataset.filter;
    btn.textContent = btn.dataset.label + (_evCounts[f] ? ' (' + _evCounts[f] + ')' : '');
  });
}

function logEvent(level, msg, cat) {
  cat = cat || _guessCategory(msg);
  _evCounts.all++;
  _evCounts[cat] = (_evCounts[cat] || 0) + 1;
  if (level === 'err' || level === 'warn') _evCounts.errors++;
  _updateFilterCounts();
  var log = $('eventLog');
  if (!log) return;
  var now = new Date();
  var ts = ('0' + now.getHours()).slice(-2) + ':' + ('0' + now.getMinutes()).slice(-2) + ':' + ('0' + now.getSeconds()).slice(-2);
  var cls = level === 'ok' ? 'ev-ok' : level === 'err' ? 'ev-err' : level === 'warn' ? 'ev-warn' : 'ev-dim';
  var line = document.createElement('div');
  line.className = 'ev';
  line.dataset.cat = cat;
  line.dataset.level = level;
  if (!_matchFilter(cat, level)) line.style.display = 'none';
  line.innerHTML = '<span class="ev-time">' + ts + '</span> <span class="' + cls + '">' + msg + '</span>';
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
  while (log.children.length > 100) log.removeChild(log.firstChild);
}

function _guessCategory(msg) {
  if (msg.startsWith('health')) return 'health';
  if (msg.startsWith('pod ') || msg.startsWith('launch') || msg.startsWith('resume')) return 'pods';
  if (msg.startsWith('civitai') || msg.startsWith('add') || msg.startsWith('download') || msg.startsWith('preset')) return 'civitai';
  if (msg.startsWith('settings') || msg.startsWith('link') || msg.startsWith('poll') || msg.startsWith('notification')) return 'settings';
  return 'health';
}

async function checkStudio() {
  const container = $('studioStatus');
  const link = $('studioLink');
  const settings = await getSettings();
  const studioUrl = settings.studioUrl ? settings.studioUrl.replace(/\/$/, '') : '';

  var status = 'offline'; // offline | no_url | no_key | unreachable | auth_fail | online
  var tooltip = '';
  var label = 'Offline';
  var studioData = null;

  if (!studioUrl) {
    status = 'no_url';
    tooltip = 'Studio URL not configured — go to Settings';
    logEvent('warn', 'health — no URL configured');
  } else if (!settings.studioKey) {
    status = 'no_key';
    tooltip = 'API Key not configured — go to Settings';
    logEvent('warn', 'health — no API key configured');
  } else {
    var keyHint = settings.studioKey.length > 4 ? '***' + settings.studioKey.slice(-4) : '***';
    logEvent('info', 'health → ' + studioUrl + '/api/health  key=' + keyHint);
    try {
      var r = await fetch(studioUrl + '/api/health', { headers: { 'X-API-Key': settings.studioKey } });
      if (r.ok) {
        var data = await r.json();
        studioData = data;
        if (data.authenticated) {
          status = 'online';
          label = data.app_version ? 'v' + data.app_version : 'Online';
          tooltip = studioUrl;
          if (data.pod_id) tooltip += ' (pod: ' + data.pod_id + ')';
          logEvent('ok', 'health ← 200 OK  authenticated  v' + (data.app_version || '?') + (data.pod_id ? '  pod=' + data.pod_id : ''));
        } else {
          status = 'auth_fail';
          tooltip = 'Server reachable but API key is wrong';
          logEvent('err', 'health ← 200 OK  authenticated=false — wrong key');
        }
      } else {
        status = 'unreachable';
        tooltip = 'Server responded with HTTP ' + r.status;
        logEvent('err', 'health ← HTTP ' + r.status);
      }
    } catch (e) {
      status = 'unreachable';
      tooltip = 'Cannot reach ' + studioUrl;
      logEvent('err', 'health ← FAILED: ' + e.message);
    }
  }

  _studioConnected = status === 'online';
  container.title = tooltip;

  if (_studioConnected) {
    container.className = 'studio-status online';
    link.href = studioUrl;
    link.textContent = label;
    chrome.action.setBadgeText({ text: '' });
    chrome.action.setIcon({ path: { '16': 'icons/icon16_connected.png', '48': 'icons/icon48_connected.png', '128': 'icons/icon128_connected.png' } });
  } else {
    container.className = 'studio-status offline';
    link.textContent = status === 'auth_fail' ? 'Auth fail' : 'Offline';
    link.href = '#';
    chrome.action.setIcon({ path: { '16': 'icons/icon16_disconnected.png', '48': 'icons/icon48_disconnected.png', '128': 'icons/icon128_disconnected.png' } });
  }

  // Flash the badge on each check
  container.classList.remove('flash-check');
  container.offsetHeight;
  container.classList.add('flash-check');
  setTimeout(() => container.classList.remove('flash-check'), 500);
}

// Setup version text (once)
(function() {
  const extVer = chrome.runtime.getManifest().version;
  var verSpan = $('statusBarText');
  verSpan.textContent = 'v' + extVer;
  verSpan.style.cursor = 'pointer';
  verSpan.title = 'View changelog';
  verSpan.addEventListener('click', showChangelog);
})();

// Refresh button
$('studioRefresh').addEventListener('click', function(e) {
  e.stopPropagation();
  this.classList.add('spinning');
  var self = this;
  checkStudio().then(() => setTimeout(() => self.classList.remove('spinning'), 600));
});

// Poll studio status every 10s (if enabled)
var _studioPollInterval = null;
var _studioPollEnabled = true;

function startStudioPoll() {
  if (_studioPollInterval) clearInterval(_studioPollInterval);
  _studioPollInterval = setInterval(checkStudio, 10000);
}

function stopStudioPoll() {
  if (_studioPollInterval) { clearInterval(_studioPollInterval); _studioPollInterval = null; }
  _studioConnected = false;
  var container = $('studioStatus');
  container.className = 'studio-status offline';
  container.title = 'Polling stopped';
  $('studioLink').textContent = 'Offline';
  $('studioLink').href = '#';
  chrome.action.setIcon({ path: { '16': 'icons/icon16_disconnected.png', '48': 'icons/icon48_disconnected.png', '128': 'icons/icon128_disconnected.png' } });
}

// Load saved state
chrome.storage.local.get(['studioPollEnabled'], function(r) {
  _studioPollEnabled = r.studioPollEnabled !== false;
  $('studioPollToggle').checked = _studioPollEnabled;
  if (_studioPollEnabled) {
    checkStudio();
    startStudioPoll();
  } else {
    stopStudioPoll();
    logEvent('info', 'poll — disabled');
  }
});

$('studioPollToggle').addEventListener('change', function() {
  _studioPollEnabled = this.checked;
  chrome.storage.local.set({ studioPollEnabled: _studioPollEnabled });
  logEvent('info', 'poll — ' + (_studioPollEnabled ? 'enabled' : 'disabled'));
  if (_studioPollEnabled) {
    checkStudio();
    startStudioPoll();
  } else {
    stopStudioPoll();
  }
});

// ── Toggle password visibility ──

document.querySelectorAll('.toggle-vis').forEach(btn => {
  btn.addEventListener('click', () => {
    const input = $(btn.dataset.target);
    input.type = input.type === 'password' ? 'text' : 'password';
  });
});

// ── Changelog ──

function _parseMd(md) {
  var html = '';
  var inList = false;
  md.split('\n').forEach(function(line) {
    var trimmed = line.trim();
    if (!trimmed) {
      if (inList) { html += '</ul>'; inList = false; }
      return;
    }
    if (trimmed.startsWith('# ') && !trimmed.startsWith('## ')) {
      if (inList) { html += '</ul>'; inList = false; }
      html += '<h1>' + _escMd(trimmed.substring(2)) + '</h1>';
    } else if (trimmed.startsWith('## ')) {
      if (inList) { html += '</ul>'; inList = false; }
      html += '<h2>' + _escMd(trimmed.substring(3)) + '</h2>';
    } else if (trimmed.startsWith('- ')) {
      if (!inList) { html += '<ul>'; inList = true; }
      var content = trimmed.substring(2);
      content = content.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
      content = content.replace(/`(.+?)`/g, '<code style="background:rgba(255,255,255,0.08);padding:1px 4px;border-radius:2px;font-size:11px;">$1</code>');
      html += '<li>' + content + '</li>';
    }
  });
  if (inList) html += '</ul>';
  return html;
}

function _escMd(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function showChangelog() {
  var overlay = $('changelogOverlay');
  var body = $('changelogBody');
  overlay.style.display = 'flex';
  body.innerHTML = '<div style="color:var(--muted);">Loading...</div>';
  try {
    var resp = await fetch('CHANGELOG.md');
    var md = await resp.text();
    body.innerHTML = _parseMd(md);
  } catch (e) {
    body.innerHTML = '<div style="color:var(--error);">Failed to load changelog</div>';
  }
}

$('changelogClose').addEventListener('click', function() {
  $('changelogOverlay').style.display = 'none';
});
$('changelogOverlay').addEventListener('click', function(e) {
  if (e.target === this) this.style.display = 'none';
});

// About dialog
$('aboutBtn').addEventListener('click', function() {
  $('aboutVersion').textContent = 'v' + chrome.runtime.getManifest().version;
  $('aboutOverlay').style.display = 'flex';
});
$('aboutClose').addEventListener('click', function() {
  $('aboutOverlay').style.display = 'none';
});
$('aboutOverlay').addEventListener('click', function(e) {
  if (e.target === this) this.style.display = 'none';
});

// ── Init ──

async function init() {
  const s = await getSettings();
  await checkStudio();
  var noKey = $('runpodNoKey');
  var content = $('runpodContent');
  if (!noKey || !content) return;

  if (s.runpodKey) {
    // Validate the key with a simple query
    try {
      await runpodQuery('query { myself { id } }');
    } catch (e) {
      noKey.style.display = '';
      content.style.display = 'none';
      return;
    }
    noKey.style.display = 'none';
    content.style.display = '';
    loadPods();
    loadStorage();
    loadGpuTypes();
    loadRegions();
    loadTemplates();
  } else {
    noKey.style.display = '';
    content.style.display = 'none';
  }
}

// ── Studio CivitAI ──

var _civitaiMapCache = null;

async function initStudio() {
  var noConnect = $('studioNoConnect');
  var content = $('studioContent');
  if (!noConnect || !content) return;

  var page = await detectCivitaiPage();
  switchTab(page.type ? 'studio' : 'runpod');

  const s = await getSettings();
  if (!s.studioUrl || !s.studioKey) {
    noConnect.style.display = '';
    content.style.display = 'none';
    return;
  }

  if (!_studioConnected) {
    await checkStudio();
    if (!_studioConnected) {
      noConnect.style.display = '';
      content.style.display = 'none';
      return;
    }
  }

  noConnect.style.display = 'none';
  content.style.display = '';

  var detect = $('civitaiDetect');
  $('civitaiModelPanel').style.display = 'none';
  $('civitaiImagePanel').style.display = 'none';
  $('civitaiNone').style.display = 'none';

  startResourcePoll();

  if (page.type === 'model') {
    logEvent('info', 'civitai — model #' + page.id + (page.versionId ? ' v' + page.versionId : ''));
    detect.innerHTML = '<span class="civitai-badge">Model #' + page.id + '</span>';
    $('civitaiModelPanel').style.display = '';
    loadModelVersions(page.id, page.versionId);
  } else if (page.type === 'image') {
    logEvent('info', 'civitai — image #' + page.id);
    detect.innerHTML = '<span class="civitai-badge">Image #' + page.id + '</span>';
    $('civitaiImagePanel').style.display = '';
    loadImageGenData(page.id);
  } else {
    detect.innerHTML = '';
    $('civitaiNone').style.display = '';
  }
}

async function getCivitaiMap(force) {
  if (!force && _civitaiMapCache) return _civitaiMapCache;
  _civitaiMapCache = await studioGet('/api/admin/models/civitai-map');
  // Init status tracking on first load
  if (!Object.keys(_lastResStatus).length) {
    var bv = _civitaiMapCache.by_version || {};
    for (var vid in bv) _lastResStatus[vid] = bv[vid].status;
  }
  return _civitaiMapCache;
}

// ── Resource status polling ──

var _resPollInterval = null;
var _lastResStatus = {}; // vid → status

function startResourcePoll() {
  if (_resPollInterval) return;
  _resPollInterval = setInterval(_pollResources, 5000);
}

function stopResourcePoll() {
  if (_resPollInterval) { clearInterval(_resPollInterval); _resPollInterval = null; }
}

async function _pollResources() {
  if (!_studioConnected) return;
  // Spin the refresh icon
  var refresh = $('studioRefresh');
  if (refresh) { refresh.classList.add('spinning'); setTimeout(function() { refresh.classList.remove('spinning'); }, 600); }
  try {
    var map = await getCivitaiMap(true);
    var byVer = map.by_version || {};
    for (var vid in byVer) {
      var cur = byVer[vid];
      var prev = _lastResStatus[vid];
      if (prev && prev !== cur.status) {
        var name = cur.name || cur.file;
        if (cur.status === 'present' && prev === 'downloading') {
          logEvent('ok', 'download complete — ' + name, 'civitai');
        } else if (cur.status === 'downloading' && prev === 'missing') {
          logEvent('info', 'download started — ' + name, 'civitai');
        } else if (cur.status === 'downloading') {
          var pct = cur.dl_total ? Math.round(cur.dl_bytes / cur.dl_total * 100) : 0;
          logEvent('info', 'downloading — ' + name + ' ' + pct + '%', 'civitai');
        } else {
          logEvent('info', name + ' — ' + prev + ' → ' + cur.status, 'civitai');
        }
      }
      _lastResStatus[vid] = cur.status;
    }
    // Update version badges in current view
    document.querySelectorAll('.ver-badge[data-vid]').forEach(function(badge) {
      var info = byVer[badge.dataset.vid];
      if (!info) return;
      if (info.status === 'downloading') {
        var pct = info.dl_total ? Math.round(info.dl_bytes / info.dl_total * 100) : 0;
        badge.textContent = 'Downloading ' + pct + '%';
        badge.className = 'ver-badge ver-other';
      } else if (info.status === 'queued') {
        badge.textContent = 'Queued';
        badge.className = 'ver-badge ver-other';
      } else if (info.status === 'present') {
        badge.textContent = 'Downloaded';
        badge.className = 'ver-badge ver-downloaded';
        // Hide download button if present
        var item = badge.closest('.version-item, .resource-item');
        if (item) {
          var dlBtn = item.querySelector('.btn-download-ver');
          if (dlBtn) dlBtn.style.display = 'none';
        }
      } else if (info.status === 'missing') {
        badge.textContent = 'In Catalog';
        badge.className = 'ver-badge ver-in-catalog';
      }
    });
  } catch (e) {
    logEvent('err', 'resource poll failed — ' + e.message, 'civitai');
  }
}

async function loadModelVersions(modelId, currentVersionId) {
  var el = $('modelVersionsList');
  el.innerHTML = '<div class="loading-spinner"><span class="spinner-lg"></span><div style="margin-top:8px;font-size:11px;color:var(--muted);">Loading versions...</div></div>';
  logEvent('info', 'loading model versions — #' + modelId, 'civitai');

  try {
    const [modelData, civitaiMap] = await Promise.all([
      fetch('https://civitai.com/api/v1/models/' + modelId).then(function(r) {
        if (!r.ok) throw new Error('CivitAI ' + r.status);
        return r.json();
      }),
      getCivitaiMap()
    ]);

    const versions = modelData.modelVersions || [];
    if (!versions.length) {
      el.innerHTML = '<div class="empty" style="font-size:12px;">No versions found</div>';
      return;
    }

    var byVersion = civitaiMap.by_version || {};
    var byModel = civitaiMap.by_model || {};
    var otherVersions = byModel[String(modelId)] || [];

    var modelType = modelData.type || '';
    el.innerHTML = '<div style="font-size:13px;font-weight:600;margin-bottom:6px;">' +
      (modelData.name || 'Model') +
      (modelType ? ' <span class="ver-badge" style="font-size:9px;background:rgba(255,255,255,0.08);color:var(--muted);">' + modelType + '</span>' : '') +
      '</div>';

    // If no versionId from URL, default to first version
    if (!currentVersionId && versions.length) currentVersionId = versions[0].id;

    versions.forEach(function(ver) {
      var vid = String(ver.id);
      var entry = byVersion[vid];
      var statusBadge, actionHtml = '';

      if (entry && entry.status === 'downloading') {
        var pct = entry.dl_total ? Math.round(entry.dl_bytes / entry.dl_total * 100) : 0;
        statusBadge = '<span class="ver-badge ver-other" data-vid="' + vid + '">Downloading ' + pct + '%</span>';
      } else if (entry && entry.status === 'queued') {
        statusBadge = '<span class="ver-badge ver-other" data-vid="' + vid + '">Queued</span>';
      } else if (entry && entry.status === 'present') {
        statusBadge = '<span class="ver-badge ver-downloaded" data-vid="' + vid + '">Downloaded</span>';
      } else if (entry) {
        statusBadge = '<span class="ver-badge ver-in-catalog" data-vid="' + vid + '">In Catalog</span>';
        actionHtml = '<button class="btn btn-sm btn-download-ver" data-file="' + entry.file + '">Download</button>';
      } else if (otherVersions.length > 0) {
        statusBadge = '<span class="ver-badge ver-other">Other version</span>';
        actionHtml = '<button class="btn btn-sm btn-add-catalog" style="margin-top:2px;" data-vid="' + vid + '">+ Add</button>';
      } else {
        statusBadge = '<span class="ver-badge ver-missing">Not in catalog</span>';
        actionHtml = '<button class="btn btn-sm btn-add-catalog" style="margin-top:2px;" data-vid="' + vid + '">+ Add</button>';
      }

      var primaryFile = (ver.files || []).find(function(f) { return f.primary; }) || (ver.files || [])[0] || {};
      var sizeGB = primaryFile.sizeKB ? (primaryFile.sizeKB / 1000000).toFixed(1) + ' GB' : '';

      var isCurrent = (ver.id === currentVersionId);
      var item = document.createElement('div');
      item.className = 'version-item' + (isCurrent ? ' version-current' : '');
      item.innerHTML =
        '<div class="ver-row">' +
          '<span class="ver-name">' + (ver.name || vid) + '</span>' +
          statusBadge +
        '</div>' +
        '<div class="ver-row">' +
          '<span class="ver-meta">' + (ver.baseModel || '') + (sizeGB ? ' · ' + sizeGB : '') + '</span>' +
          actionHtml +
        '</div>';
      el.appendChild(item);
    });

    el.querySelectorAll('.btn-download-ver').forEach(function(btn) {
      btn.addEventListener('click', async function() {
        btn.disabled = true;
        btn.textContent = 'Queued';
        try {
          await studioPost('/api/admin/models/download/' + encodeURIComponent(btn.dataset.file), {});
          btn.textContent = 'Downloading...';
          showStatus('Download started — check Models page for progress', 'success');
          logEvent('ok', 'download queued — ' + btn.dataset.file);
        } catch (e) {
          showStatus('Download failed: ' + e.message, 'error');
          logEvent('err', 'download failed — ' + e.message);
          btn.disabled = false;
          btn.textContent = 'Download';
        }
      });
    });

    el.querySelectorAll('.btn-add-catalog').forEach(function(btn) {
      btn.addEventListener('click', async function() {
        btn.disabled = true;
        btn.textContent = 'Adding...';
        logEvent('info', 'add to catalog → v' + btn.dataset.vid);
        try {
          var result = await studioPost('/api/admin/civitai/add/' + btn.dataset.vid, {});
          if (result.status === 'restricted') {
            btn.textContent = '';
            btn.outerHTML = '<span class="ver-badge ver-restricted">Generation only</span>';
            showStatus(result.reason, 'error');
            logEvent('warn', 'add — restricted: ' + result.reason);
            return;
          } else if (result.status === 'already_exists') {
            showStatus('Already in catalog', 'success');
            logEvent('info', 'add — already exists');
          } else {
            showStatus('Added: ' + result.name, 'success');
            logEvent('ok', 'add — ' + result.name);
          }
          _civitaiMapCache = null;
          loadModelVersions(modelId, currentVersionId);
        } catch (e) {
          showStatus('Add failed: ' + e.message, 'error');
          logEvent('err', 'add failed — ' + e.message);
          btn.disabled = false;
          btn.textContent = '+ Add';
        }
      });
    });
  } catch (e) {
    el.innerHTML = '<div class="empty" style="font-size:12px;color:var(--error);">' + e.message + '</div>';
    logEvent('err', 'model versions failed — ' + e.message, 'civitai');
  }
}

async function loadImageGenData(imageId) {
  var el = $('imageGenData');
  el.innerHTML = '<div class="loading-spinner"><span class="spinner-lg"></span><div style="margin-top:8px;font-size:11px;color:var(--muted);">Loading generation data...</div></div>';
  logEvent('info', 'loading gen data — image #' + imageId, 'civitai');

  try {
    const data = await studioGet('/api/admin/civitai/image/' + imageId);
    logEvent('ok', 'gen data loaded — ' + (data.detected_type || 'unknown') + ', ' + (data.resources || []).length + ' resources', 'civitai');
    var html = '';

    // Detected type badge
    if (data.detected_type && data.detected_type !== 'unknown') {
      html += '<div style="margin-bottom:6px;"><span class="civitai-badge">' + data.detected_type.toUpperCase() + '</span></div>';
    }

    // Resources — checkpoints first, then LoRAs
    var resources = data.resources || [];
    if (resources.length) {
      var checkpoints = resources.filter(function(r) { return r.modelType === 'Checkpoint'; });
      var loras = resources.filter(function(r) { return r.modelType === 'LORA'; });
      var others = resources.filter(function(r) { return r.modelType !== 'Checkpoint' && r.modelType !== 'LORA'; });
      var sorted = checkpoints.concat(loras).concat(others);

      html += '<div class="gendata-section">Resources</div>';
      sorted.forEach(function(res) {
        var resVid = res.versionId ? String(res.versionId) : '';
        var vidAttr = resVid ? ' data-vid="' + resVid + '"' : '';
        var statusBadge;
        if (res.catalog_status === 'present') {
          statusBadge = '<span class="ver-badge ver-downloaded"' + vidAttr + '>Downloaded</span>';
        } else if (res.catalog_status === 'missing') {
          statusBadge = '<span class="ver-badge ver-in-catalog"' + vidAttr + '>In Catalog</span>';
        } else {
          statusBadge = '<span class="ver-badge ver-missing"' + vidAttr + '>Not found</span>';
        }
        var strength = (res.strength != null) ? ' · w:' + res.strength : '';
        var typeLabel = res.modelType === 'Checkpoint' ? 'CKP' : res.modelType === 'LORA' ? 'LoRA' : res.modelType;

        var actionBtn = '';
        if (res.catalog_status === 'missing' && res.catalog_file) {
          actionBtn = '<button class="btn btn-sm btn-download-ver" data-file="' + res.catalog_file + '">Download</button>';
        } else if (res.catalog_status === 'not_found' && res.versionId) {
          actionBtn = '<button class="btn btn-sm btn-add-catalog" style="margin-top:2px;" data-vid="' + res.versionId + '">+ Add</button>';
        }

        html += '<div class="resource-item">' +
          '<div class="ver-row">' +
            '<span class="res-type">' + typeLabel + '</span>' +
            '<span class="ver-name">' + (res.modelName || '?') + ' — ' + (res.versionName || '') + '</span>' +
            statusBadge +
          '</div>' +
          '<div class="ver-row">' +
            '<span class="ver-meta">' + (res.baseModel || '') + strength + '</span>' +
            actionBtn +
          '</div>' +
        '</div>';
      });
    }

    // Detected dependencies (from prompt parsing + hash resolution)
    var detectedDeps = data.detected_deps || [];
    if (detectedDeps.length) {
      html += '<div class="gendata-section">Detected in Prompt</div>';
      detectedDeps.forEach(function(dep) {
        var depVid = dep.civitai_version_id ? String(dep.civitai_version_id) : '';
        var vidAttr = depVid ? ' data-vid="' + depVid + '"' : '';
        var statusBadge;
        if (dep.catalog_status === 'present') {
          statusBadge = '<span class="ver-badge ver-downloaded"' + vidAttr + '>Downloaded</span>';
        } else if (dep.catalog_status === 'missing') {
          statusBadge = '<span class="ver-badge ver-in-catalog"' + vidAttr + '>In Catalog</span>';
        } else if (dep.catalog_status === 'not_found' && dep.civitai_version_id) {
          statusBadge = '<span class="ver-badge ver-missing"' + vidAttr + '>Not in catalog</span>';
        } else if (dep.catalog_status === 'unknown') {
          statusBadge = '<a class="ver-badge ver-missing" href="https://www.google.com/search?q=site%3Acivitai.com+' + encodeURIComponent(dep.name) + '" target="_blank" title="Search on Google" style="text-decoration:none;cursor:pointer;">Unresolved ↗</a>';
        } else {
          statusBadge = '<span class="ver-badge ver-missing">Not found</span>';
        }

        var typeLabel = dep.type === 'embedding' ? 'EMB' : 'LoRA';
        var weight = (dep.weight != null) ? ' · w:' + dep.weight : '';
        var resolvedName = dep.civitai_model_name ? (dep.civitai_model_name + ' — ' + (dep.civitai_version_name || '')) : dep.name;

        var actionBtn = '';
        if (dep.catalog_status === 'missing' && dep.catalog_file) {
          actionBtn = '<button class="btn btn-sm btn-download-ver" data-file="' + dep.catalog_file + '">Download</button>';
        } else if (dep.catalog_status === 'not_found' && dep.civitai_version_id) {
          actionBtn = '<button class="btn btn-sm btn-add-catalog" style="margin-top:2px;" data-vid="' + dep.civitai_version_id + '">+ Add</button>';
        }

        html += '<div class="resource-item">' +
          '<div class="ver-row">' +
            '<span class="res-type">' + typeLabel + '</span>' +
            '<span class="ver-name">' + resolvedName + '</span>' +
            statusBadge +
          '</div>' +
          '<div class="ver-row">' +
            '<span class="ver-meta">' + (dep.civitai_base_model || '') + weight + (dep.hash ? ' · #' + dep.hash.substring(0, 8) : '') + '</span>' +
            actionBtn +
          '</div>' +
        '</div>';
      });
    }

    // Meta / Settings
    var meta = data.meta || {};
    if (meta.prompt || meta.steps) {
      html += '<hr class="civitai-hr">';
      html += '<div class="gendata-section">Settings</div>';
      html += '<div class="gendata-meta">';
      if (meta.prompt) {
        var short = meta.prompt.length > 120 ? meta.prompt.substring(0, 120) + '...' : meta.prompt;
        html += '<div class="meta-prompt" title="' + meta.prompt.replace(/"/g, '&quot;') + '">' + short + '</div>';
      }
      var settings = [];
      if (meta.steps) settings.push('Steps: ' + meta.steps);
      if (meta.sampler) settings.push(meta.sampler);
      if (meta.cfgScale) settings.push('CFG: ' + meta.cfgScale);
      if (meta.seed) settings.push('Seed: ' + meta.seed);
      if (settings.length) html += '<div class="meta-settings">' + settings.join(' · ') + '</div>';
      html += '</div>';
    }

    // Create Preset button
    html += '<button class="btn btn-accent" id="createPresetBtn" style="width:100%;margin-top:8px;">Create Preset</button>';
    el.innerHTML = html;

    // Wire download buttons
    el.querySelectorAll('.btn-download-ver').forEach(function(btn) {
      btn.addEventListener('click', async function() {
        btn.disabled = true;
        btn.textContent = 'Queued';
        try {
          await studioPost('/api/admin/models/download/' + encodeURIComponent(btn.dataset.file), {});
          btn.textContent = 'Downloading...';
          showStatus('Download started — check Models page for progress', 'success');
          logEvent('ok', 'download queued — ' + btn.dataset.file);
        } catch (e) {
          showStatus('Download failed: ' + e.message, 'error');
          logEvent('err', 'download failed — ' + e.message);
          btn.disabled = false;
          btn.textContent = 'Download';
        }
      });
    });

    // Wire add-to-catalog buttons
    el.querySelectorAll('.btn-add-catalog').forEach(function(btn) {
      btn.addEventListener('click', async function() {
        btn.disabled = true;
        btn.textContent = 'Adding...';
        logEvent('info', 'add to catalog → v' + btn.dataset.vid);
        try {
          var result = await studioPost('/api/admin/civitai/add/' + btn.dataset.vid, {});
          if (result.status === 'restricted') {
            btn.outerHTML = '<span class="ver-badge ver-restricted">Generation only</span>';
            showStatus(result.reason, 'error');
            logEvent('warn', 'add — restricted: ' + result.reason);
          } else if (result.status === 'already_exists') {
            showStatus('Already in catalog', 'success');
            logEvent('info', 'add — already exists');
            btn.outerHTML = '<span class="ver-badge ver-in-catalog">In Catalog</span>';
          } else {
            showStatus('Added: ' + result.name, 'success');
            logEvent('ok', 'add — ' + result.name);
            var dlBtn = document.createElement('button');
            dlBtn.className = 'btn btn-sm btn-download-ver';
            dlBtn.textContent = 'Download';
            dlBtn.addEventListener('click', async function() {
              dlBtn.disabled = true;
              dlBtn.textContent = 'Queued';
              try {
                await studioPost('/api/admin/models/download/' + encodeURIComponent(result.file), {});
                dlBtn.textContent = 'Downloading...';
                showStatus('Download started — check Models page for progress', 'success');
                logEvent('ok', 'download queued — ' + result.file);
              } catch (e) {
                showStatus('Download failed: ' + e.message, 'error');
                logEvent('err', 'download failed — ' + e.message);
                dlBtn.disabled = false;
                dlBtn.textContent = 'Download';
              }
            });
            btn.replaceWith(dlBtn);
          }
        } catch (e) {
          showStatus('Add failed: ' + e.message, 'error');
          logEvent('err', 'add failed — ' + e.message);
          btn.disabled = false;
          btn.textContent = '+ Add';
        }
      });
    });

    // Wire create preset — show mapping preview first
    var presetBtn = $('createPresetBtn');
    if (presetBtn) {
      presetBtn.addEventListener('click', async function() {
        presetBtn.disabled = true;
        presetBtn.textContent = 'Loading workflow...';
        logEvent('info', 'preset — loading workflow for image #' + imageId);
        try {
          // Pick best workflow based on detected type
          var typeToWorkflow = {
            't2i': 't2i-unified',
            'i2i': 't2i-unified',
            'i2v': 'wan22-svi-dynamic',
            't2v': 'wan22-svi-dynamic',
          };
          var bestWfId = typeToWorkflow[data.detected_type] || 't2i-unified';

          var wfData = await studioGet('/api/admin/workflows/' + bestWfId);
          var wfInputs = wfData.inputs || [];

          // Flatten grouped inputs
          var flatInputs = {};
          wfInputs.forEach(function(group) {
            (group.items || []).forEach(function(inp) { flatInputs[inp.id] = inp; });
          });

          // Find checkpoint from resources
          var ckpResource = (data.resources || []).find(function(r) { return r.modelType === 'Checkpoint'; });
          var ckpFile = ckpResource ? (ckpResource.catalog_file || '') : '';
          var ckpName = ckpResource ? (ckpResource.modelName + ' ' + (ckpResource.versionName || '')) : '(none)';

          // Sampler mapping: CivitAI display name → ComfyUI internal value
          var samplerMap = {
            'Euler': 'euler', 'Euler a': 'euler_ancestral', 'Euler Ancestral': 'euler_ancestral',
            'DPM++ 2M': 'dpmpp_2m', 'DPM++ SDE': 'dpmpp_sde', 'DPM++ 2M SDE': 'dpmpp_2m_sde',
            'UniPC': 'uni_pc', 'LMS': 'lms', 'Heun': 'heun', 'DDIM': 'ddim',
            'DPM++ 2M Karras': 'dpmpp_2m', 'DPM++ SDE Karras': 'dpmpp_sde',
            'DPM++ 2M SDE Karras': 'dpmpp_2m_sde',
          };
          var civitaiSampler = meta.sampler || '';
          var mappedSampler = samplerMap[civitaiSampler] || '';

          // Detect if Karras scheduler from sampler name
          var mappedScheduler = 'normal';
          if (civitaiSampler.toLowerCase().includes('karras')) mappedScheduler = 'karras';
          if (civitaiSampler.toLowerCase().includes('exponential')) mappedScheduler = 'exponential';

          // Build sampler options HTML
          var samplerInput = flatInputs['sampler_name'] || {};
          var samplerOpts = (samplerInput.options || []);
          var samplerSelectHtml = '<select class="mapping-select" data-field="sampler_name">';
          samplerOpts.forEach(function(o) {
            var sel = (o.value === mappedSampler) ? ' selected' : '';
            samplerSelectHtml += '<option value="' + o.value + '"' + sel + '>' + o.label + '</option>';
          });
          samplerSelectHtml += '</select>';

          // Build scheduler options HTML
          var schedulerInput = flatInputs['scheduler'] || {};
          var schedulerOpts = (schedulerInput.options || []);
          var schedulerSelectHtml = '<select class="mapping-select" data-field="scheduler">';
          schedulerOpts.forEach(function(o) {
            var sel = (o.value === mappedScheduler) ? ' selected' : '';
            schedulerSelectHtml += '<option value="' + o.value + '"' + sel + '>' + o.label + '</option>';
          });
          schedulerSelectHtml += '</select>';

          // Collect resolved LoRAs from detected_deps + resources as {file, strength}
          var resolvedLoras = [];
          var loraFilesSeen = {};
          (data.detected_deps || []).forEach(function(dep) {
            if ((dep.type === 'lora' || dep.type === 'lycoris' || dep.source === 'prompt') && dep.catalog_file && !loraFilesSeen[dep.catalog_file]) {
              resolvedLoras.push({file: dep.catalog_file, strength: dep.weight || 1});
              loraFilesSeen[dep.catalog_file] = true;
            }
          });
          // Also check top-level resources for LoRAs in catalog
          (data.resources || []).forEach(function(res) {
            if (res.modelType === 'LORA' && res.catalog_file && !loraFilesSeen[res.catalog_file]) {
              resolvedLoras.push({file: res.catalog_file, strength: res.strength || 1});
              loraFilesSeen[res.catalog_file] = true;
            }
          });

          var lorasDisplay = resolvedLoras.length ? resolvedLoras.map(function(l) { return l.file + ' (w:' + l.strength + ')'; }).join(', ') : '(none in catalog)';

          // Build mapping preview
          var defaultName = (meta.prompt || 'CivitAI Image').substring(0, 60);
          var mapHtml =
            '<div class="mapping-panel">' +
            '<hr class="civitai-hr">' +
            '<div class="gendata-section">Preset Name</div>' +
            '<input class="mapping-input" id="presetNameInput" type="text" value="' + defaultName.replace(/"/g, '&quot;') + '" placeholder="Enter a name for this preset" style="margin-bottom:8px;">' +
            '<div class="gendata-section">Workflow: ' + bestWfId + '</div>' +
            '<table class="mapping-table">' +
            '<tr><th>Field</th><th>CivitAI</th><th>→</th><th>Workflow Value</th></tr>' +
            '<tr><td>checkpoint</td><td class="map-source">' + ckpName + '</td><td>→</td>' +
              '<td><input class="mapping-input" data-field="checkpoint" value="' + ckpFile + '" readonly style="opacity:0.7;"></td></tr>' +
            '<tr><td>' + (bestWfId.indexOf('wan22') !== -1 || bestWfId.indexOf('svi') !== -1 ? 'loras_high+low' : 'loras') + '</td>' +
              '<td class="map-source">' + (resolvedLoras.length || '0') + ' from deps</td><td>→</td>' +
              '<td><span class="ver-meta">' + lorasDisplay + '</span></td></tr>' +
            '<tr><td>positive_prompt</td><td class="map-source" title="' + (meta.prompt || '').replace(/"/g, '&quot;') + '">' +
              ((meta.prompt || '').substring(0, 50) + (meta.prompt && meta.prompt.length > 50 ? '...' : '')) + '</td><td>→</td>' +
              '<td><textarea class="mapping-input" data-field="positive_prompt" rows="2">' + (meta.prompt || '') + '</textarea></td></tr>' +
            '<tr><td>negative_prompt</td><td class="map-source">' + ((meta.negativePrompt || '').substring(0, 40) || '(empty)') + '</td><td>→</td>' +
              '<td><textarea class="mapping-input" data-field="negative_prompt" rows="1">' + (meta.negativePrompt || '') + '</textarea></td></tr>' +
            '<tr><td>steps</td><td class="map-source">' + (meta.steps || '') + '</td><td>→</td>' +
              '<td><input class="mapping-input" data-field="steps" type="number" value="' + (meta.steps || 20) + '"></td></tr>' +
            '<tr><td>cfg</td><td class="map-source">' + (meta.cfgScale || '') + '</td><td>→</td>' +
              '<td><input class="mapping-input" data-field="cfg" type="number" step="0.5" value="' + (meta.cfgScale || 7) + '"></td></tr>' +
            '<tr><td>sampler</td><td class="map-source">' + civitaiSampler + '</td><td>→</td>' +
              '<td>' + samplerSelectHtml + '</td></tr>' +
            '<tr><td>scheduler</td><td class="map-source">' + (civitaiSampler.includes('Karras') ? 'Karras (from sampler)' : 'Normal') + '</td><td>→</td>' +
              '<td>' + schedulerSelectHtml + '</td></tr>' +
            '<tr><td>seed</td><td class="map-source">' + (meta.seed || '') + '</td><td>→</td>' +
              '<td><input class="mapping-input" data-field="seed" type="number" value="' + (meta.seed || -1) + '"></td></tr>' +
            '</table>' +
            '<button class="btn btn-accent" id="confirmPresetBtn" style="width:100%;margin-top:8px;">Confirm & Create Preset</button>' +
            '</div>';

          // Replace button with mapping panel
          presetBtn.outerHTML = mapHtml;

          // Force Chrome popup to resize to new content
          document.body.style.minHeight = document.body.scrollHeight + 'px';

          // Wire confirm button
          $('confirmPresetBtn').addEventListener('click', async function() {
            var confirmBtn = $('confirmPresetBtn');
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Creating...';

            // Read values from mapping inputs
            var params = {};
            el.querySelectorAll('.mapping-input[data-field], .mapping-select[data-field]').forEach(function(inp) {
              var field = inp.dataset.field;
              if (!field) return;
              var val = inp.value;
              if (inp.type === 'number') val = parseFloat(val);
              params[field] = val;
            });
            // Add resolved LoRAs — format depends on workflow
            var selectedWfId = bestWfId;
            if (resolvedLoras.length) {
              if (selectedWfId.indexOf('wan22') !== -1 || selectedWfId.indexOf('svi') !== -1) {
                params.loras_high = resolvedLoras;
                params.loras_low = resolvedLoras;
              } else {
                params.loras = resolvedLoras;
              }
            }

            // For svi-dynamic: convert flat prompt to scenes array
            if (selectedWfId.indexOf('svi') !== -1 && params.positive_prompt && !params.scenes) {
              params.scenes = [{
                prompt: params.positive_prompt,
                duration: 5,
                seed: params.seed || -1
              }];
              delete params.positive_prompt;
              delete params.seed;
            }

            try {
              // Download the reference asset
              var assetResult = await studioPost('/api/admin/loras/gallery/download-single/' + imageId, {});

              var presetName = ($('presetNameInput') ? $('presetNameInput').value.trim() : '') || 'CivitAI Image ' + imageId;
              var presetId = presetName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'civitai-img-' + imageId;
              var preset = {
                id: presetId,
                name: presetName,
                description: 'Created from CivitAI image #' + imageId,
                private: true,
                source: {
                  type: 'civitai_image',
                  civitai_image_id: imageId,
                  civitai_url: 'https://civitai.com/images/' + imageId,
                  fetched_at: new Date().toISOString(),
                  raw: data.raw,
                  resources: data.resources,
                  meta: data.meta,
                  techniques: data.techniques,
                  tools: data.tools,
                  detected_type: data.detected_type
                },
                workflow: {
                  workflow_id: bestWfId,
                  workflow_name: wfData.name || bestWfId,
                  params: params
                }
              };
              await studioPost('/api/admin/presets', preset);
              showStatus('Preset created: ' + presetId, 'success');
              logEvent('ok', 'preset created — ' + presetId + ' (wf: ' + bestWfId + ')');
              confirmBtn.textContent = 'Created!';
            } catch (e) {
              showStatus('Error: ' + e.message, 'error');
              logEvent('err', 'preset create failed — ' + e.message);
              confirmBtn.disabled = false;
              confirmBtn.textContent = 'Confirm & Create Preset';
            }
          });
        } catch (e) {
          showStatus('Error loading workflow: ' + e.message, 'error');
          logEvent('err', 'preset workflow load failed — ' + e.message);
          presetBtn.disabled = false;
          presetBtn.textContent = 'Create Preset';
        }
      });
    }
  } catch (e) {
    el.innerHTML = '<div class="empty" style="font-size:12px;color:var(--error);">' + e.message + '</div>';
    logEvent('err', 'gen data failed — ' + e.message, 'civitai');
  }
}

init().then(initStudio);

// Side panel: re-check CivitAI tab when user navigates or switches tabs
if (chrome.tabs && chrome.tabs.onActivated) {
  chrome.tabs.onActivated.addListener(() => { initStudio(); });
}
if (chrome.tabs && chrome.tabs.onUpdated) {
  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (changeInfo.url) initStudio();
  });
}
