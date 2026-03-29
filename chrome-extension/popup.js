/* ComfyUI Studio — Chrome Extension */

// ── Storage helpers ──

function getSettings() {
  return new Promise(resolve => {
    chrome.storage.local.get(['runpodKey', 'studioUrl', 'studioKey', 'templateId'], resolve);
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
  const data = await r.json();
  if (data.errors) throw new Error(data.errors[0].message);
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

// ── UI helpers ──

function $(id) { return document.getElementById(id); }

function showStatus(msg, type) {
  const el = $('statusMsg');
  el.textContent = msg;
  el.className = 'status-msg visible ' + type;
  setTimeout(() => { el.className = 'status-msg'; }, 4000);
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

// ── Tab navigation ──

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    $('panel-' + tab.dataset.tab).classList.add('active');
  });
});

// ── Pods panel ──

async function loadPods() {
  const el = $('podsList');
  try {
    const data = await runpodQuery(`query {
      myself {
        pods {
          id name desiredStatus
          runtime { uptimeInSeconds gpus { id gpuUtilPercent memoryUtilPercent } }
          machine { podHostId gpuDisplayName }
          costPerHr
        }
      }
    }`);
    const pods = data.myself.pods;
    if (!pods.length) {
      el.innerHTML = '<div class="empty">No pods found</div>';
      return;
    }
    el.innerHTML = '';
    pods.forEach(pod => {
      const running = pod.desiredStatus === 'RUNNING';
      const gpu = pod.machine?.gpuDisplayName || '?';
      const uptime = pod.runtime?.uptimeInSeconds ? formatUptime(pod.runtime.uptimeInSeconds * 1000) : '-';
      const cost = pod.costPerHr ? '$' + pod.costPerHr.toFixed(2) + '/hr' : '';
      const hostId = pod.machine?.podHostId || '';
      const studioLink = running && hostId
        ? `<a href="https://${pod.id}-8000.proxy.runpod.net" target="_blank" style="color:var(--accent);text-decoration:none;font-size:10px;">Open Studio ↗</a>`
        : '';

      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-title">' + (pod.name || pod.id) + '</div>' +
        '<div class="card-row">' +
          '<span class="badge ' + (running ? 'badge-running' : 'badge-exited') + '">' + pod.desiredStatus + '</span>' +
          '<span class="card-meta">' + gpu + '</span>' +
        '</div>' +
        '<div class="card-row">' +
          '<span class="card-meta">' + uptime + ' · ' + cost + '</span>' +
          studioLink +
        '</div>' +
        '<div class="card-actions">' +
          (running
            ? '<button class="btn btn-sm btn-danger" data-action="stop" data-id="' + pod.id + '">Stop</button>'
            : '<button class="btn btn-sm" data-action="resume" data-id="' + pod.id + '">Resume</button>') +
          '<button class="btn btn-sm btn-danger" data-action="terminate" data-id="' + pod.id + '">Terminate</button>' +
        '</div>';
      el.appendChild(card);
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
          } else if (action === 'terminate') {
            await runpodMutation(`mutation { podTerminate(input: {podId: "${id}"}) }`);
          }
          showStatus('Pod ' + action + ' OK', 'success');
          setTimeout(loadPods, 2000);
        } catch (e) {
          showStatus('Error: ' + e.message, 'error');
          btn.disabled = false;
        }
      });
    });
  } catch (e) {
    el.innerHTML = '<div class="empty">' + e.message + '</div>';
  }
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
    const vols = data.myself.networkVolumes;
    if (!vols.length) {
      el.innerHTML = '<div class="empty">No network volumes</div>';
      return;
    }
    el.innerHTML = '';
    vols.forEach(vol => {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML =
        '<div class="card-title">' + (vol.name || vol.id) + '</div>' +
        '<div class="card-meta">' + vol.size + ' GB · ' + (vol.dataCenterId || 'unknown region') + '</div>';
      el.appendChild(card);
    });

    // Also populate volume selector in Launch tab
    const volSelect = $('volumeSelect');
    volSelect.innerHTML = '<option value="">-- No volume --</option>';
    vols.forEach(vol => {
      const o = document.createElement('option');
      o.value = vol.id;
      o.textContent = (vol.name || vol.id) + ' (' + vol.size + 'GB)';
      volSelect.appendChild(o);
    });
  } catch (e) {
    el.innerHTML = '<div class="empty">' + e.message + '</div>';
  }
}

// ── Launch panel ──

async function loadGpuTypes() {
  const sel = $('gpuSelect');
  try {
    const data = await runpodQuery(`query {
      gpuTypes {
        id displayName memoryInGb
        lowestPrice { minimumBidPrice uninterruptablePrice }
      }
    }`);
    sel.innerHTML = '<option value="">-- Select GPU --</option>';
    const gpus = (data.gpuTypes || [])
      .filter(g => g.lowestPrice)
      .sort((a, b) => (a.lowestPrice.uninterruptablePrice || 99) - (b.lowestPrice.uninterruptablePrice || 99));
    gpus.forEach(g => {
      const price = g.lowestPrice.uninterruptablePrice
        ? '$' + g.lowestPrice.uninterruptablePrice.toFixed(2) + '/hr'
        : 'bid only';
      const o = document.createElement('option');
      o.value = g.id;
      o.textContent = g.displayName + ' (' + g.memoryInGb + 'GB) — ' + price;
      sel.appendChild(o);
    });
  } catch (e) {
    sel.innerHTML = '<option value="">Error loading GPUs</option>';
  }
}

$('launchBtn').addEventListener('click', async () => {
  const gpuId = $('gpuSelect').value;
  const cloudType = $('cloudType').value;
  const volumeId = $('volumeSelect').value;
  const templateId = $('templateId').value.trim();
  const settings = await getSettings();

  if (!gpuId) { showStatus('Select a GPU', 'error'); return; }
  if (!templateId && !settings.templateId) { showStatus('Enter a template ID', 'error'); return; }

  const btn = $('launchBtn');
  btn.disabled = true;
  btn.textContent = 'Launching...';

  try {
    const tpl = templateId || settings.templateId;
    const mutation = `mutation {
      podFindAndDeployOnDemand(input: {
        cloudType: ${cloudType}
        gpuTypeId: "${gpuId}"
        gpuCount: 1
        templateId: "${tpl}"
        ${volumeId ? `networkVolumeId: "${volumeId}"` : ''}
      }) { id name desiredStatus machine { podHostId } }
    }`;
    const data = await runpodMutation(mutation);
    const pod = data.podFindAndDeployOnDemand;
    showStatus('Pod launched: ' + (pod.name || pod.id), 'success');
    setTimeout(loadPods, 3000);
  } catch (e) {
    showStatus('Launch failed: ' + e.message, 'error');
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
    const running = (data.myself.pods || []).filter(p => p.desiredStatus === 'RUNNING');

    if (!running.length) {
      showStatus('No running pods found', 'error');
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
    btn.innerHTML = '&#128269;';
  }
});

// ── Settings panel ──

$('saveSettingsBtn').addEventListener('click', async () => {
  await saveSettings({
    runpodKey: $('runpodKey').value.trim(),
    studioUrl: $('studioUrl').value.trim(),
    studioKey: $('studioKey').value.trim(),
    templateId: $('templateId').value.trim(),
  });
  showStatus('Settings saved', 'success');
  // Reload data with new keys
  loadPods();
  loadStorage();
  loadGpuTypes();
  checkStudio();
});

// Populate settings on load
getSettings().then(s => {
  $('runpodKey').value = s.runpodKey || '';
  $('studioUrl').value = s.studioUrl || '';
  $('studioKey').value = s.studioKey || '';
  $('templateId').value = s.templateId || '';
});

// ── Studio status dot ──

async function checkStudio() {
  const dot = $('studioDot');
  try {
    await studioGet('/api/health');
    dot.className = 'dot dot-green';
    dot.title = 'Studio: Connected';
  } catch {
    dot.className = 'dot dot-gray';
    dot.title = 'Studio: Not connected';
  }
}

// ── Init ──

loadPods();
loadStorage();
loadGpuTypes();
checkStudio();
