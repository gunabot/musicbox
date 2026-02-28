(() => {
  const STORAGE_KEY = 'musicbox-ui-v2';

  const state = {
    snapshot: null,
    spotify: null,
    mappings: {},
    entries: [],
    selectedPath: '',
    currentDir: '',
    treeNodes: {},
    expandedDirs: new Set(['']),
    events: [],
    lastEventId: 0,
    pendingUploads: [],
    lastAutoCard: '',
    sse: null,
    pollTimer: null,
    activeTab: 'now',
    libKind: 'all',
    libMapped: 'all',
    libSearch: '',
  };

  const $ = (id) => document.getElementById(id);

  function normalizeRel(path) {
    return String(path || '').trim().replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+$/, '');
  }

  function parentPath(path) {
    const norm = normalizeRel(path);
    if (!norm.includes('/')) {
      return '';
    }
    return norm.split('/').slice(0, -1).join('/');
  }

  function basename(path) {
    const norm = normalizeRel(path);
    if (!norm) {
      return '';
    }
    const parts = norm.split('/');
    return parts[parts.length - 1];
  }

  function clampInt(value, min, max, fallback) {
    const parsed = Number.parseInt(String(value ?? ''), 10);
    if (Number.isNaN(parsed)) {
      return fallback;
    }
    return Math.max(min, Math.min(max, parsed));
  }

  function normalizeMappingEntry(value) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const type = String(value.type || 'local').trim().toLowerCase() || 'local';
      const target = String(value.target || '').trim();
      return { type, target };
    }
    return { type: 'local', target: normalizeRel(value || '') };
  }

  function ancestors(path) {
    const norm = normalizeRel(path);
    if (!norm) {
      return [''];
    }
    const chunks = norm.split('/');
    const all = [''];
    let current = '';
    for (const chunk of chunks) {
      current = current ? `${current}/${chunk}` : chunk;
      all.push(current);
    }
    return all;
  }

  function setText(id, value) {
    const el = $(id);
    if (el) {
      el.textContent = value == null || value === '' ? '-' : String(value);
    }
  }

  function formatBytes(bytes) {
    if (bytes == null || Number.isNaN(Number(bytes))) {
      return '-';
    }
    const value = Number(bytes);
    if (value < 1024) {
      return `${value} B`;
    }
    const units = ['KiB', 'MiB', 'GiB', 'TiB'];
    let size = value;
    let unitIdx = -1;
    while (size >= 1024 && unitIdx < units.length - 1) {
      size /= 1024;
      unitIdx += 1;
    }
    return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unitIdx]}`;
  }

  function formatUptime(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) {
      return '-';
    }
    let remaining = Math.max(0, Math.floor(Number(seconds)));
    const days = Math.floor(remaining / 86400);
    remaining %= 86400;
    const hours = Math.floor(remaining / 3600);
    remaining %= 3600;
    const minutes = Math.floor(remaining / 60);

    const parts = [];
    if (days) {
      parts.push(`${days}d`);
    }
    if (hours || days) {
      parts.push(`${hours}h`);
    }
    parts.push(`${minutes}m`);
    return parts.join(' ');
  }

  function formatDateTime(epochSeconds) {
    if (!epochSeconds || Number.isNaN(Number(epochSeconds))) {
      return '-';
    }
    const date = new Date(Number(epochSeconds) * 1000);
    if (Number.isNaN(date.getTime())) {
      return '-';
    }
    return date.toLocaleString();
  }

  function loadUiPrefs() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return;
      }
      const prefs = JSON.parse(raw);
      state.activeTab = ['now', 'library', 'cards', 'hardware', 'settings', 'events'].includes(prefs.activeTab)
        ? prefs.activeTab
        : 'now';
      state.currentDir = normalizeRel(prefs.currentDir);
      state.selectedPath = normalizeRel(prefs.selectedPath);
      state.libKind = ['all', 'files', 'dirs'].includes(prefs.libKind) ? prefs.libKind : 'all';
      state.libMapped = ['all', 'mapped', 'unmapped'].includes(prefs.libMapped) ? prefs.libMapped : 'all';
      state.libSearch = String(prefs.libSearch || '');

      const expanded = Array.isArray(prefs.expandedDirs) ? prefs.expandedDirs.map(normalizeRel) : [];
      state.expandedDirs = new Set(['', ...expanded]);
    } catch (_err) {
      // ignore bad local storage
    }
  }

  function saveUiPrefs() {
    const payload = {
      activeTab: state.activeTab,
      currentDir: state.currentDir,
      selectedPath: state.selectedPath,
      libKind: $('lib-kind') ? $('lib-kind').value : state.libKind,
      libMapped: $('lib-mapped') ? $('lib-mapped').value : state.libMapped,
      libSearch: $('lib-search') ? $('lib-search').value : state.libSearch,
      expandedDirs: Array.from(state.expandedDirs.values()),
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch (_err) {
      // ignore storage issues
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

    if (state.events.length > 700) {
      state.events = state.events.slice(-700);
    }

    const logEl = $('events-log');
    if (logEl) {
      logEl.textContent = state.events.join('\n');
      logEl.scrollTop = logEl.scrollHeight;
    }
  }

  function setBatteryBadge(percent) {
    const badge = $('badge-battery');
    if (!badge) {
      return;
    }
    badge.classList.remove('good', 'warn');
    if (percent == null) {
      badge.textContent = '-';
      return;
    }
    badge.textContent = `${Number(percent).toFixed(0)}%`;
    if (percent <= 20) {
      badge.classList.add('warn');
    } else {
      badge.classList.add('good');
    }
  }

  function setDisabled(id, disabled, reason = '') {
    const el = $(id);
    if (!el) {
      return;
    }
    el.disabled = Boolean(disabled);
    el.title = disabled ? reason : '';
  }

  function spotifyCapabilities(spotify) {
    const status = spotify || {};
    const user = status.user || {};
    const product = String(user.product || '').trim().toLowerCase();
    const configured = Boolean(status.client_id_set || status.configured || status.client_id);
    const connected = Boolean(status.connected);
    const accessValid = Boolean(status.access_valid);
    const hasStreamingScope = Boolean(status.has_streaming_scope);
    const premiumKnown = Boolean(product);
    const isPremium = product === 'premium';

    let guidance = 'Set Spotify client ID to begin.';
    if (!configured) {
      guidance = 'Step 1: enter Spotify client ID, then click Save Spotify Config.';
    } else if (!connected) {
      guidance = 'Step 2: click Connect Spotify and approve access in the popup.';
    } else if (!hasStreamingScope) {
      guidance = 'Reconnect Spotify to grant the streaming scope.';
    } else if (premiumKnown && !isPremium) {
      guidance = 'Spotify Premium is required for transfer/capture playback.';
    } else if (!accessValid) {
      guidance = 'Spotify token is refreshing. Please wait a moment.';
    } else {
      guidance = 'Ready: first play captures into cache, then playback uses local library.';
    }

    return {
      configured,
      connected,
      accessValid,
      hasStreamingScope,
      premiumKnown,
      isPremium,
      ready: configured && connected && hasStreamingScope && accessValid && (!premiumKnown || isPremium),
      guidance,
    };
  }

  function renderSpotifyStatus(spotify) {
    const status = spotify || {};
    const user = status.user || {};
    const caps = spotifyCapabilities(status);

    setText('spotify-status', caps.connected ? (caps.accessValid ? 'connected' : 'refreshing') : 'not connected');
    setText('spotify-user', user.display_name || user.id || '-');
    setText('spotify-product', user.product || '-');
    setText('spotify-device', status.device_name || '-');
    setText('spotify-expiry', formatDateTime(status.expires_at));
    setText('spotify-streaming', caps.hasStreamingScope ? 'yes' : 'missing');
    setText('spotify-scope', status.scope || '-');
    setText('spotify-guidance', caps.guidance);

    const clientInput = $('spotify-client-id');
    if (clientInput && status.client_id && (!clientInput.value || clientInput.dataset.autofilled === '1')) {
      clientInput.value = String(status.client_id);
      clientInput.dataset.autofilled = '1';
    }

    const deviceInput = $('spotify-device-name');
    if (deviceInput && status.device_name && (!deviceInput.value || deviceInput.dataset.autofilled === '1')) {
      deviceInput.value = String(status.device_name);
      deviceInput.dataset.autofilled = '1';
    }

    const connectBtn = $('spotify-connect');
    if (connectBtn) {
      connectBtn.textContent = caps.connected ? 'Reconnect Spotify' : 'Connect Spotify';
    }

    const hasClientDraft = Boolean(clientInput && String(clientInput.value || '').trim());
    setDisabled('spotify-connect', !(caps.configured || hasClientDraft), 'Set Spotify client ID first');
    setDisabled('spotify-disconnect', !caps.connected, 'Spotify is not connected');
    setDisabled('spotify-cache-btn', !caps.ready, 'Connect Spotify with streaming scope first');
    setDisabled('spotify-cache-uri', !caps.connected, 'Connect Spotify first');
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
    setBatteryBadge(health.battery_percent);

    setText('now-file', player.file || 'No active track');
    setText('now-source', `Source: ${player.source || 'local'}`);
    setText('now-spotify-uri', player.spotify_uri ? `Spotify: ${player.spotify_uri}` : 'Spotify: -');
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

    setText('health-ups', health.ups_connected ? 'connected' : 'not detected');
    setText('health-battery', health.battery_percent == null ? '-' : `${Number(health.battery_percent).toFixed(1)}%`);
    setText('health-battery-voltage', health.battery_voltage == null ? '-' : `${Number(health.battery_voltage).toFixed(3)} V`);
    setText('health-battery-current', health.battery_current_ma == null ? '-' : `${Number(health.battery_current_ma).toFixed(1)} mA`);
    setText('health-battery-power', health.battery_power_w == null ? '-' : `${Number(health.battery_power_w).toFixed(3)} W`);
    setText('health-battery-charging', health.battery_charging == null ? '-' : (health.battery_charging ? 'yes' : 'no'));

    setText('health-cpu-temp', health.cpu_temp_c == null ? '-' : `${Number(health.cpu_temp_c).toFixed(1)} C`);
    setText('health-uptime', formatUptime(health.uptime_s));

    if (health.load_1 == null || health.load_5 == null || health.load_15 == null) {
      setText('health-load', '-');
    } else {
      setText('health-load', `${health.load_1} / ${health.load_5} / ${health.load_15}`);
    }

    if (health.disk_total_bytes == null || health.disk_free_bytes == null || health.disk_used_pct == null) {
      setText('health-disk', '-');
    } else {
      const free = formatBytes(health.disk_free_bytes);
      const total = formatBytes(health.disk_total_bytes);
      setText('health-disk', `${free} free / ${total} (${health.disk_used_pct}% used)`);
    }

    const speed = snapshot.settings && snapshot.settings.rotary_led_step_ms;
    const ledInput = $('led-speed');
    if (speed != null && ledInput && document.activeElement !== ledInput) {
      ledInput.value = String(speed);
    }

    const volumePerTurn = snapshot.settings && snapshot.settings.rotary_volume_per_turn;
    const volumeInput = $('rotary-volume-per-turn');
    if (volumePerTurn != null && volumeInput && document.activeElement !== volumeInput) {
      volumeInput.value = String(volumePerTurn);
    }

    if (snapshot.last_card) {
      const cardInput = $('map-card');
      if (cardInput && (!cardInput.value || cardInput.value === state.lastAutoCard)) {
        cardInput.value = snapshot.last_card;
        state.lastAutoCard = snapshot.last_card;
      }
    }

    if (snapshot.spotify) {
      state.spotify = snapshot.spotify;
      renderSpotifyStatus(snapshot.spotify);
    }

    appendEvents(snapshot.events || []);
  }

  function applySnapshot(payload) {
    state.snapshot = payload;
    if (payload && payload.spotify) {
      state.spotify = payload.spotify;
    }
    renderStatus(payload);
  }

  function activateTab(tabName, persist = true) {
    state.activeTab = tabName;
    document.querySelectorAll('.tab').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    document.querySelectorAll('.panel').forEach((panel) => {
      panel.classList.toggle('active', panel.id === `tab-${tabName}`);
    });
    if (persist) {
      saveUiPrefs();
    }
  }

  function setSelectedPath(path) {
    state.selectedPath = normalizeRel(path);
    setText('map-selected', state.selectedPath || 'No library item selected');
    if (state.selectedPath) {
      $('move-dst').value = basename(state.selectedPath);
    }
    renderLibrary();
    saveUiPrefs();
  }

  async function loadTreeNode(path = '') {
    const rel = normalizeRel(path);
    const payload = await apiFetch(`/api/tree?path=${encodeURIComponent(rel)}`);
    state.treeNodes[rel] = payload.node;
    return payload.node;
  }

  async function ensureTreePathLoaded(path) {
    const chain = ancestors(path);
    if (!state.treeNodes['']) {
      await loadTreeNode('');
    }
    for (const item of chain) {
      state.expandedDirs.add(item);
      if (item && !state.treeNodes[item]) {
        try {
          await loadTreeNode(item);
        } catch (_err) {
          // ignore missing path
        }
      }
    }
  }

  async function refreshTree() {
    state.treeNodes = {};
    await loadTreeNode('');
    await ensureTreePathLoaded(state.currentDir);
    renderTree();
    renderBreadcrumb();
  }

  function renderBreadcrumb() {
    const el = $('lib-breadcrumb');
    if (!el) {
      return;
    }
    el.textContent = '';

    const rootBtn = document.createElement('button');
    rootBtn.className = 'crumb';
    rootBtn.textContent = '/media';
    rootBtn.addEventListener('click', () => {
      void setCurrentDir('');
    });
    el.appendChild(rootBtn);

    let current = '';
    for (const segment of normalizeRel(state.currentDir).split('/').filter(Boolean)) {
      current = current ? `${current}/${segment}` : segment;
      const segBtn = document.createElement('button');
      segBtn.className = 'crumb';
      segBtn.textContent = segment;
      const target = current;
      segBtn.addEventListener('click', () => {
        void setCurrentDir(target);
      });
      el.appendChild(segBtn);
    }
  }

  function renderTreeChildren(parentPath, node, depth) {
    const frag = document.createDocumentFragment();
    const children = Array.isArray(node.children) ? node.children : [];
    const dirs = children.filter((entry) => entry.type === 'dir');

    for (const dir of dirs) {
      const rel = normalizeRel(dir.path);
      const row = document.createElement('div');
      row.className = 'tree-node';

      const line = document.createElement('div');
      line.className = 'tree-row';

      for (let i = 0; i < depth; i += 1) {
        const spacer = document.createElement('span');
        spacer.className = 'tree-depth';
        line.appendChild(spacer);
      }

      const toggle = document.createElement('button');
      toggle.className = 'tree-toggle';
      const expanded = state.expandedDirs.has(rel);
      const hasChildren = Boolean(dir.has_children);
      toggle.textContent = hasChildren ? (expanded ? '▾' : '▸') : '•';
      toggle.disabled = !hasChildren;
      toggle.addEventListener('click', async (event) => {
        event.stopPropagation();
        if (!hasChildren) {
          return;
        }
        if (state.expandedDirs.has(rel)) {
          state.expandedDirs.delete(rel);
          renderTree();
          saveUiPrefs();
          return;
        }
        state.expandedDirs.add(rel);
        try {
          if (!state.treeNodes[rel]) {
            await loadTreeNode(rel);
          }
          renderTree();
          saveUiPrefs();
        } catch (err) {
          toast(`Failed to expand folder: ${err.message}`, 'error');
        }
      });
      line.appendChild(toggle);

      const label = document.createElement('button');
      label.className = 'tree-label';
      if (rel === state.currentDir) {
        label.classList.add('selected');
      }
      label.textContent = dir.name;
      label.addEventListener('click', () => {
        void setCurrentDir(rel);
      });
      line.appendChild(label);

      row.appendChild(line);

      if (expanded && state.treeNodes[rel]) {
        row.appendChild(renderTreeChildren(rel, state.treeNodes[rel], depth + 1));
      }

      frag.appendChild(row);
    }

    return frag;
  }

  function renderTree() {
    const root = $('library-tree');
    if (!root) {
      return;
    }

    root.textContent = '';
    const rootNode = state.treeNodes[''];
    if (!rootNode) {
      const btn = document.createElement('button');
      btn.textContent = 'Load folders';
      btn.addEventListener('click', async () => {
        try {
          await loadTreeNode('');
          renderTree();
        } catch (err) {
          toast(`Tree load failed: ${err.message}`, 'error');
        }
      });
      root.appendChild(btn);
      return;
    }

    root.appendChild(renderTreeChildren('', rootNode, 0));
  }

  function mappedCardsByPath() {
    const map = {};
    for (const [card, rawMapping] of Object.entries(state.mappings || {})) {
      const mapping = normalizeMappingEntry(rawMapping);
      if (mapping.type !== 'local' || !mapping.target) {
        continue;
      }
      if (!map[mapping.target]) {
        map[mapping.target] = [];
      }
      map[mapping.target].push(card);
    }
    return map;
  }

  async function confirmDelete(path) {
    const payload = await apiFetch(`/api/pathinfo?path=${encodeURIComponent(path)}`);
    const info = payload.info || {};
    if (!info.exists) {
      return false;
    }

    if (info.type === 'dir') {
      const size = formatBytes(info.size_bytes);
      return window.confirm(
        `Delete folder "${path}"?\n\nContains ${info.dir_count || 0} subfolder(s), ${info.file_count || 0} file(s), total ${size}.`
      );
    }

    return window.confirm(`Delete file "${path}" (${formatBytes(info.size_bytes)})?`);
  }

  async function deleteEntry(path) {
    const ok = await confirmDelete(path);
    if (!ok) {
      return;
    }

    await apiFetch('/api/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });

    toast(`Deleted ${path}`);
    if (state.selectedPath === path) {
      setSelectedPath('');
    }

    if (state.currentDir === path || state.currentDir.startsWith(`${path}/`)) {
      state.currentDir = parentPath(path);
    }

    await refreshTree();
    await loadLibrary();
  }

  function renderLibrary() {
    const tbody = $('library-body');
    if (!tbody) {
      return;
    }
    tbody.textContent = '';

    const pathToCards = mappedCardsByPath();
    const mappedFilter = $('lib-mapped') ? $('lib-mapped').value : 'all';

    for (const entry of state.entries) {
      const mappedCards = pathToCards[entry.path] || [];
      if (mappedFilter === 'mapped' && mappedCards.length === 0) {
        continue;
      }
      if (mappedFilter === 'unmapped' && mappedCards.length > 0) {
        continue;
      }

      const tr = document.createElement('tr');
      if (entry.path === state.selectedPath) {
        tr.classList.add('selected');
      }

      const typeTd = document.createElement('td');
      typeTd.textContent = entry.type;
      tr.appendChild(typeTd);

      const nameTd = document.createElement('td');
      nameTd.textContent = entry.name;
      tr.appendChild(nameTd);

      const pathTd = document.createElement('td');
      pathTd.textContent = entry.path;
      tr.appendChild(pathTd);

      const mapTd = document.createElement('td');
      mapTd.textContent = mappedCards.join(', ') || '-';
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

      if (entry.type === 'dir') {
        const openBtn = document.createElement('button');
        openBtn.textContent = 'Open';
        openBtn.addEventListener('click', () => {
          void setCurrentDir(entry.path);
        });
        actionsTd.appendChild(openBtn);
      }

      const selectBtn = document.createElement('button');
      selectBtn.textContent = 'Select';
      selectBtn.addEventListener('click', () => {
        setSelectedPath(entry.path);
      });
      actionsTd.appendChild(selectBtn);

      const mapBtn = document.createElement('button');
      mapBtn.textContent = 'Map';
      mapBtn.addEventListener('click', () => {
        setSelectedPath(entry.path);
        $('map-type').value = 'local';
        $('map-target').value = entry.path;
        activateTab('cards');
      });
      actionsTd.appendChild(mapBtn);

      const delBtn = document.createElement('button');
      delBtn.textContent = 'Delete';
      delBtn.className = 'danger';
      delBtn.addEventListener('click', async () => {
        try {
          await deleteEntry(entry.path);
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
    const query = ($('lib-search').value || '').trim();
    const kind = ($('lib-kind').value || 'all').trim();
    const recursive = query ? '1' : '0';

    try {
      const payload = await apiFetch(
        `/api/files?path=${encodeURIComponent(state.currentDir)}&q=${encodeURIComponent(query)}&kind=${encodeURIComponent(kind)}&recursive=${recursive}`
      );
      state.entries = payload.entries || [];
      state.libSearch = query;
      state.libKind = kind;
      renderLibrary();
      saveUiPrefs();
      return payload;
    } catch (err) {
      if (state.currentDir) {
        state.currentDir = '';
        $('target-dir').value = '';
        await refreshTree();
        return loadLibrary();
      }
      throw err;
    }
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
    const mappingType = (($('map-type').value || 'local').trim().toLowerCase() || 'local');
    const rawTarget = ($('map-target').value || '').trim();
    const target = remove ? '' : (mappingType === 'local' ? normalizeRel(rawTarget) : rawTarget);
    if (!card) {
      toast('Card ID is required', 'warning');
      return;
    }
    if (!remove && !target) {
      toast('Target is required', 'warning');
      return;
    }

    const payload = await apiFetch('/api/mappings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ card, type: mappingType, target }),
    });

    state.mappings = payload.mappings || {};
    renderMappings();
    renderLibrary();
    toast(remove ? `Mapping removed for ${card}` : `Mapping saved for ${card}`);
  }

  function renderMappings() {
    const tbody = $('mappings-body');
    if (!tbody) {
      return;
    }
    tbody.textContent = '';

    const rows = Object.entries(state.mappings || {}).sort((a, b) => a[0].localeCompare(b[0]));
    for (const [card, rawMapping] of rows) {
      const mapping = normalizeMappingEntry(rawMapping);
      const tr = document.createElement('tr');

      const cardTd = document.createElement('td');
      cardTd.textContent = card;
      tr.appendChild(cardTd);

      const typeTd = document.createElement('td');
      typeTd.textContent = mapping.type;
      tr.appendChild(typeTd);

      const targetTd = document.createElement('td');
      targetTd.textContent = mapping.target;
      tr.appendChild(targetTd);

      const actionsTd = document.createElement('td');
      actionsTd.className = 'actions';

      const useBtn = document.createElement('button');
      useBtn.textContent = 'Use';
      useBtn.addEventListener('click', () => {
        $('map-card').value = card;
        $('map-type').value = mapping.type;
        $('map-target').value = mapping.target;
        if (mapping.type === 'local') {
          setSelectedPath(mapping.target);
        } else if (mapping.type === 'spotify') {
          const cacheInput = $('spotify-cache-uri');
          if (cacheInput) {
            cacheInput.value = mapping.target;
          }
        }
        activateTab('cards');
      });
      actionsTd.appendChild(useBtn);

      const playBtn = document.createElement('button');
      playBtn.textContent = 'Play';
      playBtn.addEventListener('click', async () => {
        try {
          const payload = mapping.type === 'spotify'
            ? { type: 'spotify', target: mapping.target }
            : { file: mapping.target };
          await apiFetch('/api/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
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

  function updateUploadStatus() {
    const count = state.pendingUploads.length;
    const totalBytes = state.pendingUploads.reduce((sum, item) => sum + (item.file.size || 0), 0);
    const queued = count ? `${count} file(s), ${formatBytes(totalBytes)} queued` : 'idle';
    setText('upload-status', queued);
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
    const targetDir = normalizeRel(($('target-dir').value || '').trim()) || state.currentDir;
    formData.append('dir', targetDir);
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
    await refreshTree();
    await loadLibrary();
  }

  async function postAction(action) {
    await apiFetch('/api/player/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
  }

  async function setCurrentDir(path) {
    state.currentDir = normalizeRel(path);
    state.expandedDirs = new Set([...state.expandedDirs, ...ancestors(state.currentDir)]);
    $('target-dir').value = state.currentDir;
    await ensureTreePathLoaded(state.currentDir);
    renderTree();
    renderBreadcrumb();
    await loadLibrary();
    saveUiPrefs();
  }

  async function moveSelected() {
    if (!state.selectedPath) {
      toast('Select an item first', 'warning');
      return;
    }

    const raw = ($('move-dst').value || '').trim();
    if (!raw) {
      toast('Enter destination path or new name', 'warning');
      return;
    }

    let dst = normalizeRel(raw);
    if (!dst.includes('/')) {
      const parent = parentPath(state.selectedPath);
      dst = parent ? `${parent}/${dst}` : dst;
    }

    await apiFetch('/api/move', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ src: state.selectedPath, dst }),
    });

    toast(`Moved to ${dst}`);
    state.selectedPath = dst;
    await refreshTree();
    await loadLibrary();
    setSelectedPath(dst);
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
      const path = normalizeRel(($('quick-play-path').value || '').trim());
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
        await refreshTree();
        await loadLibrary();
      } catch (err) {
        toast(`Refresh failed: ${err.message}`, 'error');
      }
    });

    $('lib-kind').value = state.libKind;
    $('lib-mapped').value = state.libMapped;
    $('lib-search').value = state.libSearch;

    $('lib-kind').addEventListener('change', async () => {
      try {
        await loadLibrary();
      } catch (err) {
        toast(`Filter failed: ${err.message}`, 'error');
      }
    });

    $('lib-mapped').addEventListener('change', () => {
      renderLibrary();
      saveUiPrefs();
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
      const path = normalizeRel(($('target-dir').value || '').trim());
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
        await refreshTree();
        await loadLibrary();
      } catch (err) {
        toast(`Create dir failed: ${err.message}`, 'error');
      }
    });

    $('move-btn').addEventListener('click', async () => {
      try {
        await moveSelected();
      } catch (err) {
        toast(`Move failed: ${err.message}`, 'error');
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

    $('tree-root-btn').addEventListener('click', async () => {
      try {
        await setCurrentDir('');
      } catch (err) {
        toast(`Failed to jump to root: ${err.message}`, 'error');
      }
    });

    $('tree-collapse-btn').addEventListener('click', () => {
      state.expandedDirs = new Set(['']);
      renderTree();
      saveUiPrefs();
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
    const mapType = $('map-type');
    const mapTarget = $('map-target');

    const syncMapTypeUi = () => {
      const kind = String(mapType.value || 'local').trim().toLowerCase();
      if (kind === 'spotify') {
        mapTarget.placeholder = 'spotify:playlist:... or https://open.spotify.com/...';
      } else {
        mapTarget.placeholder = 'target file/folder under /media';
      }
    };

    mapType.addEventListener('change', syncMapTypeUi);
    syncMapTypeUi();

    $('map-from-selected').addEventListener('click', () => {
      if (!state.selectedPath) {
        toast('Select an item in Library first', 'warning');
        return;
      }
      $('map-type').value = 'local';
      $('map-target').value = state.selectedPath;
      toast('Mapped target from selected item');
    });

    $('map-last-scan').addEventListener('click', async () => {
      const lastCard = state.snapshot && state.snapshot.last_card;
      if (!lastCard) {
        toast('No scanned card yet', 'warning');
        return;
      }
      if (!state.selectedPath) {
        toast('Select a library item first', 'warning');
        return;
      }
      $('map-card').value = String(lastCard);
      $('map-type').value = 'local';
      $('map-target').value = state.selectedPath;
      try {
        await saveMapping(false);
      } catch (err) {
        toast(`Save mapping failed: ${err.message}`, 'error');
      }
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

  async function refreshSpotifyStatus() {
    const payload = await apiFetch('/api/spotify/status');
    state.spotify = payload.spotify || {};
    renderSpotifyStatus(state.spotify);
    return payload;
  }

  async function saveSpotifyConfig() {
    const clientId = ($('spotify-client-id').value || '').trim();
    const deviceName = ($('spotify-device-name').value || '').trim();
    const existingClientId = state.spotify && state.spotify.client_id ? String(state.spotify.client_id).trim() : '';
    const effectiveClientId = clientId || existingClientId;
    if (!effectiveClientId) {
      toast('Spotify client id is required', 'warning');
      return false;
    }
    const payload = await apiFetch('/api/spotify/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: effectiveClientId, device_name: deviceName }),
    });
    state.spotify = payload.spotify || {};
    renderSpotifyStatus(state.spotify);
    toast('Spotify config saved');
    return true;
  }

  async function connectSpotify() {
    const payload = await apiFetch('/api/spotify/login/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const authUrl = payload.auth_url;
    if (!authUrl) {
      throw new Error('missing spotify auth URL');
    }

    const popup = window.open(authUrl, 'spotify-auth', 'width=560,height=760');
    if (!popup) {
      toast('Popup blocked. Open this URL manually from browser console log.', 'warning');
      // eslint-disable-next-line no-console
      console.log('Spotify auth URL:', authUrl);
      return;
    }

    toast('Complete Spotify login in the popup window');
    const started = Date.now();
    let finished = false;
    const finish = (message, level = 'info') => {
      if (finished) {
        return;
      }
      finished = true;
      window.clearInterval(timer);
      if (message) {
        toast(message, level);
      }
    };

    const timer = window.setInterval(async () => {
      const elapsed = Date.now() - started;
      let latest = state.spotify || {};
      try {
        const refreshed = await refreshSpotifyStatus();
        latest = refreshed.spotify || latest;
      } catch (_err) {
        // keep polling silently
      }

      const caps = spotifyCapabilities(latest);
      if (caps.connected && caps.hasStreamingScope) {
        finish('Spotify connected');
        return;
      }

      if (elapsed > 180000) {
        finish('Spotify login timed out', 'warning');
        return;
      }

      if (popup.closed) {
        finish(caps.connected ? 'Spotify connected' : 'Spotify popup closed before login finished', caps.connected ? 'info' : 'warning');
      }
    }, 3000);
  }

  async function disconnectSpotify() {
    const payload = await apiFetch('/api/spotify/disconnect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    state.spotify = payload.spotify || {};
    renderSpotifyStatus(state.spotify);
    toast('Spotify disconnected');
  }

  async function cacheSpotifyUri() {
    await refreshSpotifyStatus();
    const caps = spotifyCapabilities(state.spotify || {});
    if (!caps.ready) {
      toast(caps.guidance, 'warning');
      return;
    }

    const target = ($('spotify-cache-uri').value || '').trim();
    if (!target) {
      toast('Spotify URI is required', 'warning');
      return;
    }
    const payload = await apiFetch('/api/spotify/cache', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target }),
    });
    if (payload.cached_path) {
      setSelectedPath(payload.cached_path);
    }
    await refreshTree();
    await loadLibrary();
    toast(`Cached: ${payload.cached_path || target}`);
  }

  async function saveRotarySettings() {
    const ledInput = $('led-speed');
    const volumeInput = $('rotary-volume-per-turn');
    const ledSpeed = clampInt(ledInput.value, 5, 250, 25);
    const volumePerTurn = clampInt(volumeInput.value, 20, 300, 100);
    ledInput.value = String(ledSpeed);
    volumeInput.value = String(volumePerTurn);

    const payload = await apiFetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rotary_led_step_ms: ledSpeed,
        rotary_volume_per_turn: volumePerTurn,
      }),
    });
    if (payload.settings && payload.settings.rotary_led_step_ms != null) {
      $('led-speed').value = String(payload.settings.rotary_led_step_ms);
    }
    if (payload.settings && payload.settings.rotary_volume_per_turn != null) {
      $('rotary-volume-per-turn').value = String(payload.settings.rotary_volume_per_turn);
    }
    toast('Settings saved');
  }

  function bindSettings() {
    const ledInput = $('led-speed');
    const volumeInput = $('rotary-volume-per-turn');
    const spotifyClient = $('spotify-client-id');
    const spotifyDevice = $('spotify-device-name');

    const saveRotarySettingsSafe = async () => {
      try {
        await saveRotarySettings();
      } catch (err) {
        toast(`Save settings failed: ${err.message}`, 'error');
      }
    };

    [ledInput, volumeInput].forEach((input) => {
      input.addEventListener('change', () => {
        void saveRotarySettingsSafe();
      });
      input.addEventListener('blur', () => {
        void saveRotarySettingsSafe();
      });
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          input.blur();
        }
      });
    });

    spotifyClient.addEventListener('input', () => {
      spotifyClient.dataset.autofilled = '0';
    });

    spotifyDevice.addEventListener('input', () => {
      spotifyDevice.dataset.autofilled = '0';
    });

    $('spotify-save-config').addEventListener('click', async () => {
      try {
        await saveSpotifyConfig();
      } catch (err) {
        toast(`Spotify config failed: ${err.message}`, 'error');
      }
    });

    $('spotify-connect').addEventListener('click', async () => {
      try {
        const saved = await saveSpotifyConfig();
        if (!saved) {
          return;
        }
        await connectSpotify();
      } catch (err) {
        toast(`Spotify connect failed: ${err.message}`, 'error');
      }
    });

    $('spotify-disconnect').addEventListener('click', async () => {
      try {
        await disconnectSpotify();
      } catch (err) {
        toast(`Spotify disconnect failed: ${err.message}`, 'error');
      }
    });

    $('spotify-refresh-status').addEventListener('click', async () => {
      try {
        await refreshSpotifyStatus();
      } catch (err) {
        toast(`Spotify status failed: ${err.message}`, 'error');
      }
    });

    $('spotify-cache-btn').addEventListener('click', async () => {
      try {
        await cacheSpotifyUri();
      } catch (err) {
        toast(`Spotify cache failed: ${err.message}`, 'error');
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
    loadUiPrefs();

    bindTabs();
    bindControls();
    bindLibrary();
    bindCards();
    bindSettings();
    bindEventsPanel();

    updateUploadStatus();

    try {
      await loadMappings();
      await loadTreeNode('');
      await ensureTreePathLoaded(state.currentDir);
      renderTree();
      renderBreadcrumb();
      $('target-dir').value = state.currentDir;
      await loadLibrary();
      if (state.selectedPath) {
        setSelectedPath(state.selectedPath);
      }

      const statusPayload = await apiFetch('/api/status');
      applySnapshot(statusPayload);
      await refreshSpotifyStatus();
      activateTab(state.activeTab, false);
      saveUiPrefs();
    } catch (err) {
      toast(`Initial load failed: ${err.message}`, 'error');
    }

    connectStream();
  }

  init();
})();
