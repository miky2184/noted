// ── State ─────────────────────────────────────────────────────────────────────
let llmActive = false;
let currentDate = window.NOTED_BOOT.today;
let refreshTimer = null;
let activeTab = 'notes';
const REFRESH_INTERVAL = 30000;
let activeCtx = localStorage.getItem('noted-ctx') || window.NOTED_BOOT.activeCtx;
let hideDone = localStorage.getItem('noted-hide-done') === '1';
let pendingHighlightNoteId = null;

// ── Per-note hide (localStorage, no DB) ───────────────────────────────────────
function _hiddenKey() { return `noted-hidden-${activeCtx}`; }
function _loadHidden() {
  try { return new Set(JSON.parse(localStorage.getItem(_hiddenKey()) || '[]')); }
  catch { return new Set(); }
}
function _saveHidden(set) {
  localStorage.setItem(_hiddenKey(), JSON.stringify([...set]));
}
function hideNote(id) {
  const s = _loadHidden(); s.add(id); _saveHidden(s);
  if (activeTab === 'notes') loadNotes(); else if (activeTab === 'board') loadBoard();
}
function unhideNote(id) {
  const s = _loadHidden(); s.delete(id); _saveHidden(s);
  if (activeTab === 'notes') loadNotes(); else loadBoard();
}
function clearAllHidden() {
  localStorage.removeItem(_hiddenKey());
  if (activeTab === 'notes') loadNotes(); else loadBoard();
}
let _showHiddenTemp = false;
function toggleShowHidden() {
  _showHiddenTemp = !_showHiddenTemp;
  if (activeTab === 'notes') loadNotes(); else loadBoard();
}
function _syncHiddenCounters() {
  const n = _loadHidden().size;
  document.querySelectorAll('.hidden-note-counter').forEach(el => {
    el.textContent = n > 0 ? `🙈 ${n}` : '';
    el.style.display = n > 0 ? '' : 'none';
  });
}

// ── API wrapper ───────────────────────────────────────────────────────────────
let _pendingRequests = 0;
function _setLoading(delta) {
  _pendingRequests = Math.max(0, _pendingRequests + delta);
  document.getElementById('saving-dot')?.classList.toggle('active', _pendingRequests > 0);
}

// ── Assignee helpers ──────────────────────────────────────────────────────────
function _parseAssignees(str) {
  // Accepts "mario, luigi", "@mario @luigi", "mario luigi" → ["mario","luigi"]
  if (!str) return [];
  return str
    .split(/[\s,]+/)
    .map(a => a.replace(/^@/, '').trim().toLowerCase())
    .filter(Boolean);
}
function _extractMentions(content) {
  // Extract all @word from note content
  return [...new Set((content.match(/@([\w.àèìòùÀÈÌÒÙáéíóú]+)/g) || []).map(m => m.slice(1).toLowerCase()))];
}
function _mergeAssignees(existing, fromContent) {
  const all = [...new Set([..._parseAssignees(existing), ...fromContent])];
  return all.join(',');
}
function _renderAssigneeBadges(assignee, noteId) {
  const names = _parseAssignees(assignee);
  if (!names.length) {
    return `<span class="assignee-badge assignee-empty" onclick="editAssignee(this,${noteId},'')" title="Assegna a qualcuno">+@</span>`;
  }
  const encoded = escHtml(assignee);
  return names.map(a =>
    `<span class="assignee-badge" onclick="editAssignee(this,${noteId},'${encoded}')" title="Modifica assegnatari">@${escHtml(a)}</span>`
  ).join('');
}

function apiFetch(url, opts = {}) {
  const sep = url.includes('?') ? '&' : '?';
  const isMutating = opts.method && opts.method !== 'GET';
  if (isMutating) _setLoading(+1);
  return fetch(`${url}${sep}ctx=${encodeURIComponent(activeCtx)}`, opts)
    .finally(() => { if (isMutating) _setLoading(-1); });
}

// ── Context switcher ──────────────────────────────────────────────────────────
async function downloadBackup(format) {
  document.getElementById('backup-menu').style.display = 'none';
  try {
    const filename = `noted_backup_${new Date().toLocaleDateString('sv')}.${format}`;
    const a = document.createElement('a');
    a.href = `/api/backup/${format}?ctx=${encodeURIComponent(activeCtx)}`;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    toast(`Backup ${format.toUpperCase()} scaricato`, 'success');
  } catch(e) { toast(e.message, 'error'); }
}

function triggerImport(format) {
  document.getElementById('backup-menu').style.display = 'none';
  document.getElementById(`import-${format}-input`).value = '';
  document.getElementById(`import-${format}-input`).click();
}

async function handleImport(input, format) {
  const file = input.files[0];
  if (!file) return;

  const ok = await showConfirm(
    'Importa backup',
    `Stai per sostituire <strong>tutti i dati attuali</strong> con il backup:<br>
     <code style="font-size:0.8rem;background:var(--surface2);padding:2px 6px;border-radius:4px">${escHtml(file.name)}</code><br><br>
     Questa operazione è <strong>irreversibile</strong>. Esegui prima un export se vuoi conservare i dati attuali.`,
    'Importa e sostituisci'
  );
  if (!ok) return;

  const loading = showImportLoading();
  try {
    loading.progress(20, 'Lettura file…');
    let body, contentType;
    if (format === 'db') {
      body = await file.arrayBuffer();
      contentType = 'application/octet-stream';
    } else {
      body = await file.text();
      contentType = 'application/json';
    }

    loading.progress(55, 'Invio al server…');
    const res = await fetch(`/api/restore/${format}`, {
      method: 'POST',
      headers: { 'Content-Type': contentType },
      body,
    });

    loading.progress(90, 'Finalizzazione…');
    if (!res.ok) {
      let msg = 'Errore server';
      try { msg = (await res.json()).detail || msg; } catch(_) {}
      throw new Error(msg);
    }

    loading.progress(100);
    await new Promise(r => setTimeout(r, 300));
    loading.success();
    setTimeout(() => { window.location.href = `/?ctx=${encodeURIComponent(activeCtx)}`; }, 2000);
  } catch(e) {
    loading.close();
    toast(e.message, 'error');
  }
}

function toggleBackupMenu() {
  const menu = document.getElementById('backup-menu');
  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

document.addEventListener('click', e => {
  const wrapper = document.getElementById('backup-wrapper');
  if (wrapper && !wrapper.contains(e.target)) {
    document.getElementById('backup-menu').style.display = 'none';
  }
});

function toggleCtxMenu() {
  document.getElementById('ctx-menu').classList.toggle('open');
}

document.addEventListener('click', e => {
  const switcher = document.getElementById('ctx-switcher');
  if (switcher && !switcher.contains(e.target)) {
    document.getElementById('ctx-menu').classList.remove('open');
  }
});

function switchContext(name) {
  activeCtx = name;
  localStorage.setItem('noted-ctx', name);
  document.getElementById('ctx-menu').classList.remove('open');
  // reload page so server renders correct recap/contexts state
  window.location.href = `/?ctx=${encodeURIComponent(name)}`;
}

async function createContext() {
  const input = document.getElementById('ctx-new-input');
  const name = input.value.trim().toLowerCase();
  if (!name) return;
  try {
    const res = await fetch('/api/contexts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || 'Errore');
    input.value = '';
    switchContext(name);
  } catch(e) { toast(e.message, 'error'); }
}

function toggleFavorite(e, name) {
  e.stopPropagation();
  const current = localStorage.getItem('noted-favorite-ctx');
  const newFav = current === name ? 'default' : name;
  localStorage.setItem('noted-favorite-ctx', newFav);
  _refreshStars();
  toast(newFav === name ? `⭐ ${name.toUpperCase()} impostato come preferito` : 'Preferito rimosso');
  // Persisti lato server (usato dal tray e da altri client)
  fetch('/api/settings/favorite-ctx', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: newFav }),
  }).catch(() => {});
}

function _refreshStars() {
  const fav = localStorage.getItem('noted-favorite-ctx') || 'default';
  document.querySelectorAll('.ctx-star-btn').forEach(btn => {
    const id = btn.id.replace('ctx-star-', '');
    const item = document.getElementById(`ctx-item-${id}`);
    if (!item) return;
    const name = item.querySelector('.ctx-item-name')?.textContent.trim().toLowerCase();
    const isFav = name === fav;
    btn.textContent = isFav ? '★' : '☆';
    btn.classList.toggle('favorite', isFav);
    btn.title = isFav ? 'Preferito attivo' : 'Imposta come preferito';
  });
}

function startRename(e, ctxId, currentName) {
  e.stopPropagation();
  const item = document.getElementById(`ctx-item-${ctxId}`);
  const nameSpan = item.querySelector('.ctx-item-name');
  const actions = item.querySelector('.ctx-item-actions');

  const input = document.createElement('input');
  input.className = 'ctx-rename-input';
  input.value = currentName;
  nameSpan.replaceWith(input);
  actions.style.opacity = '1';
  input.focus();
  input.select();

  async function save() {
    const newName = input.value.trim().toLowerCase();
    if (!newName || newName === currentName) { window.location.reload(); return; }
    try {
      const res = await fetch(`/api/contexts/${ctxId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Errore');
      // update favorite/active if needed
      if (localStorage.getItem('noted-favorite-ctx') === currentName)
        localStorage.setItem('noted-favorite-ctx', newName);
      const targetCtx = activeCtx === currentName ? newName : activeCtx;
      window.location.href = `/?ctx=${encodeURIComponent(targetCtx)}`;
    } catch(err) { toast(err.message, 'error'); window.location.reload(); }
  }

  input.onblur = save;
  input.onkeydown = e => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { window.location.reload(); }
  };
}

async function deleteContext(e, ctxId, name) {
  e.stopPropagation();
  document.getElementById('ctx-menu').classList.remove('open');
  const ok = await showConfirm(
    `Elimina contesto`,
    `Stai per eliminare <strong>${name.toUpperCase()}</strong>.<br>Tutte le note, recap e progetti Gantt associati andranno persi definitivamente.`
  );
  if (!ok) return;
  try {
    const res = await fetch(`/api/contexts/${ctxId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error();
    if (localStorage.getItem('noted-favorite-ctx') === name)
      localStorage.removeItem('noted-favorite-ctx');
    const target = activeCtx === name ? 'default' : activeCtx;
    window.location.href = `/?ctx=${encodeURIComponent(target)}`;
  } catch { toast('Errore eliminazione contesto', 'error'); }
}

// Init: apply stars and auto-redirect to favorite if no ctx in URL
(function initCtx() {
  _refreshStars();
  const urlCtx = new URLSearchParams(window.location.search).get('ctx');
  if (!urlCtx) {
    const fav = localStorage.getItem('noted-favorite-ctx') || activeCtx;
    if (fav && fav !== 'default') {
      window.location.href = `/?ctx=${encodeURIComponent(fav)}`;
    }
  }
})();

// ── Theme ─────────────────────────────────────────────────────────────────────
(function() {
  const saved = localStorage.getItem('noted-theme') || 'dark';
  if (saved === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
    document.getElementById('theme-toggle').textContent = '☀️';
  }
})();

document.getElementById('theme-toggle').addEventListener('click', () => {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  const next = isLight ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next === 'dark' ? '' : 'light');
  document.getElementById('theme-toggle').textContent = next === 'light' ? '☀️' : '🌙';
  localStorage.setItem('noted-theme', next);
});

// ── Tabs ──────────────────────────────────────────────────────────────────────
function switchTab(tab) {
  if (tab === 'focus' || tab === 'due') tab = 'board';
  activeTab = tab;
  const isMobile = window.innerWidth <= 768;

  ['notes', 'board', 'gantt', 'docs', 'editor'].forEach(t => {
    const tabBtn = document.getElementById(`tab-${t}`);
    if (tabBtn) tabBtn.classList.toggle('active', t === tab);
    const mb = document.getElementById(`mnav-${t}`);
    if (mb) mb.classList.toggle('active', t === tab);
  });

  document.getElementById('view-notes').style.display = tab === 'notes' ? 'block' : 'none';
  document.getElementById('view-board').style.display = tab === 'board' ? 'block' : 'none';
  document.getElementById('view-gantt').style.display = tab === 'gantt' ? 'block' : 'none';
  document.getElementById('view-docs').style.display = tab === 'docs' ? 'block' : 'none';
  document.getElementById('view-editor').style.display = tab === 'editor' ? 'flex' : 'none';
  document.getElementById('date-nav').style.display = tab === 'notes' ? '' : 'none';
  document.getElementById('filter-bar').style.display = 'none';

  if (isMobile) {
    const showFab = tab === 'notes' && isToday(currentDate);
    const fab = document.getElementById('mobile-fab');
    if (fab) fab.style.display = showFab ? 'flex' : 'none';
    if (!showFab) closeNoteSheet();
  } else {
    document.getElementById('add-form').style.display = (tab === 'notes' && isToday(currentDate)) ? '' : 'none';
  }

  if (tab === 'gantt' || tab === 'docs' || tab === 'editor') {
    if (!isMobile) {
      document.querySelector('.sidebar').style.display = 'none';
      document.querySelector('.layout').style.gridTemplateColumns = '1fr';
    }
    if (tab === 'gantt') loadGantt();
    if (tab === 'docs') loadDocList();
    if (tab === 'editor') initEditor();
  } else {
    if (!isMobile) {
      document.querySelector('.sidebar').style.display = '';
      document.querySelector('.layout').style.gridTemplateColumns = '1fr 360px';
    }
  }
  if (tab === 'board') loadBoard();
}

// ── Note bottom sheet (mobile) ────────────────────────────────────────────────
function openNoteSheet() {
  document.getElementById('add-form').classList.add('mobile-open');
  document.getElementById('sheet-backdrop').classList.add('show');
  document.getElementById('mobile-fab').classList.add('open');
  setTimeout(() => document.getElementById('note-input')?.focus(), 320);
}

function closeNoteSheet() {
  document.getElementById('add-form').classList.remove('mobile-open');
  document.getElementById('sheet-backdrop').classList.remove('show');
  const fab = document.getElementById('mobile-fab');
  if (fab) fab.classList.remove('open');
}

function toggleNoteSheet() {
  if (document.getElementById('add-form').classList.contains('mobile-open')) {
    closeNoteSheet();
  } else {
    openNoteSheet();
  }
}

// ── Markdown recap init ───────────────────────────────────────────────────────
(function() {
  const box = document.getElementById('recap-box');
  if (box && window.NOTED_BOOT.recapSummary) {
    box.innerHTML = marked.parse(window.NOTED_BOOT.recapSummary);
  }
})();

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg, type = '') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = type ? `show ${type}` : 'show';
  clearTimeout(el._t);
  el._t = setTimeout(() => el.className = '', 2500);
}

// ── Due notes ─────────────────────────────────────────────────────────────────
const STATUS_LABEL = { backlog: '🗂 backlog', todo: '⬜ todo', discuss: '💬 discuss', wip: '🔄 wip', waiting: '⏳ waiting', blocked: '🚫 blocked', done: '✅ done' };

async function loadDueNotes() {
  try {
    const res = await apiFetch('/api/notes/due');
    const notes = await res.json();
    renderDueNotes(notes);
  } catch(e) { console.error(e); }
}

function renderDueNotes(notes) {
  const list = document.getElementById('due-list');
  document.getElementById('due-count').textContent = notes.length;
  const today = window.NOTED_BOOT.today;
  const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0,10);

  if (!notes.length) {
    list.innerHTML = `<div class="empty">Nessuna scadenza aperta. 🎉</div>`;
    return;
  }

  // group: scadute | oggi | prossimi 7gg | dopo
  const groups = { overdue: [], today: [], soon: [], future: [] };
  notes.forEach(n => {
    if (n.due_date < today)        groups.overdue.push(n);
    else if (n.due_date === today) groups.today.push(n);
    else if (n.due_date <= new Date(Date.now() + 7*86400000).toISOString().slice(0,10))
                                   groups.soon.push(n);
    else                           groups.future.push(n);
  });

  const labels = { overdue: '⚠️ Scadute', today: '🔴 Oggi', soon: '🟡 Prossimi 7 giorni', future: '📆 Dopo' };
  let html = '';
  for (const [key, items] of Object.entries(groups)) {
    if (!items.length) continue;
    html += `<div class="due-group-label">${labels[key]}</div>`;
    html += items.map(n => {
      const dateCls = key === 'overdue' ? 'overdue' : key === 'today' ? 'today' : 'future';
      const statusHtml = n.status ? `<span class="status status-${n.status}" onclick="cycleStatus(${n.id},'${n.status||''}')" title="Cambia stato">${STATUS_LABEL[n.status]}</span>` : `<span class="status status-empty" onclick="cycleStatus(${n.id},'')" title="Aggiungi stato">+ stato</span>`;
      const priorityHtml = `<span class="priority priority-${n.priority}" onclick="cyclePriority(${n.id},'${n.priority}')" title="Cambia priorità">${n.priority}</span>`;
      const projHtml = n.project
        ? `<span class="project-badge" onclick="editProject(this,${n.id},'${escHtml(n.project)}')" title="Modifica progetto">${escHtml(n.project)}</span>`
        : `<span class="project-badge project-empty" onclick="editProject(this,${n.id},'')" title="Aggiungi progetto">+progetto</span>`;
      const assigneeHtml = _renderAssigneeBadges(n.assignee, n.id);
      const tagsGroup = `<span class="tags-group" onclick="editTags(this,${n.id},'${escHtml(n.tags.join(','))}')" title="Modifica tag">${
        n.tags.length
          ? n.tags.map(t => `<span class="tag">#${escHtml(t)}</span>`).join('')
          : `<span class="tag tag-empty">+tag</span>`
      }</span>`;
      return `
      <div class="due-item ${dateCls}" data-id="${n.id}">
        <div class="due-item-date ${dateCls}">📅 ${n.due_date}</div>
        <div class="due-item-body">
          <div class="due-item-content" onclick="startEdit(this,${n.id})" title="Clicca per modificare">${escHtml(n.content)}</div>
          <div class="due-item-meta">
            ${statusHtml}${priorityHtml}${projHtml}${assigneeHtml}${tagsGroup}
          </div>
        </div>
        <button class="delete-btn" style="opacity:0.4" onclick="deleteNote(${n.id})" title="Elimina">✕</button>
      </div>`;
    }).join('');
  }
  list.innerHTML = html;
}

async function reloadActiveView() {
  if (activeTab === 'board') return loadBoard();
  if (activeTab === 'due') return loadDueNotes();
  if (activeTab === 'focus') return loadFocus();
  return loadNotes();
}

// ── Focus mode ───────────────────────────────────────────────────────────────
async function loadFocus() {
  try {
    const today = window.NOTED_BOOT.today;
    const [dueRes, boardRes, notesRes] = await Promise.all([
      apiFetch('/api/notes/due'),
      apiFetch('/api/board'),
      apiFetch('/api/notes?' + new URLSearchParams({ day: today })),
    ]);
    const due = await dueRes.json();
    const board = await boardRes.json();
    const notes = await notesRes.json();
    renderFocus({ due, board, notes });
  } catch(e) {
    console.error(e);
    toast('Errore caricamento focus', 'error');
  }
}

function _uniqueNotes(notes) {
  const seen = new Set();
  return notes.filter(n => {
    if (seen.has(n.id)) return false;
    seen.add(n.id);
    return true;
  });
}

function renderFocus({ due, board, notes }) {
  const today = window.NOTED_BOOT.today;
  const overdue = due.filter(n => n.due_date < today);
  const dueToday = due.filter(n => n.due_date === today);
  const wip = board.wip || [];
  const inbox = _uniqueNotes([
    ...(board.inbox || []),
    ...notes.filter(n => n.status !== 'done' && (!n.project || !n.status || !n.due_date)),
  ]).slice(0, 8);
  const total = _uniqueNotes([...overdue, ...dueToday, ...wip, ...inbox]).length;

  document.getElementById('focus-count').textContent = total;
  document.getElementById('focus-summary').innerHTML = [
    { n: overdue.length, label: 'scadute' },
    { n: dueToday.length, label: 'da fare oggi' },
    { n: wip.length, label: 'in corso' },
    { n: inbox.length, label: 'da triagiare' },
  ].map(s => `
    <div class="focus-stat">
      <div class="focus-stat-num">${s.n}</div>
      <div class="focus-stat-label">${s.label}</div>
    </div>
  `).join('');

  const groups = [
    { key: 'overdue', title: 'Scadute', notes: overdue, empty: 'Nessuna scadenza arretrata.' },
    { key: 'today', title: 'Oggi', notes: dueToday, empty: 'Nessuna scadenza per oggi.' },
    { key: 'wip', title: 'In corso', notes: wip, empty: 'Niente in corso.' },
    { key: 'inbox', title: 'Da triagiare', notes: inbox, empty: 'Inbox pulita.' },
  ];

  document.getElementById('focus-grid').innerHTML = groups.map(g => `
    <section class="focus-panel">
      <div class="focus-panel-header">
        <span class="focus-panel-title">${g.title}</span>
        <span class="count-badge">${g.notes.length}</span>
      </div>
      <div class="focus-panel-body">
        ${g.notes.length ? g.notes.map(n => focusCard(n, g.key)).join('') : `<div class="empty" style="padding:10px">${g.empty}</div>`}
      </div>
    </section>
  `).join('');
}

function focusCard(n, kind) {
  const projHtml = n.project ? `<span class="project-badge">${escHtml(n.project)}</span>` : '';
  const dueHtml = n.due_date ? `<span class="due-date ${n.due_date < window.NOTED_BOOT.today ? 'overdue' : 'soon'}">📅 ${n.due_date}</span>` : '';
  const statusHtml = n.status ? `<span class="status status-${n.status}">${STATUS_LABEL[n.status] || n.status}</span>` : `<span class="status status-empty">inbox</span>`;
  const nextAction = kind === 'inbox'
    ? `<button class="focus-action" onclick="event.stopPropagation();quickPatchFocus(${n.id},{status:'todo'})">todo</button>`
    : `<button class="focus-action" onclick="event.stopPropagation();quickPatchFocus(${n.id},{status:'done'})">done</button>`;
  return `
    <article class="focus-card ${kind}" data-id="${n.id}" onclick="openNoteFromCard(event,${n.id},'${n.created_at}')">
      <div class="focus-card-title" onclick="event.stopPropagation();startEdit(this,${n.id})">${escHtml(n.content)}</div>
      <div class="focus-card-meta">
        ${projHtml}${statusHtml}<span class="priority priority-${n.priority}">${n.priority}</span>${dueHtml}
        <button class="focus-action" onclick="event.stopPropagation();cycleStatus(${n.id},'${n.status || ''}')">stato</button>
        ${nextAction}
      </div>
    </article>
  `;
}

async function quickPatchFocus(noteId, patch) {
  try {
    await patchNote(noteId, patch);
    await loadFocus();
    toast('Focus aggiornato', 'success');
  } catch {
    toast('Errore aggiornamento focus', 'error');
  }
}

// ── Date navigation ───────────────────────────────────────────────────────────
function formatDateLabel(isoDate) {
  const d = new Date(isoDate + 'T12:00:00');
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' });
}

function isToday(isoDate) {
  return isoDate === window.NOTED_BOOT.today;
}

function navigateToDate(isoDate) {
  currentDate = isoDate;
  document.getElementById('current-date-label').textContent = formatDateLabel(isoDate);
  document.getElementById('notes-section-label').textContent =
    isToday(isoDate) ? 'Note di oggi' : `Note del ${formatDateLabel(isoDate)}`;
  const isMobile = window.innerWidth <= 768;
  if (isMobile) {
    const showFab = isToday(isoDate);
    const fab = document.getElementById('mobile-fab');
    if (fab) fab.style.display = showFab ? 'flex' : 'none';
    if (!showFab) closeNoteSheet();
  } else {
    document.getElementById('add-form').style.display = isToday(isoDate) ? '' : 'none';
  }
  loadNotes();
  resetRefresh();
}

document.getElementById('prev-day').addEventListener('click', () => {
  const d = new Date(currentDate + 'T12:00:00');
  d.setDate(d.getDate() - 1);
  navigateToDate(d.toISOString().slice(0, 10));
});

document.getElementById('next-day').addEventListener('click', () => {
  const d = new Date(currentDate + 'T12:00:00');
  d.setDate(d.getDate() + 1);
  navigateToDate(d.toISOString().slice(0, 10));
});

document.getElementById('today-btn').addEventListener('click', () => {
  navigateToDate(window.NOTED_BOOT.today);
});

// ── Load notes ────────────────────────────────────────────────────────────────
let activeTag = null, activeProject = null;

let _loadingNotes = false;
async function loadNotes() {
  if (_loadingNotes) return;
  _loadingNotes = true;

  const dot = document.getElementById('refresh-dot');
  dot.classList.add('active');
  setTimeout(() => dot.classList.remove('active'), 600);

  const params = new URLSearchParams({ day: currentDate });
  if (activeTag) params.set('tag', activeTag);
  if (activeProject) params.set('project', activeProject);

  try {
    const res = await apiFetch('/api/notes?' + params);
    const notes = await res.json();
    renderNotes(notes);
    renderFilterBar();
  } catch(e) {
    console.error(e);
  } finally {
    _loadingNotes = false;
  }
}

function toggleHideDone() {
  hideDone = !hideDone;
  localStorage.setItem('noted-hide-done', hideDone ? '1' : '0');
  _syncHideDoneBtn();
  loadNotes();
}

function _syncHideDoneBtn() {
  const btn = document.getElementById('hide-done-btn');
  if (!btn) return;
  btn.style.borderColor = hideDone ? 'var(--accent)' : 'var(--border)';
  btn.style.color       = hideDone ? 'var(--accent)' : 'var(--text-muted)';
  btn.style.background  = hideDone ? 'var(--accent-dim)' : '';
  btn.title = hideDone ? 'Mostra task completati' : 'Nascondi task completati';
  btn.textContent = hideDone ? '🙈 done' : '👁 done';
}

function renderNotes(notes) {
  const list = document.getElementById('notes-list');
  _syncHideDoneBtn();

  const hidden    = _loadHidden();
  const doneNotes = notes.filter(n => n.status === 'done');
  const visible   = (hideDone ? notes.filter(n => n.status !== 'done') : notes)
                    .filter(n => !hidden.has(n.id));
  const shownHidden = _showHiddenTemp ? notes.filter(n => hidden.has(n.id)) : [];
  document.getElementById('notes-count').textContent = visible.length;

  if (!visible.length && !notes.length) {
    list.innerHTML = `<div class="empty">
      Nessuna nota${activeTag || activeProject ? ' con questi filtri' : ' per questo giorno'}.<br>
      ${isToday(currentDate) ? 'Aggiungine una qui sopra oppure con: <code>noted add "..."</code>' : ''}
    </div>`;
    return;
  }

  const hiddenDoneCount = hideDone ? doneNotes.length : 0;

  const today = window.NOTED_BOOT.today;
  const noteCards = visible.map(n => {
    const tagsGroup = `<span class="tags-group" onclick="editTags(this,${n.id},'${escHtml(n.tags.join(','))}')" title="Modifica tag">${
      n.tags.length
        ? n.tags.map(t => `<span class="tag">#${escHtml(t)}</span>`).join('')
        : `<span class="tag tag-empty">+tag</span>`
    }</span>`;
    const projHtml = n.project
      ? `<span class="project-badge" onclick="editProject(this,${n.id},'${escHtml(n.project)}')" title="Modifica progetto">${escHtml(n.project)}</span>`
      : `<span class="project-badge project-empty" onclick="editProject(this,${n.id},'')" title="Aggiungi progetto">+progetto</span>`;
    const msHtml = n.milestone_id
      ? `<span class="milestone-badge" onclick="editMilestone(event,${n.id},${n.milestone_id},'${escHtml(n.project||'')}')">🏁 ms#${n.milestone_id}</span>`
      : (n.project
         ? `<span class="milestone-badge milestone-empty" onclick="editMilestone(event,${n.id},null,'${escHtml(n.project||'')}')">+ ms</span>`
         : '');
    const assigneeHtml = _renderAssigneeBadges(n.assignee, n.id);
    return `
    <div class="note-item" data-id="${n.id}">
      <div class="note-meta">
        <span class="note-time">${n.created_at.slice(11, 16)}</span>
        ${projHtml}
        ${msHtml}
        ${tagsGroup}
        ${assigneeHtml}
        <span class="status ${n.status ? 'status-'+n.status : 'status-empty'}" onclick="cycleStatus(${n.id},'${n.status||''}')" title="Clicca per cambiare stato">${n.status ? STATUS_LABEL[n.status] : '+ stato'}</span>
        <span class="priority priority-${n.priority}" onclick="cyclePriority(${n.id},'${n.priority}')" title="Clicca per cambiare priorità">${n.priority}</span>
        <span class="due-date${n.due_date ? (n.due_date < today ? ' overdue' : (n.due_date <= new Date(Date.now()+2*86400000).toISOString().slice(0,10) ? ' soon' : '')) : ' due-empty'}" onclick="editDue(this,${n.id},'${n.due_date||''}')" title="Clicca per impostare scadenza">${n.due_date ? '📅 '+n.due_date : '+ scadenza'}</span>
        <span class="note-id">#${n.id}</span>
        <button class="hide-btn" onclick="hideNote(${n.id})" title="Nascondi nota">🙈</button>
        <button class="delete-btn" onclick="deleteNote(${n.id})" title="Elimina">✕</button>
      </div>
      <div class="note-content" onclick="startEdit(this,${n.id})" title="Clicca per modificare">${escHtml(n.content)}</div>
      <div class="note-deps-row" id="deps-chips-${n.id}" style="display:flex;gap:4px;flex-wrap:wrap;margin-top:${(n.blockers.length||n.blocking.length)?'5px':'0'};min-height:0;">
        ${n.blockers.length ? `<span class="dep-chip blocker" onclick="toggleDepsPanel(${n.id})" title="Bloccata da ${n.blockers.length} nota/e">🚫 ${n.blockers.length} blocker${n.blockers.length>1?'s':''}</span>` : ''}
        ${n.blocking.length ? `<span class="dep-chip blocking" onclick="toggleDepsPanel(${n.id})" title="Blocca ${n.blocking.length} nota/e">▶ blocca ${n.blocking.length}</span>` : ''}
        <span class="dep-chip add-dep" onclick="toggleDepsPanel(${n.id})" title="Gestisci dipendenze">+ dipendenza</span>
      </div>
      <div class="deps-panel" id="deps-panel-${n.id}"></div>
      ${n.docs && n.docs.length ? `
        <div class="note-docs">
          ${n.docs.map(d => `
            <button class="doc-chip" onclick="openDoc(${d.id})" title="${escHtml(d.orig_name)}${d.analysis ? '\n\n' + escHtml(d.analysis) : ''}">
              ${_fileIcon(d.mime_type, d.orig_name)}
              <span>${escHtml(d.orig_name)}</span>
              ${d.analysis ? '<span class="doc-chip-ai" title="Analisi AI disponibile">🔍</span>' : ''}
              <span class="doc-chip-size">${_fmtSize(d.size_bytes)}</span>
            </button>
          `).join('')}
          <button class="doc-chip doc-chip-add" onclick="attachToNote(${n.id})" title="Allega file">📎</button>
        </div>
      ` : `<button class="doc-chip doc-chip-add doc-chip-add-hidden" onclick="attachToNote(${n.id})" title="Allega file">📎</button>`}
    </div>`;
  }).join('');

  // Shown-hidden notes (dimmed, with unhide button)
  const shownHiddenCards = shownHidden.map(n => `
    <div class="note-item shown-hidden" data-id="${n.id}">
      <div class="note-meta">
        <span class="note-time">${n.created_at.slice(11, 16)}</span>
        ${n.project ? `<span class="project-badge">${escHtml(n.project)}</span>` : ''}
        <span style="font-size:0.72rem;color:var(--text-muted);flex:1;">${escHtml(n.content.slice(0,60))}${n.content.length>60?'…':''}</span>
        <button class="hide-btn" style="opacity:1;color:var(--accent);" onclick="unhideNote(${n.id})" title="Mostra nota">👁</button>
      </div>
    </div>`).join('');

  const doneChip = hiddenDoneCount > 0
    ? `<div style="text-align:center;padding:6px 0;">
        <button onclick="toggleHideDone()" style="background:none;border:1px dashed var(--border);border-radius:6px;padding:5px 14px;font-size:0.72rem;color:var(--text-muted);cursor:pointer;">
          ✓ ${hiddenDoneCount} completat${hiddenDoneCount === 1 ? 'a' : 'e'} nascost${hiddenDoneCount === 1 ? 'a' : 'e'} — clicca per mostrare
        </button>
      </div>`
    : '';

  const hiddenCount = hidden.size;
  const hiddenChip = hiddenCount > 0 && !_showHiddenTemp
    ? `<div style="text-align:center;padding:6px 0;">
        <button onclick="toggleShowHidden()" style="background:none;border:1px dashed var(--border);border-radius:6px;padding:5px 14px;font-size:0.72rem;color:var(--text-muted);cursor:pointer;">
          🙈 ${hiddenCount} nascost${hiddenCount === 1 ? 'a' : 'e'} — clicca per gestire
        </button>
      </div>`
    : _showHiddenTemp
      ? `<div style="text-align:center;padding:4px 0;">
          <button onclick="toggleShowHidden()" style="background:none;border:none;font-size:0.7rem;color:var(--accent);cursor:pointer;">▲ nascondi gestione</button>
          <button onclick="clearAllHidden()" style="background:none;border:none;font-size:0.7rem;color:var(--red);cursor:pointer;margin-left:8px;">✕ sblocca tutte</button>
        </div>`
      : '';

  list.innerHTML = noteCards + shownHiddenCards + doneChip + hiddenChip;
  highlightPendingNote();

  if (!visible.length && hiddenDoneCount === 0 && hiddenCount === 0) {
    list.innerHTML = `<div class="empty">
      Nessuna nota${activeTag || activeProject ? ' con questi filtri' : ' per questo giorno'}.<br>
      ${isToday(currentDate) ? 'Aggiungine una qui sopra oppure con: <code>noted add "..."</code>' : ''}
    </div>`;
  }
}

function renderFilterBar() {
  const bar = document.getElementById('filter-bar');
  if (!activeTag && !activeProject) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  bar.innerHTML = '';
  if (activeTag) bar.innerHTML += `<span class="filter-chip">#${escHtml(activeTag)} <button onclick="clearFilter('tag')">✕</button></span>`;
  if (activeProject) bar.innerHTML += `<span class="filter-chip">${escHtml(activeProject)} <button onclick="clearFilter('project')">✕</button></span>`;
}

const NOTE_TEMPLATES = {
  meeting: {
    content: "Meeting: \n\nPartecipanti: \n\nPunti discussi:\n- \n\nDecisioni:\n- \n\nAzioni:\n- ",
    tags: "meeting",
    status: "todo",
  },
  decision: {
    content: "Decisione: \n\nContesto:\n\nOpzioni considerate:\n- \n\nDecisione presa:\n\nMotivo:",
    tags: "decisione",
    status: "",
  },
  followup: {
    content: "Follow-up: \n\nDa fare:\n- \n\nProssimo passo:",
    tags: "followup",
    status: "todo",
    priority: "medium",
  },
  idea: {
    content: "Idea: \n\nPerché è utile:\n\nPrimo esperimento:",
    tags: "idea",
    status: "backlog",
    priority: "low",
  },
};

async function applyNoteTemplate(templateId) {
  const template = NOTE_TEMPLATES[templateId];
  if (!template) return;
  const input = document.getElementById('note-input');
  if (input.value.trim()) {
    const ok = await showConfirm(
      'Applica template',
      'Il testo corrente verrà sostituito dal template selezionato.<br>Gli altri campi del form verranno aggiornati dove previsto.',
      'Sostituisci'
    );
    if (!ok) {
      document.getElementById('note-template').value = '';
      return;
    }
  }
  input.value = template.content;
  document.getElementById('note-tag').value = template.tags || '';
  document.getElementById('note-status').value = template.status || '';
  document.getElementById('note-priority').value = template.priority || 'medium';
  input.style.height = 'auto';
  input.style.height = input.scrollHeight + 'px';
  input.focus();
  document.getElementById('note-template').value = '';
}

function filterBy(type, value) {
  if (type === 'tag') activeTag = value;
  else activeProject = value;
  loadNotes();
}

function clearFilter(type) {
  if (type === 'tag') activeTag = null;
  else activeProject = null;
  loadNotes();
}

// ── Add note ──────────────────────────────────────────────────────────────────
const textarea = document.getElementById('note-input');

textarea.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    document.getElementById('add-form').requestSubmit();
  }
  // auto-resize
  setTimeout(() => { textarea.style.height = 'auto'; textarea.style.height = textarea.scrollHeight + 'px'; }, 0);
});

document.getElementById('add-form').addEventListener('submit', async e => {
  e.preventDefault();
  let content = textarea.value.trim();
  if (!content) return;

  const btn = document.getElementById('add-btn');
  btn.disabled = true;

  // ── LLM enhance step ──────────────────────────────────────────────────────
  if (llmActive) {
    btn.textContent = '🦙 Elaboro…';
    try {
      const llmRes = await fetch('/api/notes/enhance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      if (llmRes.ok) {
        const enhanced = await llmRes.json();
        content = enhanced.content || content;
        if (enhanced.tags)    document.getElementById('note-tag').value     = enhanced.tags;
        if (enhanced.project) document.getElementById('note-project').value = enhanced.project;
        if (enhanced.priority) {
          const sel = document.getElementById('note-priority');
          if ([...sel.options].some(o => o.value === enhanced.priority))
            sel.value = enhanced.priority;
        }
        if (enhanced.status) {
          const sel = document.getElementById('note-status');
          if ([...sel.options].some(o => o.value === enhanced.status))
            sel.value = enhanced.status;
        }
        textarea.value = content;
      } else {
        const err = await llmRes.json().catch(() => ({}));
        toast(`🦙 ${err.detail || 'Ollama non disponibile'} — salvo nota originale`, 'error');
      }
    } catch {
      toast('🦙 Ollama non raggiungibile — salvo nota originale', 'error');
    }
  }

  btn.textContent = '⏳ Salvo…';

  try {
    const res = await apiFetch('/api/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content,
        tags: normalizeTags(document.getElementById('note-tag').value),
        project: document.getElementById('note-project').value.trim() ? normalizeProject(document.getElementById('note-project').value) : null,
        assignee: _mergeAssignees(document.getElementById('note-assignee').value, _extractMentions(content)) || null,
        priority: document.getElementById('note-priority').value,
        due_date: document.getElementById('note-due').value || null,
        status: document.getElementById('note-status').value || null,
      })
    });
    if (!res.ok) throw new Error();
    const newNote = await res.json();
    textarea.value = '';
    textarea.style.height = 'auto';
    document.getElementById('note-tag').value = '';
    document.getElementById('note-project').value = '';
    document.getElementById('note-assignee').value = '';
    document.getElementById('note-due').value = '';
    document.getElementById('note-priority').value = 'medium';
    document.getElementById('note-status').value = '';
    if (_pendingFiles.length) await _uploadPendingFiles(newNote.id);
    await loadNotes();
    if (window.innerWidth <= 768) closeNoteSheet();
  } catch {
    toast('Errore nel salvataggio', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '+ Aggiungi';
  }
});

// ── Delete note ───────────────────────────────────────────────────────────────
async function deleteNote(id) {
  const card = document.querySelector(`[data-id="${id}"]`);
  if (card) card.style.opacity = '0.4';
  try {
    const res = await fetch(`/api/notes/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error();
    await reloadActiveView();
    toast('Nota eliminata');
  } catch {
    if (card) card.style.opacity = '1';
    toast('Errore nella cancellazione', 'error');
  }
}

// ── Inline edit ──────────────────────────────────────────────────────────────
const STATUS_CYCLE = [null, 'backlog', 'todo', 'discuss', 'wip', 'waiting', 'blocked', 'done'];

function startEdit(el, noteId) {
  if (el.contentEditable === 'true') return;
  const original = el.textContent;
  el.contentEditable = 'true';
  el.focus();

  // place cursor at end
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);

  async function save() {
    el.contentEditable = 'false';
    const newContent = el.textContent.trim();
    if (!newContent || newContent === original) { el.textContent = original; return; }
    try {
      const mentions = _extractMentions(newContent);
      const patch = { content: newContent };
      if (mentions.length) {
        // Find current assignee from rendered badge if present
        const noteEl = el.closest('[data-id]');
        const curAssignee = noteEl?.querySelector('.assignee-badge:not(.assignee-empty)')?.textContent?.replace(/^@/,'').trim() || '';
        const merged = _mergeAssignees(curAssignee, mentions);
        if (merged) patch.assignee = merged;
      }
      await patchNote(noteId, patch);
      toast('Nota aggiornata', 'success');
      await reloadActiveView();
    } catch {
      el.textContent = original;
      toast('Errore salvataggio', 'error');
    }
  }

  el.onblur = save;
  el.onkeydown = e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); el.blur(); }
    if (e.key === 'Escape') { el.textContent = original; el.contentEditable = 'false'; }
  };
}

async function cycleStatus(noteId, currentStatus) {
  const idx = STATUS_CYCLE.indexOf(currentStatus || null);
  const next = STATUS_CYCLE[(idx + 1) % STATUS_CYCLE.length];
  try {
    await patchNote(noteId, { status: next === null ? '' : next });
    toast(next ? `Stato: ${next}` : 'Stato rimosso');
    await reloadActiveView();
  } catch { toast('Errore aggiornamento stato', 'error'); }
}

const PRIORITY_CYCLE = ['low', 'medium', 'high'];

async function cyclePriority(noteId, currentPriority) {
  const idx = PRIORITY_CYCLE.indexOf(currentPriority);
  const next = PRIORITY_CYCLE[(idx + 1) % PRIORITY_CYCLE.length];
  try {
    await patchNote(noteId, { priority: next });
    toast(`Priorità: ${next}`);
    await reloadActiveView();
  } catch { toast('Errore aggiornamento priorità', 'error'); }
}

function editDue(el, noteId, currentDue) {
  // replace the span with a date input inline
  const input = document.createElement('input');
  input.type = 'date';
  input.value = currentDue || '';
  input.style.cssText = 'background:var(--surface2);border:1px solid var(--accent);border-radius:6px;color:var(--text);font-size:0.72rem;padding:1px 6px;outline:none;width:130px;';
  el.replaceWith(input);
  input.focus();

  async function save() {
    const val = input.value;
    try {
      await patchNote(noteId, { due_date: val || '' });
      toast(val ? `Scadenza: ${val}` : 'Scadenza rimossa');
    } catch { toast('Errore aggiornamento scadenza', 'error'); }
    await loadNotes();
  }
  const reload = () => activeTab === 'due' ? loadDueNotes() : loadNotes();
  input.onblur = save;
  input.onkeydown = e => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') reload();
  };
}

async function patchNote(noteId, data) {
  const card = document.querySelector(`.note-item[data-id="${noteId}"]`);
  if (card) card.classList.add('saving');
  try {
    const res = await fetch(`/api/notes/${noteId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error();
    return res.json();
  } finally {
    if (card) card.classList.remove('saving');
  }
}

// ── Load recap by id ─────────────────────────────────────────────────────────
async function loadRecap(id) {
  try {
    const res = await fetch(`/api/recaps/${id}`);
    if (!res.ok) throw new Error();
    const r = await res.json();
    document.getElementById('recap-content').innerHTML =
      `<div class="recap-box" id="recap-box">${marked.parse(r.summary)}</div>`;
    // highlight active item
    document.querySelectorAll('.recap-day').forEach(el => el.classList.remove('recap-day-active'));
    const row = document.getElementById(`recap-row-${id}`);
    if (row) row.classList.add('recap-day-active');
  } catch { toast('Errore caricamento recap', 'error'); }
}

// ── Delete recap ─────────────────────────────────────────────────────────────
async function deleteRecap(id) {
  const row = document.getElementById(`recap-row-${id}`);
  if (row) row.style.opacity = '0.4';
  try {
    const res = await fetch(`/api/recaps/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error();
    if (row) row.remove();
    toast('Recap eliminato');
  } catch {
    if (row) row.style.opacity = '1';
    toast('Errore nella cancellazione', 'error');
  }
}

// ── Auto-refresh ──────────────────────────────────────────────────────────────
function resetRefresh() {
  clearInterval(refreshTimer);
  if (isToday(currentDate)) {
    refreshTimer = setInterval(loadNotes, REFRESH_INTERVAL);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function normalizeProject(raw) {
  return raw.trim().toUpperCase();
}

function normalizeTags(raw) {
  return raw
    .split(/[|;,]+/)
    .map(t => t.trim().replace(/^#+/, ''))
    .filter(t => t.length > 0)
    .map(t => {
      const parts = t.split(/[\s\-_]+/);
      return parts[0].toLowerCase() +
        parts.slice(1).map(p => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase()).join('');
    })
    .join(',');
}

// ── Generate recap ────────────────────────────────────────────────────────────
async function _streamToRecapBox(url, doneLabel) {
  const dailyBtn = document.getElementById('gen-daily-btn');
  const weeklyBtn = document.getElementById('gen-weekly-btn');
  const box = document.getElementById('recap-content');

  dailyBtn.disabled = weeklyBtn.disabled = true;
  box.innerHTML = '<div class="recap-box" id="recap-box" style="color:var(--text-muted);font-size:0.82rem;min-height:60px;"></div>';
  const recapBox = document.getElementById('recap-box');

  try {
    const res = await apiFetch(url, { method: 'POST' });
    if (!res.ok) throw new Error((await res.json()).detail || 'Errore');
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let full = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      full += decoder.decode(value, { stream: true });
      recapBox.innerHTML = marked.parse(full);
      recapBox.scrollIntoView({ block: 'nearest' });
    }
    toast(doneLabel, 'success');
    await refreshRecentRecaps();
  } catch(e) {
    box.innerHTML = `<div class="no-recap" style="color:var(--red)">${e.message}</div>`;
    toast(e.message, 'error');
  } finally {
    dailyBtn.disabled = weeklyBtn.disabled = false;
    dailyBtn.textContent = '🤖 Daily';
    weeklyBtn.textContent = '📅 Weekly';
  }
}

// ── Import loading modal ──────────────────────────────────────────────────────
function showImportLoading() {
  document.getElementById('confirm-title').textContent = 'Importazione in corso…';
  document.getElementById('confirm-body').innerHTML = `
    <div style="margin:12px 0 4px;">
      <div style="background:var(--surface2);border-radius:100px;height:6px;overflow:hidden;">
        <div id="import-progress-bar" style="height:100%;width:0%;background:var(--accent);border-radius:100px;transition:width 0.4s ease;"></div>
      </div>
    </div>
    <div id="import-status" style="font-size:0.78rem;color:var(--text-muted);margin-top:8px;">Caricamento file…</div>`;
  document.getElementById('confirm-buttons').style.display = 'none';
  document.getElementById('confirm-modal').classList.add('show');
  return {
    progress(pct, label) {
      document.getElementById('import-progress-bar').style.width = pct + '%';
      if (label) document.getElementById('import-status').textContent = label;
    },
    success() {
      document.getElementById('confirm-title').textContent = 'Operazione riuscita';
      document.getElementById('confirm-body').innerHTML = `
        <div style="text-align:center;padding:8px 0;">
          <div style="font-size:2rem;margin-bottom:8px;">✅</div>
          <div style="color:var(--green);font-weight:600;">Database importato correttamente.</div>
          <div style="color:var(--text-muted);font-size:0.78rem;margin-top:6px;">Ricarico l\'app…</div>
        </div>`;
    },
    close() {
      document.getElementById('confirm-modal').classList.remove('show');
      document.getElementById('confirm-buttons').style.display = '';
    }
  };
}

async function refreshRecentRecaps() {
  try {
    const res = await apiFetch('/api/recaps/recent');
    const recaps = await res.json();
    const container = document.querySelector('.sidebar-section:last-child');
    if (!container) return;
    const list = recaps.map(r => {
      const d = new Date(r.recap_date + 'T12:00:00');
      const label = d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' });
      const time = r.created_at ? r.created_at.slice(11, 16) : '';
      const preview = r.summary.slice(0, 90);
      return `
      <div class="recap-day" id="recap-row-${r.id}">
        <div class="recap-day-body" onclick="loadRecap(${r.id})">
          <div class="recap-day-date">${label} <span style="opacity:0.55">${time}</span> &mdash; ${r.notes_count} note</div>
          <div class="recap-day-preview">${escHtml(preview)}...</div>
        </div>
        <button class="recap-delete-btn" onclick="deleteRecap(${r.id})" title="Elimina recap">✕</button>
      </div>`;
    }).join('');
    const header = container.querySelector('.section-header');
    const existing = container.querySelectorAll('.recap-day, .no-recap');
    existing.forEach(el => el.remove());
    header.insertAdjacentHTML('afterend', list || '<div class="no-recap">Nessun recap recente.</div>');
  } catch(e) { console.error(e); }
}

async function generateRecap() {
  document.getElementById('gen-daily-btn').textContent = '⏳ Generando...';
  await _streamToRecapBox('/api/recap', 'Recap daily salvato 💾');
}

async function generateWeeklyRecap() {
  document.getElementById('gen-weekly-btn').textContent = '⏳ Generando...';
  await _streamToRecapBox('/api/recap/weekly', 'Recap weekly salvato 💾');
}

// ── Model selector ────────────────────────────────────────────────────────────
// ── Schedule ──────────────────────────────────────────────────────────────────
function _setScheduleToggleUI(enabled) {
  const pill = document.getElementById('schedule-toggle-pill');
  const dot  = document.getElementById('schedule-toggle-dot');
  const cfg  = document.getElementById('schedule-config');
  document.getElementById('schedule-enabled').checked = enabled;
  pill.style.background = enabled ? 'var(--accent)' : 'var(--surface2)';
  dot.style.background  = enabled ? '#fff' : 'var(--text-muted)';
  dot.style.transform   = enabled ? 'translateX(14px)' : 'translateX(0)';
  cfg.style.display     = enabled ? 'block' : 'none';
}

async function onScheduleToggle(enabled) {
  _setScheduleToggleUI(enabled);
  if (!enabled) {
    await fetch('/api/schedule', { method: 'DELETE' });
    toast('Recap automatico disattivato');
  } else {
    await saveSchedule();
  }
}

function toggleDay(btn) {
  btn.classList.toggle('active');
}

function setScheduleType(type) {
  document.getElementById('sched-type-daily').classList.toggle('active', type === 'daily');
  document.getElementById('sched-type-weekly').classList.toggle('active', type === 'weekly');
}

async function saveSchedule() {
  const time = document.getElementById('schedule-time').value;
  const days = [...document.querySelectorAll('#schedule-days .day-btn.active')]
    .map(b => parseInt(b.dataset.day));
  const type = document.getElementById('sched-type-daily').classList.contains('active') ? 'daily' : 'weekly';
  if (!time) { toast('Inserisci un orario valido', 'error'); return; }
  if (days.length === 0) { toast('Seleziona almeno un giorno', 'error'); return; }
  const res = await fetch('/api/schedule', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ time, days, type }),
  });
  if (res.ok) toast(`Recap ${type} automatico alle ${time} ✓`);
  else toast('Errore nel salvataggio', 'error');
}

async function initSchedule() {
  const res = await fetch('/api/schedule');
  const data = await res.json();
  if (data.time) {
    document.getElementById('schedule-time').value = data.time;
    document.querySelectorAll('#schedule-days .day-btn').forEach(btn => {
      btn.classList.toggle('active', data.days.includes(parseInt(btn.dataset.day)));
    });
    setScheduleType(data.type || 'daily');
    _setScheduleToggleUI(true);
    _renderSchedulerStatus(data.last_run);
  } else {
    _setScheduleToggleUI(false);
  }
}

function _renderSchedulerStatus(s) {
  const el = document.getElementById('schedule-last-run');
  if (!s || !s.ts) { el.style.display = 'none'; return; }
  const dt = new Date(s.ts);
  const isToday = dt.toDateString() === new Date().toDateString();
  const label = isToday
    ? `oggi ${dt.toLocaleTimeString('it-IT', {hour:'2-digit', minute:'2-digit'})}`
    : dt.toLocaleDateString('it-IT', {day:'2-digit', month:'short'}) + ' ' + dt.toLocaleTimeString('it-IT', {hour:'2-digit', minute:'2-digit'});
  el.style.display = 'block';
  if (s.ok) {
    el.innerHTML = `<span style="color:var(--green)">✓ Ultimo: ${label}</span>`;
  } else {
    el.innerHTML = `<span style="color:var(--red)" title="${escHtml(s.error || '')}">✗ Errore: ${label}</span>`;
  }
}

initSchedule();

async function setModel(modelId) {
  try {
    await fetch('/api/config/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelId }),
    });
    const label = document.querySelector(`#model-select option[value="${modelId}"]`)?.textContent || modelId;
    toast(`Modello: ${label.trim()}`);
  } catch { toast('Errore cambio modello', 'error'); }
}

(async function initModel() {
  try {
    const res = await fetch('/api/config/model');
    const data = await res.json();
    const sel = document.getElementById('model-select');
    if (sel) sel.value = data.model;
  } catch {}
})();

// ── Board ─────────────────────────────────────────────────────────────────────
async function loadBoard() {
  const dot = document.getElementById('board-refresh-dot');
  if (dot) { dot.classList.add('active'); setTimeout(() => dot.classList.remove('active'), 600); }
  const q = document.getElementById('board-q-filter').value.trim();
  const tag = document.getElementById('board-tag-filter').value.trim().replace(/^#/, '');
  const project = document.getElementById('board-project-filter').value.trim();
  const assignee = document.getElementById('board-assignee-filter').value.trim();
  const priority = document.getElementById('board-priority-filter').value;
  const due = document.getElementById('board-due-filter').value;
  const createdToday = document.getElementById('board-created-today-filter').checked;
  const noProject = document.getElementById('board-no-project-filter').checked;
  const noTag = document.getElementById('board-no-tag-filter').checked;
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (tag) params.set('tag', tag);
  if (project) params.set('project', project);
  if (assignee) params.set('assignee', assignee);
  if (priority) params.set('priority', priority);
  if (due) params.set('due', due);
  if (createdToday) params.set('created', 'today');
  if (noProject) params.set('no_project', 'true');
  if (noTag) params.set('no_tag', 'true');
  try {
    const res = await apiFetch('/api/board?' + params);
    const data = await res.json();
    renderBoard(data);
  } catch(e) { console.error(e); }
}

function clearBoardFilters() {
  document.getElementById('board-q-filter').value = '';
  document.getElementById('board-tag-filter').value = '';
  document.getElementById('board-project-filter').value = '';
  document.getElementById('board-assignee-filter').value = '';
  document.getElementById('board-priority-filter').value = '';
  document.getElementById('board-due-filter').value = '';
  document.getElementById('board-created-today-filter').checked = false;
  document.getElementById('board-no-project-filter').checked = false;
  document.getElementById('board-no-tag-filter').checked = false;
  loadBoard();
}

function renderBoard(data) {
  const container = document.getElementById('board-container');
  const today = new Date().toISOString().slice(0,10);
  const hidden = _loadHidden();
  const COLS = [
    { key: 'inbox',    label: '📥 Inbox',     color: 'var(--text-muted)' },
    { key: 'backlog',  label: '🗂 Backlog',   color: '#64748b' },
    { key: 'todo',     label: '⬜ Todo',      color: 'var(--blue)' },
    { key: 'discuss',  label: '💬 Discuss',   color: '#22d3ee' },
    { key: 'wip',      label: '🔄 In corso',  color: 'var(--yellow)' },
    { key: 'waiting',  label: '⏳ Waiting',   color: '#a78bfa' },
    { key: 'blocked',  label: '🚫 Bloccati',  color: 'var(--red)' },
    { key: 'done',     label: '✅ Done',      color: 'var(--green)' },
  ];
  container.innerHTML = COLS.map(col => {
    const allNotes  = data[col.key] || [];
    const visible   = allNotes.filter(n => !hidden.has(n.id));
    const hiddenCol = allNotes.filter(n => hidden.has(n.id));
    const hiddenChip = hiddenCol.length
      ? `<div style="padding:6px 8px;border-top:1px solid var(--border);">
          <button onclick="toggleShowHidden()" style="background:none;border:none;font-size:0.7rem;color:var(--text-muted);cursor:pointer;width:100%;text-align:left;">
            🙈 ${hiddenCol.length} nascost${hiddenCol.length===1?'a':'e'}
          </button>
        </div>`
      : '';
    const shownDimmed = _showHiddenTemp
      ? allNotes.filter(n => _loadHidden().has(n.id)).map(n => boardCard(n, today, true)).join('')
      : '';
    return `
    <div class="board-col" data-status="${col.key}">
      <div class="board-col-header">
        <span class="board-col-title" style="color:${col.color}">${col.label}</span>
        <span class="count-badge" id="col-count-${col.key}">${visible.length}</span>
      </div>
      <div class="board-col-body" data-status="${col.key}">
        ${visible.map(n => boardCard(n, today)).join('')}
        ${shownDimmed}
      </div>
      ${hiddenChip}
    </div>`;
  }).join('');
  initSortable();
}

function initSortable() {
  document.querySelectorAll('.board-col-body').forEach(colBody => {
    Sortable.create(colBody, {
      group: 'board',
      animation: 150,
      ghostClass: 'board-card-ghost',
      chosenClass: 'board-card-chosen',
      dragClass: 'board-card-drag',
      onEnd: async function(evt) {
        const noteId = parseInt(evt.item.dataset.id);
        const toColBody = evt.to;
        const toStatus = toColBody.dataset.status;
        const columnIds = [...toColBody.querySelectorAll('.board-card[data-id]')]
          .map(el => parseInt(el.dataset.id));

        // Update badge counts
        [evt.from, evt.to].forEach(col => {
          const status = col.dataset.status;
          const badge = document.getElementById(`col-count-${status}`);
          if (badge) badge.textContent = col.querySelectorAll('.board-card[data-id]').length;
        });

        try {
          await apiFetch(`/api/notes/${noteId}/move`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: toStatus, column_ids: columnIds }),
          });
        } catch(e) {
          toast('Errore aggiornamento posizione', 'error');
          loadBoard();
        }
      }
    });
  });
}

function boardCard(n, today, dimmed = false) {
  const assigneeHtml = _parseAssignees(n.assignee).map(a => `<span class="assignee-badge">@${escHtml(a)}</span>`).join('');
  const projHtml = n.project ? `<span class="project-badge">${escHtml(n.project)}</span>` : '';
  const dueHtml = n.due_date ? `<span class="due-date ${n.due_date < today ? 'overdue' : (n.due_date === today ? 'soon' : '')}" style="font-size:0.65rem">📅 ${n.due_date}</span>` : '';
  const hideHtml = dimmed
    ? `<button class="hide-btn" style="opacity:1;color:var(--accent);margin-left:auto;" onclick="event.stopPropagation();unhideNote(${n.id})" title="Mostra nota">👁</button>`
    : `<button class="hide-btn" onclick="event.stopPropagation();hideNote(${n.id})" title="Nascondi nota">🙈</button>
       <button class="delete-btn" onclick="event.stopPropagation();deleteNote(${n.id})" title="Elimina">✕</button>`;
  return `
  <div class="board-card priority-${n.priority}${dimmed ? ' shown-hidden' : ''}" data-id="${n.id}" onclick="openNoteFromCard(event,${n.id},'${n.created_at}')" style="${dimmed ? 'pointer-events:auto;' : ''}">
    <div class="board-card-content" onclick="event.stopPropagation();startEdit(this,${n.id})" title="Clicca per modificare">${escHtml(n.content)}</div>
    <div class="board-card-meta">
      ${projHtml}${assigneeHtml}
      <span class="status status-${n.status}" onclick="event.stopPropagation();cycleStatus(${n.id},'${n.status||''}')" title="Avanza stato" style="cursor:pointer">${STATUS_LABEL[n.status]||''}</span>
      ${dueHtml}
      <span style="margin-left:auto;display:flex;gap:4px;align-items:center;">${hideHtml}</span>
    </div>
  </div>`;
}

// ── Inline edit: tags, project, assignee ─────────────────────────────────────
function editTags(container, noteId, currentTags) {
  const input = document.createElement('input');
  input.type = 'text';
  input.value = currentTags;
  input.placeholder = 'tag1, tag2, ...';
  input.style.cssText = 'background:var(--surface2);border:1px solid var(--accent);border-radius:6px;color:var(--text);font-size:0.72rem;padding:2px 8px;outline:none;min-width:120px;max-width:200px;';
  container.replaceWith(input);
  input.focus();
  input.select();
  const reload = () => activeTab === 'due' ? loadDueNotes() : loadNotes();
  async function save() {
    const val = normalizeTags(input.value);
    try {
      await patchNote(noteId, { tags: val });
    } catch { toast('Errore aggiornamento tag', 'error'); }
    reload();
  }
  input.onblur = save;
  input.onkeydown = e => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') reload();
  };
}

function editProject(el, noteId, currentProject) {
  const input = document.createElement('input');
  input.type = 'text';
  input.value = currentProject;
  input.placeholder = 'progetto';
  input.style.cssText = 'background:var(--surface2);border:1px solid var(--accent);border-radius:6px;color:var(--text);font-size:0.72rem;padding:2px 8px;outline:none;width:120px;';
  el.replaceWith(input);
  input.focus();
  input.select();
  const reload = () => activeTab === 'due' ? loadDueNotes() : loadNotes();
  async function save() {
    const raw = input.value.trim();
    const val = raw ? normalizeProject(raw) : '';
    try {
      await patchNote(noteId, { project: val });
      if (val) toast(`Progetto: ${val}`); else toast('Progetto rimosso');
    } catch { toast('Errore aggiornamento progetto', 'error'); }
    reload();
  }
  input.onblur = save;
  input.onkeydown = e => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') reload();
  };
}

function editAssignee(el, noteId, currentAssignee) {
  // Click on any of the multiple badges → edit the whole assignee string
  // Find the container that holds all the badges for this note
  const container = el.parentElement;
  const allBadges = [...container.querySelectorAll('.assignee-badge')];

  const input = document.createElement('input');
  input.type = 'text';
  // Show as "@mario @luigi" for readability
  const names = _parseAssignees(currentAssignee);
  input.value = names.map(n => '@' + n).join(' ');
  input.placeholder = '@persona1 @persona2';
  input.style.cssText = 'background:var(--surface2);border:1px solid var(--accent);border-radius:6px;color:var(--text);font-size:0.72rem;padding:2px 8px;outline:none;width:140px;';
  // Replace only the first badge, remove the rest
  allBadges[0].replaceWith(input);
  allBadges.slice(1).forEach(b => b.remove());
  input.focus();
  input.select();

  const reload = () => activeTab === 'due' ? loadDueNotes() : loadNotes();
  async function save() {
    const merged = _parseAssignees(input.value).join(',');
    try {
      await patchNote(noteId, { assignee: merged });
      if (merged) toast(merged.split(',').map(a=>'@'+a).join(' '), 'success');
      else toast('Assignee rimosso');
    } catch { toast('Errore aggiornamento assignee', 'error'); }
    reload();
  }
  input.onblur = save;
  input.onkeydown = e => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') reload();
  };
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  const tag = document.activeElement.tagName;
  const isEditing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || document.activeElement.contentEditable === 'true';

  if (e.key === 'Escape') {
    if (document.getElementById('voice-modal').classList.contains('show')) {
      _closeVoiceModal();
    } else if (document.getElementById('shortcuts-modal').classList.contains('show')) {
      closeShortcuts();
    } else if (document.getElementById('settings-modal').classList.contains('open')) {
      closeSettings();
    } else if (isEditing) {
      document.activeElement.blur();
    }
    return;
  }

  if (isEditing) return;

  if (e.key === 'n' || e.key === 'N') {
    e.preventDefault();
    switchTab('notes');
    setTimeout(() => document.getElementById('note-input').focus(), 50);
  }
  if (e.key === '1') { e.preventDefault(); switchTab('notes'); }
  if (e.key === '2') { e.preventDefault(); switchTab('board'); }
  if (e.key === '3') { e.preventDefault(); switchTab('gantt'); }
  if (e.key === '4') { e.preventDefault(); switchTab('docs'); }
  if (e.key === '7') { e.preventDefault(); switchTab('editor'); }
  if (e.key === ',') { e.preventDefault(); openSettings(); }
  if (e.key === '?') { e.preventDefault(); toggleShortcuts(); }
});

// ── Confirm modal ─────────────────────────────────────────────────────────────
let _confirmResolve = null;

function showConfirm(title, body, confirmLabel = 'Elimina') {
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-body').innerHTML = body;
  document.getElementById('confirm-ok').textContent = confirmLabel;
  document.getElementById('confirm-modal').classList.add('show');
  return new Promise(resolve => {
    _confirmResolve = resolve;
    document.getElementById('confirm-ok').onclick = () => {
      document.getElementById('confirm-modal').classList.remove('show');
      _confirmResolve = null;
      resolve(true);
    };
  });
}

function closeConfirm(e) {
  if (e && e.target !== document.getElementById('confirm-modal')) return;
  document.getElementById('confirm-modal').classList.remove('show');
  if (_confirmResolve) { _confirmResolve(false); _confirmResolve = null; }
}

function toggleShortcuts() {
  document.getElementById('shortcuts-modal').classList.toggle('show');
}

function closeShortcuts(e) {
  if (!e || e.target === document.getElementById('shortcuts-modal')) {
    document.getElementById('shortcuts-modal').classList.remove('show');
  }
}

function openSettings() {
  document.getElementById('settings-modal').classList.add('open');
  loadOllamaSettings();
  loadDocRoot();
  initSchedule();
}
function closeSettings(e) {
  if (e && e.target !== document.getElementById('settings-modal')) return;
  document.getElementById('settings-modal').classList.remove('open');
}

function goToNote(e, dateStr, noteId = null) {
  if (e) e.preventDefault();
  switchTab('notes');
  if (noteId) pendingHighlightNoteId = noteId;
  navigateToDate(String(dateStr).slice(0, 10));
}

function openNoteFromCard(e, noteId, createdAt) {
  if (e?.target?.closest('button,input,select,textarea,a,[contenteditable="true"]')) return;
  goToNote(e, createdAt, noteId);
}

function highlightPendingNote() {
  if (!pendingHighlightNoteId) return;
  const target = document.querySelector(`.note-item[data-id="${pendingHighlightNoteId}"]`);
  if (!target) return;
  pendingHighlightNoteId = null;
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.add('note-highlight');
  setTimeout(() => target.classList.remove('note-highlight'), 1800);
}

// ── Gantt ─────────────────────────────────────────────────────────────────────
const GANTT_COLORS = ['#818cf8','#60a5fa','#34d399','#fbbf24','#f87171','#a78bfa','#fb923c','#2dd4bf','#f472b6','#a3e635'];
let ganttSelectedColor = GANTT_COLORS[0];
let ganttData = null;
let ganttZoom = 'auto';

function setGanttZoom(z) {
  ganttZoom = z;
  document.querySelectorAll('.gantt-zoom-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`zoom-${z}`).classList.add('active');
  if (ganttData) renderGanttChart(ganttData);
}

(function initColorPicker() {
  const picker = document.getElementById('gantt-color-picker');
  if (!picker) return;
  GANTT_COLORS.forEach((c, i) => {
    const d = document.createElement('div');
    d.className = 'gantt-color-swatch' + (i === 0 ? ' selected' : '');
    d.style.background = c;
    d.onclick = () => {
      ganttSelectedColor = c;
      picker.querySelectorAll('.gantt-color-swatch').forEach(s => s.classList.remove('selected'));
      d.classList.add('selected');
    };
    picker.appendChild(d);
  });
})();

async function loadGantt() {
  try {
    const res = await apiFetch('/api/gantt');
    ganttData = await res.json();
    renderGanttPanel(ganttData);
    renderGanttChart(ganttData);
  } catch(e) { console.error(e); }
}

function renderGanttPanel(data) {
  const list = document.getElementById('gantt-projects-list');
  if (!data.projects.length) {
    list.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem;padding:8px 0">Nessun progetto. Aggiungine uno qui sotto.</div>';
    return;
  }
  // Sezione archivio in fondo
  const archivedHtml = (data.archived_projects && data.archived_projects.length) ? `
    <div class="gantt-archive-section" id="gantt-archive-section">
      <button class="gantt-archive-toggle" onclick="toggleGanttArchive()" id="gantt-archive-toggle">
        📦 Archivio <span style="font-size:0.68rem;background:var(--surface2);border-radius:10px;padding:1px 7px;margin-left:4px;">${data.archived_projects.length}</span>
        <span id="gantt-archive-chevron" style="margin-left:auto;font-size:0.7rem;color:var(--text-dim);">▶</span>
      </button>
      <div id="gantt-archive-list" style="display:none;flex-direction:column;gap:4px;padding:4px 0;">
        ${data.archived_projects.map(p => `
          <div class="gantt-archived-item">
            <div class="gantt-project-dot" style="background:${p.color};opacity:0.5;"></div>
            <span style="flex:1;font-size:0.78rem;color:var(--text-muted);">${escHtml(p.name)}</span>
            <button onclick="unarchiveGanttProject(${p.id},event)" title="Ripristina progetto" style="background:none;border:1px solid var(--border);border-radius:5px;color:var(--text-muted);font-size:0.68rem;padding:2px 8px;cursor:pointer;transition:all 0.15s;" onmouseover="this.style.borderColor='var(--accent)';this.style.color='var(--accent)'" onmouseout="this.style.borderColor='var(--border)';this.style.color='var(--text-muted)'">↩ ripristina</button>
          </div>
        `).join('')}
      </div>
    </div>` : '';

  list.innerHTML = data.projects.map(p => `
    <div class="gantt-project-item">
      <div class="gantt-project-header">
        <div class="gantt-project-dot" style="background:${p.color}"></div>
        <span class="gantt-project-name">${escHtml(p.name)}</span>
        ${p.is_background ? `<span style="font-size:0.62rem;background:var(--surface2);border:1px solid var(--border);border-radius:4px;padding:1px 5px;color:var(--text-muted);margin-left:2px;">sfondo</span>` : ''}
        <button class="gantt-project-archive" onclick="archiveGanttProject(${p.id},event)" title="Archivia progetto" style="opacity:0;transition:opacity 0.15s;">📦</button>
        <button class="gantt-project-del" onclick="deleteGanttProject(${p.id},event)" title="Elimina progetto">✕</button>
      </div>
      <div class="gantt-milestones-list">
        ${p.milestones.map(m => `
          <div class="gantt-ms-item" data-mid="${m.id}" onclick="editGanttMilestone(${m.id})" title="Clicca per modificare date e nome">
            <span style="width:6px;height:6px;border-radius:50%;background:${p.color};flex-shrink:0;display:inline-block;margin-top:4px"></span>
            <div class="gantt-ms-body">
              <span>${escHtml(m.name)}</span>
              <span class="gantt-ms-dates">${m.start_date} → ${m.end_date}</span>
              <span class="gantt-ms-progress-row" title="${m.progress_done || 0}/${m.progress_total || 0} note completate">
                <span class="gantt-ms-progress"><span style="width:${m.progress || 0}%"></span></span>
                <span class="gantt-ms-progress-label">${m.progress || 0}%</span>
              </span>
              ${m.linked_notes && m.linked_notes.length ? `<span style="font-size:0.62rem;background:var(--accent-dim);color:var(--accent);border-radius:4px;padding:1px 5px;margin-left:4px;">📎 ${m.linked_notes.length}</span>` : ''}
            </div>
            <button class="gantt-ms-del" onclick="event.stopPropagation();deleteMilestone(${m.id},event)" title="Elimina">✕</button>
          </div>
        `).join('')}
      </div>
      <button class="gantt-add-ms-btn" onclick="toggleAddMilestone(${p.id},this)">+ milestone</button>
      <form class="gantt-add-ms-form" id="gantt-ms-form-${p.id}" onsubmit="addMilestone(event,${p.id})">
        <input class="gantt-input" name="name" placeholder="Nome milestone" maxlength="80" required style="font-size:0.75rem;padding:3px 7px;">
        <div style="display:flex;gap:4px;">
          <input class="gantt-input" type="date" name="start" required style="font-size:0.75rem;padding:3px 7px;">
          <input class="gantt-input" type="date" name="end" required style="font-size:0.75rem;padding:3px 7px;">
        </div>
        <div style="display:flex;gap:4px;">
          <button type="submit" class="gantt-btn-sm">Aggiungi</button>
          <button type="button" class="gantt-btn-sm" onclick="toggleAddMilestone(${p.id},this.closest('form').previousElementSibling)">Annulla</button>
        </div>
      </form>
    </div>
  `).join('') + archivedHtml;
}

function toggleGanttArchive() {
  const list = document.getElementById('gantt-archive-list');
  const chevron = document.getElementById('gantt-archive-chevron');
  const open = list.style.display === 'none';
  list.style.display = open ? 'flex' : 'none';
  chevron.textContent = open ? '▼' : '▶';
}

async function archiveGanttProject(id, e) {
  e.stopPropagation();
  try {
    await apiFetch(`/api/gantt/projects/${id}/archive`, { method: 'PATCH' });
    toast('Progetto archiviato', 'success');
    await loadGantt();
  } catch { toast('Errore', 'error'); }
}

async function unarchiveGanttProject(id, e) {
  e.stopPropagation();
  try {
    await apiFetch(`/api/gantt/projects/${id}/unarchive`, { method: 'PATCH' });
    toast('Progetto ripristinato', 'success');
    await loadGantt();
  } catch { toast('Errore', 'error'); }
}

function toggleAddMilestone(projectId, btn) {
  const form = document.getElementById(`gantt-ms-form-${projectId}`);
  form.classList.toggle('open');
}

function renderGanttChart(data) {
  const chart = document.getElementById('gantt-chart');
  if (!data.projects.length || !data.projects.some(p => p.milestones.length)) {
    chart.innerHTML = '<div class="gantt-empty">Aggiungi un progetto e le sue milestone per visualizzare il Gantt.<br>Le note con scadenza appariranno come ◆ sulla timeline.</div>';
    return;
  }

  // Calculate date range
  let minDate = null, maxDate = null;
  for (const p of data.projects) {
    for (const m of p.milestones) {
      if (!minDate || m.start_date < minDate) minDate = m.start_date;
      if (!maxDate || m.end_date > maxDate) maxDate = m.end_date;
    }
  }
  if (!minDate) { chart.innerHTML = '<div class="gantt-empty">Aggiungi delle milestone per visualizzare il Gantt.</div>'; return; }

  // Add padding
  const startD = new Date(minDate + 'T00:00:00'); startD.setDate(startD.getDate() - 3);
  const endD = new Date(maxDate + 'T00:00:00'); endD.setDate(endD.getDate() + 7);
  const totalMs = endD - startD;
  const totalDays = totalMs / 86400000;

  function pct(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    return Math.max(0, Math.min(100, (d - startD) / totalMs * 100)).toFixed(2);
  }
  // Sempre data locale (evita offset UTC in CEST/CET)
  function _lds(d) {
    return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
  }

  const _now = new Date();
  const todayStr = _lds(_now);
  const _warnD = new Date(_now); _warnD.setDate(_warnD.getDate()+7);
  const warnCutoff = _lds(_warnD);

  // Compute at-risk milestones (end_date within 7 days + project has blocked/wip notes)
  const atRiskList = [];
  for (const p of data.projects) {
    for (const m of p.milestones) {
      m._atRisk = p.has_risk_blocker && m.end_date >= todayStr && m.end_date <= warnCutoff;
      m._overdue = m.end_date < todayStr;
      if (m._atRisk) atRiskList.push({ project: p.name, milestone: m.name, end: m.end_date });
    }
  }

  // Build scale header marks
  const zoom = ganttZoom === 'auto'
    ? (totalDays < 60 ? 'day' : totalDays < 180 ? 'week' : 'month')
    : ganttZoom;
  const oneDayPct = 1 / totalDays * 100;

  let scaleMarks = '', monthMarks = '', weekendBandsHtml = '';
  let headerHeight = '20px';

  if (zoom === 'day') {
    headerHeight = '36px';
    // Month row (top): one block per calendar month
    const mCur = new Date(startD.getFullYear(), startD.getMonth(), 1);
    while (mCur <= endD) {
      const clampedStart = mCur < startD ? startD : mCur;
      const nextM = new Date(mCur.getFullYear(), mCur.getMonth()+1, 1);
      const clampedEnd = nextM > endD ? endD : nextM;
      const left = pct(_lds(clampedStart));
      const right = pct(_lds(clampedEnd));
      const width = Math.max(0, parseFloat(right) - parseFloat(left)).toFixed(2);
      const label = mCur.toLocaleDateString('it-IT', {month:'long', year:'numeric'});
      monthMarks += `<div class="gantt-month-mark" style="left:${left}%;width:${width}%;top:0;height:16px;">${label}</div>`;
      mCur.setMonth(mCur.getMonth()+1);
    }
    // Day row (bottom) + weekend bands
    const dCur = new Date(startD);
    while (dCur <= endD) {
      const dow = dCur.getDay();
      const isWeekend = dow === 0 || dow === 6;
      const left = pct(_lds(dCur));
      const w = oneDayPct.toFixed(2);
      const cls = isWeekend ? 'weekend' : 'workday';
      scaleMarks += `<div class="gantt-day-mark ${cls}" style="left:${left}%;width:${w}%;top:18px;height:18px;">${dCur.getDate()}</div>`;
      if (isWeekend) {
        weekendBandsHtml += `<div class="gantt-weekend-band" style="left:${left}%;width:${w}%;"></div>`;
      }
      dCur.setDate(dCur.getDate()+1);
    }
  } else {
    // Week/month zoom — single row, weekend bands for week zoom
    const cur = new Date(startD);
    while (cur <= endD) {
      const left = pct(_lds(cur));
      const width = zoom === 'week' ? (7/totalDays*100).toFixed(2)
                  : (() => {
                      const dim = new Date(cur.getFullYear(), cur.getMonth()+1, 0).getDate();
                      return (dim/totalDays*100).toFixed(2);
                    })();
      const label = zoom === 'week'
        ? `W${getWeekNumber(cur)} · ${cur.toLocaleDateString('it-IT', {day:'2-digit',month:'2-digit'})}`
        : cur.toLocaleDateString('it-IT', {month:'short', year:'2-digit'});
      scaleMarks += `<div class="gantt-scale-mark" style="left:${left}%;width:${width}%">${label}</div>`;
      if (zoom === 'week') cur.setDate(cur.getDate()+7);
      else cur.setMonth(cur.getMonth()+1);
    }
    // Weekend bands for week view
    if (zoom === 'week') {
      const wCur = new Date(startD);
      while (wCur <= endD) {
        const dow = wCur.getDay();
        if (dow === 6 || dow === 0) {
          const left = pct(_lds(wCur));
          weekendBandsHtml += `<div class="gantt-weekend-band" style="left:${left}%;width:${oneDayPct.toFixed(2)}%;"></div>`;
        }
        wCur.setDate(wCur.getDate()+1);
      }
    }
  }

  // Today line
  const todayLeft = pct(todayStr);
  const todayLine = `<div class="gantt-today-line" style="left:${todayLeft}%" title="Oggi"></div>`;

  // Build background bands (ferie, etc.) — rendered as absolute overlays
  const bgProjects = data.projects.filter(p => p.is_background && p.milestones.length);
  let bgBandsHtml = bgProjects.flatMap(p => p.milestones.map(m => {
    const left = pct(m.start_date);
    const endExcl = new Date(m.end_date + 'T00:00:00'); endExcl.setDate(endExcl.getDate()+1);
    const width = Math.max(parseFloat(pct(_lds(endExcl))) - parseFloat(left), oneDayPct).toFixed(2);
    const col = p.color;
    return `<div class="gantt-bg-band" style="left:${left}%;width:${width}%;background:${col};border-color:${col};"></div>
            <div class="gantt-bg-label" style="left:${left}%;width:${width}%;color:${col};">${escHtml(p.name)}: ${escHtml(m.name)}</div>`;
  })).join('');

  // Build rows (normal projects only)
  let rowsHtml = '';
  for (const p of data.projects) {
    if (p.is_background || !p.milestones.length) continue;
    // Project label row
    rowsHtml += `
    <div class="gantt-row" style="margin-bottom:2px;margin-top:12px;position:relative;z-index:1;">
      <div class="gantt-row-label project">${escHtml(p.name)}</div>
      <div class="gantt-row-track" style="height:4px;"><div class="gantt-track-bg" style="opacity:0.3"></div>${todayLine}</div>
    </div>`;

    // Milestone rows
    for (const m of p.milestones) {
      const barLeft = pct(m.start_date);
      const barRight = pct(m.end_date);
      const barWidth = Math.max(parseFloat(barRight) - parseFloat(barLeft), oneDayPct).toFixed(2);
      const riskBadge = m._atRisk ? ' ⚠️' : '';
      const riskStyle = m._atRisk
        ? `outline: 2px solid var(--yellow); outline-offset: 1px;`
        : m._overdue ? `opacity:0.6;` : '';
      const labelStyle = m._atRisk ? 'color:var(--yellow);font-weight:600;' : '';
      rowsHtml += `
      <div class="gantt-row">
        <div class="gantt-row-label" title="${escHtml(m.name)}" style="${labelStyle}">${escHtml(m.name)}${riskBadge}</div>
        <div class="gantt-row-track">
          <div class="gantt-track-bg"></div>
          ${todayLine}
          <div class="gantt-bar" style="left:${barLeft}%;width:${barWidth}%;background:${p.color};${riskStyle}" title="${m.start_date} → ${m.end_date} · ${m.progress || 0}% completato">
            <span class="gantt-bar-progress" style="width:${m.progress || 0}%"></span>
            <span class="gantt-bar-label">${escHtml(m.name)}${riskBadge} · ${m.progress || 0}%</span>
          </div>
        </div>
      </div>`;
      // Sub-task notes linked to this milestone
      if (m.linked_notes && m.linked_notes.length) {
        for (const ln of m.linked_notes) {
          const lnDate = ln.due_date || ln.created_at;
          const lnLeft = pct(lnDate);
          const statusIcon = {todo:'⬜',discuss:'💬',wip:'🔄',done:'✅',waiting:'⏳',blocked:'🚫',backlog:'🗂'}[ln.status] || '·';
          const doneStyle = ln.status === 'done' ? 'opacity:0.4;text-decoration:line-through' : '';
          rowsHtml += `
          <div class="gantt-row gantt-subnote-row">
            <div class="gantt-row-label" style="${doneStyle};padding-left:18px;font-size:0.64rem;gap:4px;">
              <span style="font-size:0.7em;">${statusIcon}</span>
              <a href="#" onclick="goToNote(event,'${ln.created_at}')" title="${escHtml(ln.content)}"
                 style="color:var(--text-dim);text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                 onmouseover="this.style.color='var(--accent)'"
                 onmouseout="this.style.color='var(--text-dim)'">${escHtml(ln.content.length > 30 ? ln.content.slice(0,30)+'…' : ln.content)}</a>
            </div>
            <div class="gantt-row-track" style="height:20px;">
              ${todayLine}
              <div class="gantt-subnote-pin" style="left:${lnLeft}%;background:${p.color};${ln.status==='done'?'opacity:0.35':''}" title="${escHtml(ln.content)} (${lnDate})"></div>
            </div>
          </div>`;
        }
      }
    }

    // One row per note with due_date
    for (const n of p.notes) {
      const noteLeft = pct(n.due_date);
      const assigneeTip = n.assignee ? ` · @${n.assignee}` : '';
      const tooltip = `#${n.id} ${n.content} (${n.due_date})${assigneeTip}`;
      const labelText = `#${n.id} ${n.content.length > 28 ? n.content.slice(0, 28) + '…' : n.content}`;
      const doneStyle = n.status === 'done' ? 'opacity:0.45;text-decoration:line-through' : '';
      rowsHtml += `
      <div class="gantt-row gantt-notes-row">
        <div class="gantt-row-label" style="${doneStyle}">
          <a href="#" onclick="goToNote(event,'${n.created_at}')" title="${escHtml(tooltip)}" style="color:var(--text-dim);text-decoration:none;font-size:0.68rem;font-style:italic;" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='var(--text-dim)'">${escHtml(labelText)}</a>
        </div>
        <div class="gantt-row-track" style="height:24px;">
          ${todayLine}
          <div class="gantt-diamond overdue" style="left:${noteLeft}%;background:var(--red);${n.status==='done'?'opacity:0.35':''}" title="${escHtml(tooltip)}"></div>
        </div>
      </div>`;
    }
  }

  const warningPanel = atRiskList.length ? `
  <div style="background:rgba(234,179,8,0.08);border:1px solid var(--yellow);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:0.78rem;">
    <div style="font-weight:700;color:var(--yellow);margin-bottom:6px;">⚠️ ${atRiskList.length} milestone a rischio</div>
    ${atRiskList.map(r => `<div style="color:var(--text-muted);margin-bottom:2px;">· <strong style="color:var(--text)">${escHtml(r.project)}</strong> — ${escHtml(r.milestone)} <span style="color:var(--red)">(scade ${r.end})</span></div>`).join('')}
  </div>` : '';

  chart.innerHTML = warningPanel + `
  <div class="gantt-container">
    <div class="gantt-header-row">
      <div class="gantt-label-col"></div>
      <div class="gantt-scale" style="position:relative;height:${headerHeight};">
        ${monthMarks}
        ${scaleMarks}
      </div>
    </div>
    <div class="gantt-body" style="position:relative;">
      <div style="position:absolute;left:180px;right:0;top:0;bottom:0;overflow:hidden;pointer-events:none;z-index:0;">
        ${weekendBandsHtml}
        ${bgBandsHtml}
      </div>
      ${rowsHtml}
    </div>
  </div>`;
}

function getWeekNumber(d) {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  return Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
}

async function addGanttProject() {
  const name = normalizeProject(document.getElementById('gantt-proj-name').value);
  if (!name) return;
  const is_background = document.getElementById('gantt-proj-background').checked;
  try {
    await apiFetch('/api/gantt/projects', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name, color: ganttSelectedColor, is_background}),
    });
    document.getElementById('gantt-proj-name').value = '';
    document.getElementById('gantt-proj-background').checked = false;
    toast('Progetto aggiunto', 'success');
    await loadGantt();
  } catch { toast('Errore', 'error'); }
}

async function deleteGanttProject(id, e) {
  e.stopPropagation();
  try {
    await fetch(`/api/gantt/projects/${id}`, {method:'DELETE'});
    toast('Progetto eliminato');
    await loadGantt();
  } catch { toast('Errore eliminazione', 'error'); }
}

function editMilestone(e, noteId, currentMsId, project) {
  e.stopPropagation();
  const existing = document.getElementById('ms-picker');
  if (existing) { const prev = existing._noteId; existing.remove(); if (prev === noteId) return; }
  if (!project) { toast('Imposta prima un progetto sulla nota', 'info'); return; }

  const btn = e.currentTarget;
  const rect = btn.getBoundingClientRect();
  const picker = document.createElement('div');
  picker.id = 'ms-picker';
  picker._noteId = noteId;
  picker.style.cssText = `position:fixed;top:${rect.bottom + 4}px;left:${rect.left}px;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:4px;z-index:1000;min-width:200px;box-shadow:0 4px 20px rgba(0,0,0,0.35);`;
  picker.innerHTML = `
    <div style="padding:3px 8px 5px;font-size:0.62rem;color:var(--text-dim);font-weight:700;text-transform:uppercase;letter-spacing:0.05em;">Collega a milestone</div>
    <div class="ms-pick-item${!currentMsId?' ms-pick-active':''}" onclick="setNoteMilestone(${noteId},null)">— nessuna</div>
    <div id="ms-pick-body"><div style="padding:6px 10px;font-size:0.72rem;color:var(--text-muted);">Caricamento…</div></div>`;
  document.body.appendChild(picker);

  const closeHandler = (ev) => {
    if (!picker.contains(ev.target)) { picker.remove(); document.removeEventListener('click', closeHandler); }
  };
  setTimeout(() => document.addEventListener('click', closeHandler), 0);

  apiFetch(`/api/gantt/milestones/for-project?project=${encodeURIComponent(project)}`)
    .then(r => r.json()).then(data => {
      const body = document.getElementById('ms-pick-body');
      if (!body) return;
      if (!data.milestones.length) {
        body.innerHTML = `<div style="padding:6px 10px;font-size:0.72rem;color:var(--text-muted);">Nessuna milestone per "${project}"</div>`;
        return;
      }
      body.innerHTML = data.milestones.map(m =>
        `<div class="ms-pick-item${m.id===currentMsId?' ms-pick-active':''}" onclick="setNoteMilestone(${noteId},${m.id})">🏁 ${escHtml(m.name)} <span style="opacity:0.5;font-size:0.68rem">→ ${m.end_date}</span></div>`
      ).join('');
    });
}

async function setNoteMilestone(noteId, milestoneId) {
  const picker = document.getElementById('ms-picker');
  if (picker) picker.remove();
  try {
    await apiFetch(`/api/notes/${noteId}`, {
      method: 'PATCH',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(milestoneId ? {milestone_id: milestoneId} : {clear_milestone: true})
    });
    await loadNotes();
    toast(milestoneId ? 'Nota collegata alla milestone' : 'Milestone rimossa', 'success');
  } catch { toast('Errore', 'error'); }
}

async function addMilestone(e, projectId) {
  e.preventDefault();
  const form = e.target;
  const name = form.name.value.trim();
  const start = form.start.value;
  const end = form.end.value;
  if (!name || !start || !end) return;
  try {
    await apiFetch('/api/gantt/milestones', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({project_id: projectId, name, start_date: start, end_date: end}),
    });
    form.reset();
    form.classList.remove('open');
    toast('Milestone aggiunta', 'success');
    await loadGantt();
  } catch { toast('Errore', 'error'); }
}

function editGanttMilestone(milestoneId) {
  if (!ganttData) return;
  let milestone = null;
  for (const project of ganttData.projects) {
    milestone = project.milestones.find(m => m.id === milestoneId);
    if (milestone) break;
  }
  if (!milestone) return;

  const item = document.querySelector(`.gantt-ms-item[data-mid="${milestoneId}"]`);
  if (!item || item.classList.contains('editing')) return;
  item.classList.add('editing');
  item.innerHTML = `
    <form class="gantt-ms-edit-form" onsubmit="saveGanttMilestone(event,${milestoneId})">
      <input class="gantt-input" name="name" value="${escHtml(milestone.name)}" maxlength="80" required>
      <div class="gantt-ms-edit-dates">
        <input class="gantt-input" type="date" name="start" value="${milestone.start_date}" required>
        <input class="gantt-input" type="date" name="end" value="${milestone.end_date}" required>
      </div>
      <div class="gantt-ms-edit-actions">
        <button type="submit" class="gantt-btn-sm">Salva</button>
        <button type="button" class="gantt-btn-sm" onclick="event.stopPropagation();loadGantt()">Annulla</button>
      </div>
    </form>
  `;
  item.querySelector('input[name="start"]').focus();
}

async function saveGanttMilestone(e, milestoneId) {
  e.preventDefault();
  e.stopPropagation();
  const form = e.target;
  const name = form.name.value.trim();
  const start = form.start.value;
  const end = form.end.value;
  if (!name || !start || !end) return;
  try {
    const res = await apiFetch(`/api/gantt/milestones/${milestoneId}`, {
      method: 'PATCH',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name, start_date: start, end_date: end}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Errore');
    }
    toast('Milestone aggiornata', 'success');
    await loadGantt();
    if (activeTab === 'due') await loadDueNotes();
    if (activeTab === 'focus') await loadFocus();
  } catch(err) {
    toast(err.message || 'Errore aggiornamento milestone', 'error');
  }
}

async function deleteMilestone(id, e) {
  e.stopPropagation();
  try {
    await fetch(`/api/gantt/milestones/${id}`, {method:'DELETE'});
    toast('Milestone eliminata');
    await loadGantt();
  } catch { toast('Errore eliminazione', 'error'); }
}

// ── Dependencies ──────────────────────────────────────────────────────────────
const STATUS_ICON = {backlog:'🗂',todo:'⬜',wip:'🔄',waiting:'⏳',blocked:'🚫',done:'✅'};
let _openDepsPanel = null;

async function toggleDepsPanel(noteId) {
  const panel = document.getElementById(`deps-panel-${noteId}`);
  if (!panel) return;
  if (panel.classList.contains('open')) {
    panel.classList.remove('open');
    _openDepsPanel = null;
    return;
  }
  // Close any other open panel
  if (_openDepsPanel && _openDepsPanel !== noteId) {
    const prev = document.getElementById(`deps-panel-${_openDepsPanel}`);
    if (prev) prev.classList.remove('open');
  }
  _openDepsPanel = noteId;
  panel.innerHTML = '<div style="color:var(--text-dim);font-size:0.78rem;padding:4px 0;">Carico…</div>';
  panel.classList.add('open');
  await refreshDepsPanel(noteId);
}

async function refreshDepsPanel(noteId) {
  const panel = document.getElementById(`deps-panel-${noteId}`);
  if (!panel || !panel.classList.contains('open')) return;
  const res = await apiFetch(`/api/notes/${noteId}/deps`);
  const data = await res.json();

  const renderList = (items, isBlocker) => items.length ? items.map(n => {
    const icon = STATUS_ICON[n.status] || '';
    const label = isBlocker ? 'Rimuovi blocker' : 'Rimuovi';
    const removeCall = isBlocker
      ? `removeDep(${noteId}, ${n.id})`
      : `removeDep(${n.id}, ${noteId})`;
    return `<div class="dep-item">
      <span class="dep-item-id">#${n.id}</span>
      <span class="dep-item-content" title="${escHtml(n.content)}">${escHtml(n.content)}</span>
      ${n.status ? `<span class="dep-item-status status-${n.status}">${icon} ${n.status}</span>` : ''}
      <button class="dep-remove-btn" onclick="${removeCall}" title="${label}">✕</button>
    </div>`;
  }).join('') : '<div style="color:var(--text-dim);font-size:0.75rem;padding:2px 0;">Nessuna</div>';

  panel.innerHTML = `
    <div class="deps-section-title">🚫 Bloccata da</div>
    ${renderList(data.blockers, true)}
    <div class="deps-section-title">▶ Blocca</div>
    ${renderList(data.blocking, false)}
    <div class="deps-section-title">Aggiungi blocker</div>
    <input class="dep-search-input" id="dep-search-${noteId}" placeholder="Cerca per ID o testo…" oninput="searchDeps(${noteId})" autocomplete="off">
    <div id="dep-results-${noteId}" class="dep-search-results" style="display:none;"></div>`;

  // Refresh chips too
  _refreshDepChips(noteId, data);
}

function _refreshDepChips(noteId, data) {
  const row = document.getElementById(`deps-chips-${noteId}`);
  if (!row) return;
  const bl = data.blockers.length, bk = data.blocking.length;
  row.style.marginTop = (bl || bk) ? '5px' : '0';
  row.innerHTML = `
    ${bl ? `<span class="dep-chip blocker" onclick="toggleDepsPanel(${noteId})">🚫 ${bl} blocker${bl>1?'s':''}</span>` : ''}
    ${bk ? `<span class="dep-chip blocking" onclick="toggleDepsPanel(${noteId})">▶ blocca ${bk}</span>` : ''}
    <span class="dep-chip add-dep" onclick="toggleDepsPanel(${noteId})">+ dipendenza</span>`;
}

let _depSearchTimer = null;
async function searchDeps(noteId) {
  clearTimeout(_depSearchTimer);
  _depSearchTimer = setTimeout(async () => {
    const q = document.getElementById(`dep-search-${noteId}`)?.value.trim();
    const resultsEl = document.getElementById(`dep-results-${noteId}`);
    if (!resultsEl) return;
    if (!q) { resultsEl.style.display = 'none'; return; }

    // Search by ID or text
    let url = `/api/notes?`;
    const numQ = parseInt(q);
    if (!isNaN(numQ) && String(numQ) === q) {
      // lookup by ID: fetch all and filter client-side (no search-by-id endpoint)
      url += `tag=&`;
    }
    const res = await apiFetch(`/api/search?q=${encodeURIComponent(q)}&limit=8`);
    if (!res.ok) { resultsEl.style.display = 'none'; return; }
    const notes = await res.json();
    const filtered = notes.filter(n => n.id !== noteId);
    if (!filtered.length) { resultsEl.innerHTML = '<div style="padding:8px 10px;color:var(--text-dim);font-size:0.78rem;">Nessun risultato</div>'; resultsEl.style.display = 'block'; return; }
    resultsEl.style.display = 'block';
    resultsEl.innerHTML = filtered.map(n => `
      <div class="dep-search-item" onclick="addDep(${noteId}, ${n.id})">
        <span class="dep-item-id">#${n.id}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtml(n.content)}</span>
        ${n.status ? `<span class="dep-item-status status-${n.status}">${STATUS_ICON[n.status]||''}</span>` : ''}
      </div>`).join('');
  }, 250);
}

async function addDep(noteId, blockerId) {
  const res = await apiFetch(`/api/notes/${noteId}/deps`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({blocker_id: blockerId}),
  });
  if (!res.ok) { const e = await res.json(); toast(e.detail || 'Errore', 'error'); return; }
  const inp = document.getElementById(`dep-search-${noteId}`);
  if (inp) inp.value = '';
  const rd = document.getElementById(`dep-results-${noteId}`);
  if (rd) rd.style.display = 'none';
  await refreshDepsPanel(noteId);
}

async function removeDep(noteId, blockerId) {
  await apiFetch(`/api/notes/${noteId}/deps/${blockerId}`, { method: 'DELETE' });
  await refreshDepsPanel(noteId);
}

// ── Mobile sidebar ────────────────────────────────────────────────────────────
function toggleMobileSidebar() {
  document.getElementById('sidebar').classList.toggle('mobile-open');
  document.getElementById('sidebar-backdrop').classList.toggle('show');
}
function closeMobileSidebar() {
  document.getElementById('sidebar').classList.remove('mobile-open');
  document.getElementById('sidebar-backdrop').classList.remove('show');
}

function toggleSidebarSection(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('collapsed');
  // Persisti stato in localStorage
  const key = `noted-sidebar-${id}`;
  localStorage.setItem(key, el.classList.contains('collapsed') ? '1' : '0');
}

// Ripristina stato collassato al caricamento
(function _restoreSidebarSections() {
  ['section-schedule', 'section-ollama', 'section-docs'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const stored = localStorage.getItem(`noted-sidebar-${id}`);
    // default: collapsed (stored === null → collapsed)
    if (stored === '0') el.classList.remove('collapsed');
    else el.classList.add('collapsed');
  });
})();

// ── Local IP button ───────────────────────────────────────────────────────────
async function _loadLocalIp() {
  try {
    const res = await fetch('/api/local-ip');
    const { url, ip } = await res.json();
    if (ip === '127.0.0.1') return;
    const btn = document.getElementById('ip-btn');
    btn.textContent = `📱 ${ip}`;
    btn.style.display = '';
    btn._url = url;
  } catch {}
}
async function copyLocalUrl() {
  const btn = document.getElementById('ip-btn');
  const url = btn._url;
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    const orig = btn.textContent;
    btn.textContent = '✓ Copiato!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  } catch {
    toast(url, 'success');
  }
}

// ── Service Worker ────────────────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/sw.js').catch(() => {});
}

// ── Documents ─────────────────────────────────────────────────────────────────
function _fileIcon(mime, name) {
  if (!mime) mime = '';
  if (mime.startsWith('image/')) return '🖼';
  if (mime === 'application/pdf') return '📄';
  if (mime.startsWith('application/vnd.openxmlformats') || mime === 'application/msword') return '📝';
  if (mime.startsWith('video/')) return '🎥';
  if (mime.startsWith('audio/')) return '🎵';
  if (mime === 'application/zip' || mime === 'application/x-tar') return '📦';
  return '📎';
}

function _fmtSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024*1024) return `${(bytes/1024).toFixed(0)}KB`;
  return `${(bytes/1024/1024).toFixed(1)}MB`;
}

async function openDoc(docId) {
  try {
    await fetch(`/api/docs/${docId}/open`, { method: 'POST' });
  } catch { toast('Impossibile aprire il file', 'error'); }
}

// Pending files for new note form
let _pendingFiles = [];

document.getElementById('attach-input').addEventListener('change', e => {
  _pendingFiles = [..._pendingFiles, ...Array.from(e.target.files)];
  e.target.value = '';
  _renderAttachPreview();
});

function _renderAttachPreview() {
  const el = document.getElementById('attach-preview');
  if (!el) return;
  // Revoke previous object URLs to avoid memory leaks
  el.querySelectorAll('img[data-obj-url]').forEach(img => URL.revokeObjectURL(img.src));
  el.innerHTML = _pendingFiles.map((f, i) => {
    if (f.type.startsWith('image/')) {
      const objUrl = URL.createObjectURL(f);
      return `
        <span class="attach-chip" style="align-items:center;">
          <img data-obj-url="1" src="${escHtml(objUrl)}" alt="${escHtml(f.name)}"
               style="height:40px;width:auto;max-width:80px;object-fit:cover;border-radius:4px;flex-shrink:0;">
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtml(f.name)}</span>
          <button type="button" onclick="_removeAttach(${i})" style="background:none;border:none;cursor:pointer;color:var(--text-dim);padding:0;font-size:11px;flex-shrink:0;">×</button>
        </span>
      `;
    }
    return `
      <span class="attach-chip">
        ${_fileIcon(f.type, f.name)}
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtml(f.name)}</span>
        <button type="button" onclick="_removeAttach(${i})" style="background:none;border:none;cursor:pointer;color:var(--text-dim);padding:0;font-size:11px;flex-shrink:0;">×</button>
      </span>
    `;
  }).join('');
}

function _removeAttach(i) {
  _pendingFiles.splice(i, 1);
  _renderAttachPreview();
}

async function _uploadPendingFiles(noteId) {
  for (const f of _pendingFiles) {
    const fd = new FormData();
    fd.append('file', f);
    try {
      await fetch(`/api/notes/${noteId}/docs`, { method: 'POST', body: fd });
    } catch { /* silently skip */ }
  }
  _pendingFiles = [];
  _renderAttachPreview();
}

// Input file nascosto per allegare a note esistenti
let _attachTargetNoteId = null;
const _attachExistingInput = document.createElement('input');
_attachExistingInput.type = 'file';
_attachExistingInput.multiple = true;
_attachExistingInput.style.display = 'none';
document.body.appendChild(_attachExistingInput);
_attachExistingInput.addEventListener('change', async e => {
  const files = Array.from(e.target.files);
  e.target.value = '';
  if (!_attachTargetNoteId || !files.length) return;
  for (const f of files) {
    const fd = new FormData();
    fd.append('file', f);
    try {
      await fetch(`/api/notes/${_attachTargetNoteId}/docs`, { method: 'POST', body: fd });
    } catch { toast('Upload fallito', 'error'); }
  }
  await loadNotes();
  toast('File allegato', 'success');
});

function attachToNote(noteId) {
  _attachTargetNoteId = noteId;
  _attachExistingInput.click();
}

// ── Settings: doc_root ────────────────────────────────────────────────────────
async function loadDocRoot() {
  try {
    const r = await fetch('/api/settings');
    const s = await r.json();
    const inp = document.getElementById('doc-root-input');
    if (inp && s.doc_root) inp.value = s.doc_root;
  } catch {}
}

async function saveDocRoot() {
  const val = document.getElementById('doc-root-input')?.value?.trim();
  if (!val) return;
  try {
    await fetch('/api/settings', {
      method: 'PATCH',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ doc_root: val })
    });
    toast('Cartella salvata', 'success');
  } catch { toast('Errore', 'error'); }
}

async function openDocFolder() {
  try {
    await fetch('/api/docs/open-folder-root', { method: 'POST' });
  } catch { toast('Impossibile aprire la cartella', 'error'); }
}

// ── Update check ─────────────────────────────────────────────────────────────
async function checkForUpdate() {
  try {
    const res = await fetch('/api/version');
    if (!res.ok) return;
    const data = await res.json();
    if (data.has_update) {
      const banner = document.getElementById('update-banner');
      const text = document.getElementById('update-banner-text');
      const link = document.getElementById('update-banner-link');
      if (!banner || !text) return;
      text.textContent = `noted ${data.release_name} disponibile (versione attuale: ${data.current}) — aggiorna con: pip install -e . --upgrade`;
      if (link && data.release_url) link.href = data.release_url;
      banner.style.display = 'flex';
    }
  } catch { /* silenzioso */ }
}

// ── Paste screenshot ──────────────────────────────────────────────────────────
document.getElementById('note-input')?.addEventListener('paste', function(e) {
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      const blob = item.getAsFile();
      if (!blob) continue;
      const ext = item.type.split('/')[1] || 'png';
      const file = new File([blob], `screenshot_${Date.now()}.${ext}`, { type: item.type });
      _pendingFiles.push(file);
      _renderAttachPreview();
      toast('📸 Screenshot allegato — verrà salvato con la nota', 'success');
      break;
    }
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────
loadNotes();
resetRefresh();
_loadLocalIp();
loadDocRoot();
loadOllamaSettings();
checkForUpdate();

// ── Voice input ───────────────────────────────────────────────────────────────
let _mediaRecorder = null;
let _audioChunks = [];
let _audioBlob = null;

function toggleVoiceRecording() {
  if (_mediaRecorder && _mediaRecorder.state === 'recording') {
    stopVoiceRecording();
  } else {
    startVoiceRecording();
  }
}

async function startVoiceRecording() {
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      toast('Il microfono richiede HTTPS. Esegui: noted setup-https — poi riavvia.', 'error');
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
    _mediaRecorder = new MediaRecorder(stream, { mimeType });
    _audioChunks = [];
    _mediaRecorder.ondataavailable = e => { if (e.data.size > 0) _audioChunks.push(e.data); };
    _mediaRecorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      _audioBlob = new Blob(_audioChunks, { type: mimeType });
      const url = URL.createObjectURL(_audioBlob);
      document.getElementById('voice-playback').src = url;
      _showVoiceStep('review');
    };
    _mediaRecorder.start(100);
    document.getElementById('mic-btn').classList.add('recording');
    _showVoiceModal();
    _showVoiceStep('recording');
  } catch (err) {
    toast('Microfono non disponibile: ' + err.message, 'error');
  }
}

function stopVoiceRecording() {
  if (_mediaRecorder && _mediaRecorder.state !== 'inactive') {
    _mediaRecorder.stop();
    document.getElementById('mic-btn').classList.remove('recording');
  }
}

function restartVoiceRecording() {
  _audioBlob = null;
  _audioChunks = [];
  const pb = document.getElementById('voice-playback');
  pb.src = '';
  startVoiceRecording();
}

async function transcribeAudio() {
  if (!_audioBlob) return;
  _showVoiceStep('loading');
  try {
    const form = new FormData();
    form.append('audio', _audioBlob, 'recording.webm');
    const res = await fetch('/api/voice/transcribe', { method: 'POST', body: form });
    let data;
    try { data = await res.json(); } catch { data = {}; }
    if (!res.ok) throw new Error(data.detail || 'Errore trascrizione');
    document.getElementById('voice-transcript-text').value = data.text || '';
    _showVoiceStep('transcript');
  } catch (err) {
    toast('Trascrizione fallita: ' + err.message, 'error');
    _showVoiceStep('review');
  }
}

function useVoiceTranscript() {
  const text = document.getElementById('voice-transcript-text').value.trim();
  if (text) {
    const ta = document.getElementById('note-input');
    ta.value = text;
    ta.style.height = 'auto';
    ta.style.height = ta.scrollHeight + 'px';
    ta.focus();
  }
  _closeVoiceModal();
}

function _showVoiceModal() {
  document.getElementById('voice-modal').classList.add('show');
}

function _showVoiceStep(step) {
  ['recording', 'review', 'transcript', 'loading'].forEach(s => {
    document.getElementById(`voice-step-${s}`).style.display = s === step ? '' : 'none';
  });
}

function _closeVoiceModal() {
  stopVoiceRecording();
  document.getElementById('voice-modal').classList.remove('show');
  document.getElementById('mic-btn').classList.remove('recording');
}

function closeVoiceModal(e) {
  if (!e || e.target === document.getElementById('voice-modal')) {
    _closeVoiceModal();
  }
}

// ── PWA refresh ───────────────────────────────────────────────────────────────
function pwaRefresh() {
  const btn = document.getElementById('pwa-refresh');
  btn.classList.add('spinning');
  const tab = document.getElementById('tab-notes')?.classList.contains('active') ? 'notes'
    : document.getElementById('tab-board')?.classList.contains('active') ? 'board'
    : document.getElementById('tab-gantt')?.classList.contains('active') ? 'gantt'
    : document.getElementById('tab-docs')?.classList.contains('active') ? 'docs'
    : 'notes';
  const done = () => btn.classList.remove('spinning');
  if (tab === 'notes') loadNotes().finally(done);
  else if (tab === 'board') loadBoard().finally(done);
  else if (tab === 'gantt') loadGantt().finally(done);
  else if (tab === 'docs') loadDocList().finally(done);
  else done();
}

// Pull-to-refresh
(function () {
  const THRESHOLD = 80;
  let startY = 0, pulling = false, reached = false;
  const ind = document.getElementById('ptr-indicator');
  const spin = ind.querySelector('.ptr-spinner');

  document.addEventListener('touchstart', e => {
    if (window.scrollY === 0 && e.touches.length === 1) {
      startY = e.touches[0].clientY;
      pulling = true;
      reached = false;
    }
  }, { passive: true });

  document.addEventListener('touchmove', e => {
    if (!pulling) return;
    const dy = e.touches[0].clientY - startY;
    if (dy <= 0) { pulling = false; return; }
    const pct = Math.min(dy / THRESHOLD, 1);
    ind.style.transform = `translateX(-50%) translateY(${-60 + pct * 70}px)`;
    ind.classList.toggle('visible', dy > 20);
    if (dy >= THRESHOLD && !reached) { reached = true; ind.classList.add('ready'); spin.classList.add('spin'); }
    if (dy < THRESHOLD && reached) { reached = false; ind.classList.remove('ready'); spin.classList.remove('spin'); }
  }, { passive: true });

  document.addEventListener('touchend', () => {
    if (!pulling) return;
    pulling = false;
    ind.style.transform = '';
    ind.classList.remove('visible', 'ready');
    spin.classList.remove('spin');
    if (reached) pwaRefresh();
  });
})();

// ── Doc analysis ──────────────────────────────────────────────────────────────
let _analysisItems = [];   // risultati correnti dall'AI

function openDocAnalysis() {
  switchTab('docs');
}
function closeDocAnalysis(e) {
  // legacy no-op — l'analisi è ora nel tab docs
}

function loadDocList() {
  _loadDocsForAnalysis();
}

async function _loadDocsForAnalysis() {
  const ctx = document.getElementById('ctx-label')?.textContent?.toLowerCase() || 'default';
  const list = document.getElementById('doc-selector-list');
  list.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px 0;">Caricamento…</div>';
  try {
    const res = await fetch(`/api/docs?ctx=${encodeURIComponent(ctx)}`);
    const docs = await res.json();
    if (!docs.length) {
      list.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px 0;">Nessun documento trovato.<br>Allega file alle tue note per vederli qui.</div>';
      return;
    }
    list.innerHTML = docs.map(d => `
      <label class="doc-selector-item" id="dsel-${d.id}">
        <input type="checkbox" value="${d.id}" onchange="_syncSelectorStyle(${d.id}, this.checked)">
        <div style="min-width:0;">
          <div class="doc-selector-name">${_fileIcon(d.mime_type, d.orig_name)} ${escHtml(d.orig_name)}</div>
          <div class="doc-selector-meta">${d.rel_path.split('/').slice(0,-1).join(' / ')} · ${_fmtSize(d.size_bytes)}</div>
        </div>
      </label>
    `).join('');
  } catch {
    list.innerHTML = '<div style="color:var(--red);font-size:0.8rem;">Errore nel caricamento</div>';
  }
}

const _MAX_ANALYSIS_DOCS = 5;

function _syncSelectorStyle(id, checked) {
  const all = [...document.querySelectorAll('#doc-selector-list input[type=checkbox]')];
  const nChecked = all.filter(c => c.checked).length;

  // Se si cerca di aggiungere oltre il limite, blocca
  if (checked && nChecked > _MAX_ANALYSIS_DOCS) {
    const inp = document.querySelector(`#dsel-${id} input`);
    if (inp) inp.checked = false;
    toast(`Massimo ${_MAX_ANALYSIS_DOCS} documenti per analisi`, 'error');
    _updateDocSelCount();
    return;
  }

  document.getElementById(`dsel-${id}`)?.classList.toggle('selected', checked);
  _updateDocSelCount();
}

function _updateDocSelCount() {
  const all     = [...document.querySelectorAll('#doc-selector-list input[type=checkbox]')];
  const n       = all.filter(c => c.checked).length;
  const el      = document.getElementById('doc-sel-count');
  if (!el) return;
  el.textContent = `${n} / ${_MAX_ANALYSIS_DOCS} selezionati`;
  el.style.color = n >= _MAX_ANALYSIS_DOCS ? 'var(--yellow)' : 'var(--text-muted)';
}

// Depth selector visual highlight
document.addEventListener('change', e => {
  if (e.target.name !== 'analysis-depth') return;
  ['low','medium','high'].forEach(d => {
    const lbl = document.getElementById(`depth-${d}`);
    if (!lbl) return;
    const active = e.target.value === d;
    lbl.style.borderColor = active ? 'var(--accent)' : 'var(--border)';
    lbl.style.background   = active ? 'var(--accent-dim)' : '';
  });
});

async function runDocAnalysis() {
  const checked = [...document.querySelectorAll('#doc-selector-list input[type=checkbox]:checked')];
  if (!checked.length) { toast('Seleziona almeno un documento', 'error'); return; }

  const docIds = checked.map(c => parseInt(c.value));
  const extra  = document.getElementById('doc-analysis-extra').value.trim();
  const depth  = document.querySelector('input[name="analysis-depth"]:checked')?.value || 'medium';

  const btn = document.getElementById('doc-analyze-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Analisi…';

  document.getElementById('doc-analysis-placeholder').style.display = 'none';
  document.getElementById('doc-analysis-loading').style.display = 'flex';
  document.getElementById('doc-analysis-output').style.display = 'none';

  try {
    const res = await fetch('/api/analyze-docs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds, extra_instructions: extra || null, depth }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Errore ${res.status}`);
    }
    const result = await res.json();
    _renderAnalysisResults(result);
  } catch (e) {
    document.getElementById('doc-analysis-loading').style.display = 'none';
    document.getElementById('doc-analysis-placeholder').style.display = 'flex';
    toast(`Analisi fallita: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '🤖 Analizza';
  }
}

function _renderAnalysisResults(result) {
  document.getElementById('doc-analysis-loading').style.display = 'none';
  document.getElementById('doc-analysis-output').style.display = 'flex';

  // Summary
  document.getElementById('doc-analysis-summary').textContent = result.summary || '—';

  // Insights
  const insights = result.insights || [];
  const insightsWrap = document.getElementById('doc-insights-wrap');
  if (insights.length) {
    document.getElementById('doc-analysis-insights').innerHTML =
      insights.map(i => `<li>${escHtml(i)}</li>`).join('');
    insightsWrap.style.display = 'block';
  } else {
    insightsWrap.style.display = 'none';
  }

  // Items
  _analysisItems = result.items || [];
  const itemsWrap = document.getElementById('doc-items-wrap');
  const itemsEl   = document.getElementById('doc-analysis-items');
  if (_analysisItems.length) {
    itemsEl.innerHTML = _analysisItems.map((item, i) => {
      const isNote = item.type === 'note';
      const typeLabel = isNote ? '📝 Nota / Todo' : '📊 Milestone';
      const meta = [];
      if (item.project) meta.push(`<span class="project-badge">${escHtml(item.project)}</span>`);
      if (isNote) {
        if (item.tags) meta.push(`<span class="tag">${escHtml(item.tags)}</span>`);
        if (item.priority) meta.push(`<span class="priority priority-${item.priority}">${item.priority}</span>`);
        if (item.status) meta.push(`<span class="status status-${item.status}">${item.status}</span>`);
      } else {
        if (item.start_date) meta.push(`<span style="font-size:0.68rem;color:var(--text-muted);">📅 ${item.start_date} → ${item.end_date || '?'}</span>`);
      }
      return `
        <div class="doc-item-card selected" id="ditem-${i}" onclick="_toggleDocItem(${i})">
          <input type="checkbox" checked onchange="_toggleDocItem(${i})" onclick="event.stopPropagation()" id="ditem-chk-${i}" style="accent-color:var(--accent);margin-top:3px;flex-shrink:0;">
          <div class="doc-item-body">
            <div class="doc-item-type">${typeLabel}</div>
            <div class="doc-item-content">${escHtml(isNote ? item.content : item.name)}</div>
            ${meta.length ? `<div class="doc-item-meta">${meta.join('')}</div>` : ''}
          </div>
        </div>`;
    }).join('');
    document.getElementById('doc-select-all').checked = true;
    itemsWrap.style.display = 'block';
  } else {
    itemsWrap.style.display = 'none';
  }
}

function _toggleDocItem(i) {
  const chk  = document.getElementById(`ditem-chk-${i}`);
  const card = document.getElementById(`ditem-${i}`);
  chk.checked = !chk.checked;
  card.classList.toggle('selected', chk.checked);
}

function docSelectAll(checked) {
  _analysisItems.forEach((_, i) => {
    const chk  = document.getElementById(`ditem-chk-${i}`);
    const card = document.getElementById(`ditem-${i}`);
    if (chk) { chk.checked = checked; card?.classList.toggle('selected', checked); }
  });
}

async function createDocItems() {
  const ctx = document.getElementById('ctx-label')?.textContent?.toLowerCase() || 'default';
  const btn = document.getElementById('doc-create-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Creazione…';

  let created = 0, skipped = 0;
  const milestones = [];

  for (let i = 0; i < _analysisItems.length; i++) {
    const chk = document.getElementById(`ditem-chk-${i}`);
    if (!chk?.checked) continue;
    const item = _analysisItems[i];

    if (item.type === 'note') {
      try {
        const res = await fetch(`/api/notes?ctx=${encodeURIComponent(ctx)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            content:  item.content,
            tags:     item.tags || '',
            project:  item.project || null,
            priority: item.priority || 'medium',
            status:   item.status || null,
          }),
        });
        if (res.ok) created++;
        else skipped++;
      } catch { skipped++; }
    } else if (item.type === 'milestone') {
      milestones.push(item);
    }
  }

  btn.disabled = false;
  btn.textContent = '✓ Crea selezionati';

  if (created) {
    await loadNotes();
    toast(`✓ ${created} element${created > 1 ? 'i creati' : 'e creato'}`, 'success');
  }

  if (milestones.length) {
    const names = milestones.map(m => `• ${m.name} (${m.project})`).join('\n');
    toast(`${milestones.length} milestone da creare manualmente nel Gantt:\n${names}`, '');
    console.info('Milestone suggerite:', milestones);
  }

  if (skipped) toast(`${skipped} element${skipped > 1 ? 'i' : 'o'} non creato per errore`, 'error');
}

// ── Ollama LLM ────────────────────────────────────────────────────────────────

function toggleLlm() {
  llmActive = !llmActive;
  _syncLlmBtn();
  if (llmActive) checkOllamaStatus();
}

function _syncLlmBtn() {
  const btn = document.getElementById('llm-btn');
  if (!btn) return;
  btn.style.borderColor  = llmActive ? 'var(--accent)' : '';
  btn.style.background   = llmActive ? 'var(--accent-dim)' : '';
  btn.style.color        = llmActive ? 'var(--accent)' : '';
  btn.title = llmActive ? 'LLM attivo — clicca per disattivare' : 'Attiva elaborazione LLM (Ollama)';
}

async function checkOllamaStatus() {
  const dot = document.getElementById('ollama-status-dot');
  try {
    const res = await fetch('/api/ollama/status');
    const data = await res.json();
    if (dot) dot.style.background = data.ok ? 'var(--green)' : 'var(--red)';
    const hint = document.getElementById('ollama-models-hint');
    if (hint) {
      hint.textContent = data.ok
        ? `Modelli disponibili: ${data.models.join(', ') || '—'}`
        : 'Non raggiungibile. Avvia Ollama con: ollama serve';
      hint.style.color = data.ok ? 'var(--text-dim)' : 'var(--red)';
    }
    if (llmActive && !data.ok) {
      toast('🦙 Ollama non raggiungibile — attivalo con: ollama serve', 'error');
      llmActive = false;
      _syncLlmBtn();
    }
  } catch {
    if (dot) dot.style.background = 'var(--red)';
  }
}

async function loadOllamaSettings() {
  try {
    const res = await fetch('/api/ollama/settings');
    const data = await res.json();
    const urlEl   = document.getElementById('ollama-url-input');
    const modelEl = document.getElementById('ollama-model-input');
    if (urlEl)   urlEl.value   = data.url   || '';
    if (modelEl) modelEl.value = data.model || '';
  } catch {}
  checkOllamaStatus();
}

async function saveOllamaSettings() {
  const url   = document.getElementById('ollama-url-input')?.value.trim();
  const model = document.getElementById('ollama-model-input')?.value.trim();
  try {
    await fetch('/api/ollama/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url || null, model: model || null }),
    });
    toast('Impostazioni Ollama salvate', 'ok');
    checkOllamaStatus();
  } catch {
    toast('Errore salvataggio impostazioni', 'error');
  }
}

// ── Markdown Editor ───────────────────────────────────────────────────────────
let _editorInited = false;

function initEditor() {
  if (_editorInited) return;
  _editorInited = true;
  const ta = document.getElementById('editor-textarea');
  // Restore draft
  const saved = localStorage.getItem('noted-editor-draft');
  if (saved) ta.value = saved;
  ta.addEventListener('input', () => {
    localStorage.setItem('noted-editor-draft', ta.value);
    _editorPreview();
  });
  _editorPreview();
}

function _editorPreview() {
  const ta = document.getElementById('editor-textarea');
  const preview = document.getElementById('editor-preview');
  if (!ta || !preview) return;
  preview.innerHTML = typeof marked !== 'undefined'
    ? marked.parse(ta.value || '')
    : '<em>marked.js non caricato</em>';
}

function editorCmd(cmd) {
  const ta = document.getElementById('editor-textarea');
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const sel = ta.value.substring(start, end);
  let insert = '';
  let offset = 0;

  switch (cmd) {
    case 'bold':   insert = `**${sel || 'testo'}**`; offset = sel ? 0 : 2; break;
    case 'italic': insert = `*${sel || 'testo'}*`;   offset = sel ? 0 : 1; break;
    case 'h1':     insert = `\n# ${sel || 'Titolo'}\n`; offset = 3; break;
    case 'h2':     insert = `\n## ${sel || 'Titolo'}\n`; offset = 4; break;
    case 'h3':     insert = `\n### ${sel || 'Titolo'}\n`; offset = 5; break;
    case 'ul':     insert = `\n- ${sel || 'elemento'}\n`; offset = 3; break;
    case 'ol':     insert = `\n1. ${sel || 'elemento'}\n`; offset = 4; break;
    case 'code':
      if (sel.includes('\n')) {
        insert = `\`\`\`\n${sel || 'codice'}\n\`\`\``;
        offset = 4;
      } else {
        insert = `\`${sel || 'codice'}\``;
        offset = sel ? 0 : 1;
      }
      break;
    case 'table':
      insert = '\n| Colonna 1 | Colonna 2 | Colonna 3 |\n|-----------|-----------|------------|\n| cella     | cella     | cella      |\n';
      offset = 2;
      break;
  }

  ta.setRangeText(insert, start, end, 'end');
  if (!sel) ta.setSelectionRange(start + offset, start + offset + (sel || cmd === 'table' ? 0 : insert.length - offset * 2));
  ta.focus();
  localStorage.setItem('noted-editor-draft', ta.value);
  _editorPreview();
}

function editorClear() {
  if (document.getElementById('editor-textarea').value && !confirm('Cancellare il documento corrente?')) return;
  document.getElementById('editor-textarea').value = '';
  document.getElementById('editor-filename').value = '';
  document.getElementById('editor-preview').innerHTML = '';
  localStorage.removeItem('noted-editor-draft');
}

async function editorExport(format) {
  const content = document.getElementById('editor-textarea').value.trim();
  if (!content) { toast('Editor vuoto', 'info'); return; }
  const filename = document.getElementById('editor-filename').value.trim();
  const btn = document.querySelector(`.editor-tb-export[onclick*="'${format}'"]`);
  const origText = btn?.textContent;
  if (btn) btn.textContent = '⏳…';

  try {
    const res = await fetch(`/api/editor/export/${format}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, filename }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Errore export');
    }

    if (format === 'pdf') {
      const html = await res.text();
      const win = window.open('', '_blank');
      win.document.write(html);
      win.document.close();
      return;
    }

    const blob = await res.blob();
    const disposition = res.headers.get('content-disposition') || '';
    const nameMatch = disposition.match(/filename="?([^"]+)"?/);
    const dlName = nameMatch ? nameMatch[1] : `export.${format}`;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = dlName;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`${format.toUpperCase()} scaricato`, 'success');
  } catch (e) {
    toast(e.message, 'error');
  } finally {
    if (btn) btn.textContent = origText;
  }
}
