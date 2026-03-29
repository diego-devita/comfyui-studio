/**
 * ComfyUI Studio — Shared JS
 * Common helpers, apiFetch, toast, confirm dialog, activity panel, copy utils.
 * Loaded before each page's own <script> block.
 */

/* ================================================================
   1. Helpers
   ================================================================ */

function escHtml(str) {
  var d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

function fmtDate(ts) {
  if (!ts) return '--';
  return ts.replace('T', ' ').substring(0, 19);
}

function fmtDuration(sec) {
  if (!sec) return '';
  if (sec < 60) {
    return '<span class="pill">' + sec + 's</span>';
  }
  var m = Math.floor(sec / 60), s = sec % 60;
  var human = m + 'm' + (s > 0 ? s + 's' : '');
  return '<span class="pill">' + human + '</span>' +
         '<span class="pill pill-faded">(' + sec + 's)</span>';
}

function fmtGB(bytes) { return (bytes / 1073741824).toFixed(1) + ' GB'; }

function fmtBytes(bytes) {
  if (!bytes || bytes <= 0) return '0 B';
  if (bytes < 1024)        return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

/* ================================================================
   2. apiFetch
   ================================================================ */

function apiFetch(url, opts) {
  opts = opts || {};
  opts.credentials = 'include';
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    opts.headers = Object.assign({'Content-Type': 'application/json'}, opts.headers || {});
    opts.body = JSON.stringify(opts.body);
  }
  return fetch(url, opts).then(function(r) {
    if (r.status === 401 || r.status === 403) {
      window.location = '/login';
      throw new Error('auth');
    }
    return r;
  });
}

/* ================================================================
   3. Toast (centered at top)
   ================================================================ */

var _toastStack = [];
function _layoutToasts() {
  var top = 24;
  for (var i = _toastStack.length - 1; i >= 0; i--) {
    var t = _toastStack[i];
    if (!t.parentElement) { _toastStack.splice(i, 1); continue; }
    t.style.top = top + 'px';
    top += t.offsetHeight + 8;
  }
}
function showToast(msg, duration, type) {
  var toast = document.createElement('div');
  toast.className = 'studio-toast' + (type ? ' ' + type : '');
  toast.innerHTML = msg + '<button class="toast-close" onclick="this.parentElement.remove()">&times;</button>';
  if (duration) {
    var bar = document.createElement('div');
    bar.className = 'toast-bar';
    bar.style.transition = 'transform ' + duration + 'ms linear';
    toast.appendChild(bar);
    requestAnimationFrame(function() { bar.style.transform = 'scaleX(0)'; });
    setTimeout(function() {
      toast.style.opacity = '0';
      setTimeout(function() { toast.remove(); _layoutToasts(); }, 300);
    }, duration);
  }
  _toastStack.push(toast);
  document.body.appendChild(toast);
  _layoutToasts();
  var obs = new MutationObserver(function() { if (!toast.parentElement) { obs.disconnect(); _layoutToasts(); } });
  obs.observe(document.body, { childList: true });
  return toast;
}

/* ================================================================
   4. Confirm Dialog
   ================================================================ */

var _dialogResolve = null;
function studioConfirm(msg, opts) {
  opts = opts || {};
  return new Promise(function(resolve) {
    var dlg = document.getElementById('studioDialog');
    document.getElementById('studioDialogMsg').textContent = msg;
    var yesBtn = document.getElementById('studioDialogYes');
    var noBtn = document.getElementById('studioDialogNo');
    yesBtn.textContent = opts.yes || 'Confirm';
    yesBtn.className = 'studio-dialog-btn ' + (opts.danger ? 'danger' : 'primary');
    noBtn.textContent = opts.no || 'Cancel';
    _dialogResolve = resolve;
    dlg.showModal();
    yesBtn.onclick = function() { dlg.close(); resolve(true); };
    noBtn.onclick = function() { dlg.close(); resolve(false); };
    dlg.addEventListener('close', function handler() { dlg.removeEventListener('close', handler); resolve(false); });
  });
}

/* ================================================================
   5. Activity Panel
   ================================================================ */

function initActivityPanel() {
  var $actPanel = document.getElementById('activityPanel');
  if (!$actPanel) return;
  var $actList = document.getElementById('activityList');
  var $actDot = document.getElementById('activityDot');
  var $actToggle = document.getElementById('activityToggle');
  var $actClose = document.getElementById('activityClose');
  if (!$actList || !$actDot || !$actToggle || !$actClose) return;

  var _actOpen = false;
  var _actWs = null;

  function renderEvent(evt) {
    var ts = (evt.timestamp || '').substring(11, 19);
    return '<div class="activity-item">' +
      '<span class="activity-severity ' + (evt.severity || 'info') + '"></span>' +
      '<span class="activity-time">' + ts + '</span>' +
      '<span class="activity-msg">' + escHtml(evt.message || '') + '</span>' +
    '</div>';
  }

  function loadActivityHistory() {
    apiFetch('/api/admin/events?limit=50').then(function(resp) {
      if (!resp.ok) return;
      return resp.json();
    }).then(function(events) {
      if (!events || !events.length) {
        $actList.innerHTML = '<div class="activity-empty">No activity yet</div>';
        return;
      }
      $actList.innerHTML = events.map(renderEvent).join('');
      $actList.scrollTop = $actList.scrollHeight;
    }).catch(function() {});
  }

  function connectActivityWS() {
    if (_actWs && _actWs.readyState <= 1) return;
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    _actWs = new WebSocket(proto + '//' + location.host + '/api/run/ws');
    _actWs.onopen = function() { $actDot.classList.add('connected'); };
    _actWs.onmessage = function(e) {
      if (typeof e.data !== 'string') return;
      try {
        var msg = JSON.parse(e.data);
        if (!msg.type || msg.type.indexOf('.') < 0) return;
        if (_actOpen) {
          $actList.insertAdjacentHTML('beforeend', renderEvent(msg));
          $actList.scrollTop = $actList.scrollHeight;
        } else {
          $actDot.classList.add('has-new');
        }
      } catch (_) {}
    };
    _actWs.onclose = function() {
      _actWs = null;
      $actDot.classList.remove('connected');
      setTimeout(connectActivityWS, 3000);
    };
  }

  $actToggle.addEventListener('click', function() {
    _actOpen = !_actOpen;
    $actPanel.classList.toggle('open', _actOpen);
    $actDot.classList.remove('has-new');
    if (_actOpen) loadActivityHistory();
  });
  $actClose.addEventListener('click', function() {
    _actOpen = false;
    $actPanel.classList.remove('open');
  });
  document.addEventListener('click', function(e) {
    if (_actOpen && !$actPanel.contains(e.target) && !$actToggle.contains(e.target)) {
      _actOpen = false;
      $actPanel.classList.remove('open');
    }
  });

  connectActivityWS();
}

/* ================================================================
   6. Live Bar
   ================================================================ */

function createLiveBar(elementId, intervalMs) {
  var $bar = document.getElementById(elementId);
  if (!$bar) return { start: function() {} };
  return {
    start: function() {
      $bar.style.transition = 'none';
      $bar.style.transform = 'scaleX(0)';
      $bar.offsetHeight; // force reflow
      $bar.style.transition = 'transform ' + intervalMs + 'ms linear';
      $bar.style.transform = 'scaleX(1)';
    }
  };
}

/* ================================================================
   7. Copy to clipboard
   ================================================================ */

function copyToClipboard(text, triggerEl) {
  navigator.clipboard.writeText(text).then(function() {
    if (triggerEl) {
      var old = triggerEl.querySelector('.copy-tip');
      if (old) old.remove();
      triggerEl.style.opacity = '1';
      var tip = document.createElement('span');
      tip.className = 'copy-tip';
      tip.textContent = 'Copied!';
      tip.style.cssText = 'margin-left:6px;font-size:10px;color:var(--accent);opacity:1;transition:opacity 0.3s;';
      triggerEl.appendChild(tip);
      setTimeout(function() { tip.style.opacity = '0'; setTimeout(function() { tip.remove(); triggerEl.style.opacity = '0.4'; }, 300); }, 3000);
    }
  });
}

/**
 * Returns an inline HTML snippet for a copy button (icon + inline onclick).
 * Used in history/queue where HTML is built as strings.
 */
function copyBtn(text) {
  var escaped = String(text).replace(/'/g, "\\'").replace(/\n/g, '\\n');
  return ' <span style="cursor:pointer;opacity:0.4;font-size:12px;transition:opacity 0.15s;position:relative;" ' +
    'onmouseenter="this.style.opacity=0.8" onmouseleave="this.style.opacity=0.4" ' +
    'onclick="event.stopPropagation();var el=this;var ot=el.querySelector(\'.copy-tip\');if(ot)ot.remove();navigator.clipboard.writeText(\'' + escaped + '\').then(function(){el.style.opacity=1;var tip=document.createElement(\'span\');tip.className=\'copy-tip\';tip.textContent=\'Copied!\';tip.style.cssText=\'margin-left:6px;font-size:10px;color:var(--accent);opacity:1;transition:opacity 0.3s;\';el.appendChild(tip);setTimeout(function(){tip.style.opacity=0;setTimeout(function(){tip.remove();el.style.opacity=0.4;},300);},3000);})" ' +
    'title="Copy"><span class="icon icon-copy icon-sm"></span></span>';
}

/* ================================================================
   8. Auto-inject common HTML + init
   ================================================================ */

document.addEventListener('DOMContentLoaded', function() {
  // ── Mobile nav: hamburger + drawer ──
  (function() {
    var nav = document.querySelector('.main-nav');
    if (!nav) return;

    // Create hamburger button
    var hamburger = document.createElement('button');
    hamburger.className = 'nav-hamburger';
    hamburger.setAttribute('aria-label', 'Toggle navigation');
    hamburger.innerHTML = '<span class="nav-hamburger-icon"></span>';

    // Collect drawer links (all nav-links except settings gear, activity bell, logout, db button)
    var allLinks = Array.prototype.slice.call(nav.querySelectorAll('.nav-link'));
    var drawerLinks = [];
    var keepInRow = [];
    allLinks.forEach(function(link) {
      if (link.classList.contains('nav-activity') ||
          link.classList.contains('nav-logout') ||
          link.querySelector('.icon-gear') ||
          link.id === 'docsLink') {
        keepInRow.push(link);
      } else {
        drawerLinks.push(link);
      }
    });

    // Build wrapper: .nav-links > .nav-links-inner > [links]
    var wrapper = document.createElement('div');
    wrapper.className = 'nav-links';
    var inner = document.createElement('div');
    inner.className = 'nav-links-inner';
    drawerLinks.forEach(function(link) { inner.appendChild(link); });
    wrapper.appendChild(inner);

    // Insert hamburger first, then wrapper, then the kept-in-row items stay
    nav.insertBefore(hamburger, nav.firstChild);
    // Insert wrapper before the first remaining element (gear/bell/logout)
    if (keepInRow.length > 0) {
      nav.insertBefore(wrapper, keepInRow[0]);
    } else {
      nav.appendChild(wrapper);
    }

    // Toggle
    hamburger.addEventListener('click', function(e) {
      e.stopPropagation();
      var isOpen = wrapper.classList.toggle('open');
      hamburger.classList.toggle('open', isOpen);
    });

    // Close on link click inside drawer
    inner.addEventListener('click', function(e) {
      if (e.target.closest('.nav-link')) {
        wrapper.classList.remove('open');
        hamburger.classList.remove('open');
      }
    });

    // Close on click outside
    document.addEventListener('click', function(e) {
      if (wrapper.classList.contains('open') && !nav.contains(e.target)) {
        wrapper.classList.remove('open');
        hamburger.classList.remove('open');
      }
    });
  })();

  // Inject confirm dialog if not present
  if (!document.getElementById('studioDialog')) {
    var dlg = document.createElement('dialog');
    dlg.className = 'studio-dialog';
    dlg.id = 'studioDialog';
    dlg.innerHTML =
      '<div class="studio-dialog-body" id="studioDialogMsg"></div>' +
      '<div class="studio-dialog-actions">' +
        '<button class="studio-dialog-btn" id="studioDialogNo">Cancel</button>' +
        '<button class="studio-dialog-btn primary" id="studioDialogYes">Confirm</button>' +
      '</div>';
    document.body.appendChild(dlg);
  }

  // Inject activity panel if toggle exists but panel doesn't
  if (document.getElementById('activityToggle') && !document.getElementById('activityPanel')) {
    var panel = document.createElement('div');
    panel.className = 'activity-panel';
    panel.id = 'activityPanel';
    panel.innerHTML =
      '<div class="activity-panel-inner">' +
        '<div class="activity-panel-header">' +
          '<span class="activity-panel-title">Activity</span>' +
          '<button class="activity-panel-close" id="activityClose">&times;</button>' +
        '</div>' +
        '<div class="activity-list" id="activityList"></div>' +
      '</div>';
    // Insert right after the nav
    var nav = document.querySelector('.main-nav');
    if (nav && nav.nextSibling) {
      nav.parentNode.insertBefore(panel, nav.nextSibling);
    } else {
      document.body.insertBefore(panel, document.body.firstChild);
    }
  }

  initActivityPanel();

  // ── Docs link ──
  var _docsLink = document.getElementById('docsLink');
  if (_docsLink) {
    _docsLink.style.display = 'none';
    try {
      apiFetch('/api/admin/system/status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (data && data.docs_url) {
            _docsLink.href = data.docs_url;
            _docsLink.style.display = 'flex';
            _docsLink.style.alignItems = 'center';
          }
        })
        .catch(function() {});
    } catch(e) {}
  }
});
