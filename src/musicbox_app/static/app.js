(() => {
  const state = {
    snapshot: null,
    mappings: {},
    entries: [],
    selectedPath: '',
    events: [],
    lastEventId: 0,
    pendingUploads: [],
    lastAutoCard: '',
    sse: null,
    pollTimer: null,
  };

  const $ = (id) => document.getElementById(id);

  function setText(id, value) {
    const el = $(id);
    if (el) {
      el.textContent = value == null || value === '' ? '-' : String(value);
    }
  }

  function toast(message, level = 'info') {
    const stack = $('toast-stack');
    if (!stack) {
      return;
    }

    const el = document.createElement('div');
    el.className = `toast ${level}`;
    el.textContent = message;
    stack.appendChild(el);

    window.setTimeout(() => {
      el.remove();
    }, 3500);
  }

  async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
      headers: {
        'Accept': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    let payload = null;
    try {
      payload = await response.json();
    } catch (_err) {
      payload = null;
    }

    if (!response.ok || !payload || payload.ok === false) {
      const message = payload && payload.error ? payload.error : `${response.status} ${response.statusText}`;
      throw new Error(message);
    }

    return payload;
  }

  function badgeBool(value) {
    return value ? 'ok' : 'offline';
  }

  function appendEvents(events) {
    if (!Array.isArray(events) || events.length === 0) {
      return;
    }

    for (const ev of events) {
      const id = Number(ev.id || 0);
      if (id <= state.lastEventId) {
        continue;
      }
      state.lastEventId = id;
      const level = ev.level && ev.level !== 'info' ? ` [${String(ev.level).toUpperCase()}]` : '';
      state.events.push(`[${ev.ts || '--:--:--'}]${level} ${ev.msg || ''}`.trim());
    }

    if (state.events.length > 500) {
      state.events = state.events.slice(-500);
    }

    const logEl = $('events-log');
    if (logEl) {
      logEl.textContent = state.events.join('\n');
      logEl.scrollTop = logEl.scrollHeight;
    }
  }

  function renderStatus(snapshot) {
    if (!snapshot) {
      return;
    }

    const player = snapshot.player || {};
    const health = snapshot.health || {};
    const buttons = Array.isArray(snapshot.buttons) ? snapshot.buttons : [0, 0, 0, 0];

    setText('badge-player', player.status || 'stopped');
    setText('badge-card', snapshot.last_card || '-');
    setText('badge-rfid', health.rfid_device ? 'ready' : 'missing');
    setText('badge-seesaw', badgeBool(Boolean(health.seesaw)));

    setText('now-file', player.file || 'No active track');
    setText('now-volume', `Volume: ${player.volume == null ? '--' : player.volume}`);

    setText('hw-b1', buttons[0] ? 'pressed' : 'released');
    setText('hw-b2', buttons[1] ? 'pressed' : 'released');
    setText('hw-b3', buttons[2] ? 'pressed' : 'released');
    setText('hw-b4', buttons[3] ? 'pressed' : 'released');
    setText('hw-rot', `${snapshot.rotary_last || '-'} / ${snapshot.rotary_pos || 0}`);
    setText('hw-sw', snapshot.rotary_sw ? 'pressed' : 'released');

    setText('health-seesaw', badgeBool(Boolean(health.seesaw)));
    setText('health-rfid', health.rfid_device || 'not found');
    setText('health-audio', health.audio_device || 'not detected');
    setText('health-mpv', badgeBool(Boolean(health.mpv_running)));

    const speed = snapshot.settings && snapshot.settings.rotary_led_step_ms;
    if (speed != null) {
      const slider = $('led-speed');
      if (slider) {
        slider.value = String(speed);
      }
      setText('led-speed-value', speed);
    }

    if (snapshot.last_card) {
      const cardInput = $('map-card');
      if (cardInput && (!cardInput.value || cardInput.value === state.lastAutoCard)) {
        cardInput.value = snapshot.last_card;
        state.lastAutoCard = snapshot.last_card;
      }
    }

    appendEvents(snapshot.events || []);
  }

  function applySnapshot(payload) {
    state.snapshot = payload;
    renderStatus(payload);
  }

  function activateTab(tabName) {
    document.querySelectorAll('.tab').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    document.querySelectorAll('.panel').forEach((panel) => {
      panel.classList.toggle('active', panel.id === `tab-${tabName}`);
    });
  }

  function setSelectedPath(path) {
    state.selectedPath = path || '';
    setText('map-selected', state.selectedPath || 'No library item selected');
    renderLibrary();
  }

  function renderLibrary() {
    const tbody = $('library-body');
    if (!tbody) {
      return;
    }
    tbody.textContent = '';

    const pathToCards = {};
    for (const [card, target] of Object.entries(state.mappings || {})) {
      if (!pathToCards[target]) {
        pathToCards[target] = [];
      }
      pathToCards[target].push(card);
    }

    for (const entry of state.entries) {
      const tr = document.createElement('tr');
      if (entry.path === state.selectedPath) {
        tr.classList.add('selected');
      }

      const typeTd = document.createElement('td');
      typeTd.textContent = entry.type;
      tr.appendChild(typeTd);

      const pathTd = document.createElement('td');
      pathTd.textContent = entry.path;
      tr.appendChild(pathTd);

      const mapTd = document.createElement('td');
      mapTd.textContent = (pathToCards[entry.path] || []).join(', ') || '-';
      tr.appendChild(mapTd);

      const actionsTd = document.createElement('td');
      actionsTd.className = 'actions';

      const playBtn = document.createElement('button');
      playBtn.textContent = 'Play';
      playBtn.addEventListener('click', async () => {
        try {
          await apiFetch('/api/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file: entry.path }),
          });
          toast(`Playing ${entry.path}`);
        } catch (err) {
          toast(`Play failed: ${err.message}`, 'error');
        }
      });
      actionsTd.appendChild(playBtn);

      const selectBtn = document.createElement('button');
      selectBtn.textContent = 'Select';
      selectBtn.addEventListener('click', () => {
        setSelectedPath(entry.path);
      });
      actionsTd.appendChild(selectBtn);

      const delBtn = document.createElement('button');
      delBtn.textContent = 'Delete';
      delBtn.className = 'danger';
      delBtn.addEventListener('click', async () => {
        const ok = window.confirm(`Delete ${entry.path}?`);
        if (!ok) {
          return;
        }
        try {
          await apiFetch('/api/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: entry.path }),
          });
          toast(`Deleted ${entry.path}`);
          if (state.selectedPath === entry.path) {
            setSelectedPath('');
          }
          await loadLibrary();
        } catch (err) {
          toast(`Delete failed: ${err.message}`, 'error');
        }
      });
      actionsTd.appendChild(delBtn);

      tr.appendChild(actionsTd);
      tbody.appendChild(tr);
    }
  }

  function renderMappings() {
    const tbody = $('mappings-body');
    if (!tbody) {
      return;
    }
    tbody.textContent = '';

    const rows = Object.entries(state.mappings || {}).sort((a, b) => a[0].localeCompare(b[0]));
    for (const [card, target] of rows) {
      const tr = document.createElement('tr');

      const cardTd = document.createElement('td');
      cardTd.textContent = card;
      tr.appendChild(cardTd);

      const targetTd = document.createElement('td');
      targetTd.textContent = target;
      tr.appendChild(targetTd);

      const actionsTd = document.createElement('td');
      actionsTd.className = 'actions';

      const useBtn = document.createElement('button');
      useBtn.textContent = 'Use';
      useBtn.addEventListener('click', () => {
        $('map-card').value = card;
        $('map-target').value = target;
        setSelectedPath(target);
        activateTab('cards');
      });
      actionsTd.appendChild(useBtn);

      const playBtn = document.createElement('button');
      playBtn.textContent = 'Play';
      playBtn.addEventListener('click', async () => {
        try {
          await apiFetch('/api/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file: target }),
          });
          toast(`Playing mapping for card ${card}`);
        } catch (err) {
          toast(`Play failed: ${err.message}`, 'error');
        }
      });
      actionsTd.appendChild(playBtn);

      const delBtn = document.createElement('button');
      delBtn.textContent = 'Delete';
      delBtn.className = 'danger';
      delBtn.addEventListener('click', async () => {
        try {
          const payload = await apiFetch('/api/mappings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ card, target: '' }),
          });
          state.mappings = payload.mappings || {};
          renderMappings();
          renderLibrary();
          toast(`Mapping removed for ${card}`);
        } catch (err) {
          toast(`Delete failed: ${err.message}`, 'error');
        }
      });
      actionsTd.appendChild(delBtn);

      tr.appendChild(actionsTd);
      tbody.appendChild(tr);
    }
  }

  async function loadLibrary() {
    const query = encodeURIComponent(($('lib-search').value || '').trim());
    const kind = encodeURIComponent(($('lib-kind').value || 'all').trim());
    const payload = await apiFetch(`/api/files?q=${query}&kind=${kind}`);
    state.entries = payload.entries || [];
    renderLibrary();
    return payload;
  }

  async function loadMappings() {
    const payload = await apiFetch('/api/mappings');
    state.mappings = payload.mappings || {};
    renderMappings();
    renderLibrary();
    return payload;
  }

  async function saveMapping(remove = false) {
    const card = ($('map-card').value || '').trim();
    const target = remove ? '' : ($('map-target').value || '').trim().replace(/^\/+/, '');
    if (!card) {
      toast('Card ID is required', 'warning');
      return;
    }
    if (!remove && !target) {
      toast('Target path is required', 'warning');
      return;
    }

    const payload = await apiFetch('/api/mappings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ card, target }),
    });

    state.mappings = payload.mappings || {};
    renderMappings();
    renderLibrary();
    toast(remove ? `Mapping removed for ${card}` : `Mapping saved for ${card}`);
  }

  function updateUploadStatus() {
    const count = state.pendingUploads.length;
    const totalBytes = state.pendingUploads.reduce((sum, item) => sum + (item.file.size || 0), 0);
    const mb = (totalBytes / (1024 * 1024)).toFixed(1);
    setText('upload-status', count ? `${count} file(s), ${mb} MiB queued` : 'idle');
  }

  function queueFiles(fileList) {
    if (!fileList || !fileList.length) {
      return;
    }

    for (const file of fileList) {
      const rel = file.webkitRelativePath && file.webkitRelativePath.trim() ? file.webkitRelativePath : file.name;
      state.pendingUploads.push({ file, relpath: rel });
    }

    updateUploadStatus();
    toast(`Queued ${fileList.length} file(s)`);
  }

  async function uploadPending() {
    if (!state.pendingUploads.length) {
      toast('No files queued', 'warning');
      return;
    }

    const progress = $('upload-progress');
    if (progress) {
      progress.value = 0;
    }

    const formData = new FormData();
    formData.append('dir', ($('target-dir').value || '').trim());
    for (const item of state.pendingUploads) {
      formData.append('files', item.file, item.file.name);
      formData.append('relpath', item.relpath);
    }

    await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/upload');
      xhr.responseType = 'json';

      xhr.upload.addEventListener('progress', (ev) => {
        if (!ev.lengthComputable || !progress) {
          return;
        }
        progress.value = Math.round((ev.loaded / ev.total) * 100);
      });

      xhr.addEventListener('load', () => {
        const payload = xhr.response || {};
        if (xhr.status >= 200 && xhr.status < 300 && payload.ok) {
          resolve(payload);
          return;
        }
        reject(new Error(payload.error || `${xhr.status} ${xhr.statusText}`));
      });

      xhr.addEventListener('error', () => {
        reject(new Error('network error'));
      });

      xhr.send(formData);
    });

    const uploadedCount = state.pendingUploads.length;
    state.pendingUploads = [];
    $('pick-files').value = '';
    $('pick-folder').value = '';
    if (progress) {
      progress.value = 100;
    }
    updateUploadStatus();
    toast(`Uploaded ${uploadedCount} file(s)`);
    await loadLibrary();
  }

  async function postAction(action) {
    await apiFetch('/api/player/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
  }

  function startPollingFallback() {
    if (state.pollTimer) {
      return;
    }
    state.pollTimer = window.setInterval(async () => {
      try {
        const payload = await apiFetch('/api/status');
        applySnapshot(payload);
      } catch (_err) {
        // keep retrying quietly
      }
    }, 3000);
  }

  function connectStream() {
    if (!window.EventSource) {
      startPollingFallback();
      return;
    }

    const sse = new EventSource('/api/stream');
    state.sse = sse;

    sse.addEventListener('status', (event) => {
      try {
        const payload = JSON.parse(event.data);
        applySnapshot(payload);
      } catch (_err) {
        // ignore malformed packets
      }
    });

    sse.addEventListener('error', () => {
      sse.close();
      state.sse = null;
      startPollingFallback();
      window.setTimeout(() => {
        connectStream();
      }, 5000);
    });
  }

  function bindTabs() {
    document.querySelectorAll('.tab').forEach((btn) => {
      btn.addEventListener('click', () => activateTab(btn.dataset.tab));
    });
  }

  function bindControls() {
    document.querySelectorAll('[data-action]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const action = btn.dataset.action;
        try {
          await postAction(action);
        } catch (err) {
          toast(`Action failed: ${err.message}`, 'error');
        }
      });
    });

    $('quick-play-btn').addEventListener('click', async () => {
      const path = ($('quick-play-path').value || '').trim();
      if (!path) {
        toast('Provide a path to play', 'warning');
        return;
      }
      try {
        await apiFetch('/api/play', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file: path }),
        });
      } catch (err) {
        toast(`Play failed: ${err.message}`, 'error');
      }
    });

    $('quick-stop-btn').addEventListener('click', async () => {
      try {
        await apiFetch('/api/stop', { method: 'POST' });
      } catch (err) {
        toast(`Stop failed: ${err.message}`, 'error');
      }
    });
  }

  function bindLibrary() {
    $('lib-refresh').addEventListener('click', async () => {
      try {
        await loadLibrary();
      } catch (err) {
        toast(`Refresh failed: ${err.message}`, 'error');
      }
    });

    $('lib-kind').addEventListener('change', async () => {
      try {
        await loadLibrary();
      } catch (err) {
        toast(`Filter failed: ${err.message}`, 'error');
      }
    });

    $('lib-search').addEventListener('keydown', async (event) => {
      if (event.key !== 'Enter') {
        return;
      }
      try {
        await loadLibrary();
      } catch (err) {
        toast(`Search failed: ${err.message}`, 'error');
      }
    });

    $('mkdir-btn').addEventListener('click', async () => {
      const path = ($('target-dir').value || '').trim();
      if (!path) {
        toast('Provide a folder path first', 'warning');
        return;
      }
      try {
        await apiFetch('/api/mkdir', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path }),
        });
        toast(`Created ${path}`);
        await loadLibrary();
      } catch (err) {
        toast(`Create dir failed: ${err.message}`, 'error');
      }
    });

    $('pick-files').addEventListener('change', (event) => {
      queueFiles(event.target.files);
    });

    $('pick-folder').addEventListener('change', (event) => {
      queueFiles(event.target.files);
    });

    $('upload-btn').addEventListener('click', async () => {
      try {
        await uploadPending();
      } catch (err) {
        toast(`Upload failed: ${err.message}`, 'error');
        updateUploadStatus();
      }
    });

    const dropZone = $('drop-zone');
    ['dragenter', 'dragover'].forEach((evtName) => {
      dropZone.addEventListener(evtName, (event) => {
        event.preventDefault();
        event.stopPropagation();
        dropZone.classList.add('drag');
      });
    });

    ['dragleave', 'drop'].forEach((evtName) => {
      dropZone.addEventListener(evtName, (event) => {
        event.preventDefault();
        event.stopPropagation();
        dropZone.classList.remove('drag');
      });
    });

    dropZone.addEventListener('drop', (event) => {
      const files = event.dataTransfer && event.dataTransfer.files;
      if (files && files.length) {
        queueFiles(files);
      }
    });
  }

  function bindCards() {
    $('map-from-selected').addEventListener('click', () => {
      if (!state.selectedPath) {
        toast('Select an item in Library first', 'warning');
        return;
      }
      $('map-target').value = state.selectedPath;
      toast('Mapped target from selected item');
    });

    $('map-save').addEventListener('click', async () => {
      try {
        await saveMapping(false);
      } catch (err) {
        toast(`Save mapping failed: ${err.message}`, 'error');
      }
    });

    $('map-delete').addEventListener('click', async () => {
      try {
        await saveMapping(true);
      } catch (err) {
        toast(`Delete mapping failed: ${err.message}`, 'error');
      }
    });

    $('map-refresh').addEventListener('click', async () => {
      try {
        await loadMappings();
      } catch (err) {
        toast(`Refresh mapping failed: ${err.message}`, 'error');
      }
    });
  }

  function bindSettings() {
    $('led-speed').addEventListener('input', (event) => {
      setText('led-speed-value', event.target.value);
    });

    $('save-settings').addEventListener('click', async () => {
      try {
        const value = Number($('led-speed').value || 25);
        const payload = await apiFetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rotary_led_step_ms: value }),
        });
        if (payload.settings && payload.settings.rotary_led_step_ms != null) {
          setText('led-speed-value', payload.settings.rotary_led_step_ms);
        }
        toast('Settings saved');
      } catch (err) {
        toast(`Save settings failed: ${err.message}`, 'error');
      }
    });
  }

  function bindEventsPanel() {
    $('events-clear-view').addEventListener('click', () => {
      state.events = [];
      $('events-log').textContent = '';
      toast('Event panel cleared');
    });
  }

  async function init() {
    bindTabs();
    bindControls();
    bindLibrary();
    bindCards();
    bindSettings();
    bindEventsPanel();

    updateUploadStatus();

    try {
      const [statusPayload] = await Promise.all([
        apiFetch('/api/status'),
        loadMappings(),
        loadLibrary(),
      ]);
      applySnapshot(statusPayload);
    } catch (err) {
      toast(`Initial load failed: ${err.message}`, 'error');
    }

    connectStream();
  }

  init();
})();
