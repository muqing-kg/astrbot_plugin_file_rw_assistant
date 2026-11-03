const API = '/api/plug/astrbot_plugin_file_vault';
const KIND_ORDER = ['word', 'excel', 'ppt', 'pdf', 'text', 'markdown', 'code', 'csv', 'video'];
const state = { kind: '', q: '', items: [], counts: {}, labels: {}, current: null };

const $ = (id) => document.getElementById(id);

function headers() {
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api(path, opt = {}) {
  const res = await fetch(API + path, {
    ...opt,
    headers: { ...headers(), ...(opt.body ? { 'Content-Type': 'application/json' } : {}), ...(opt.headers || {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function human(n) {
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i += 1; }
  return `${i ? n.toFixed(1) : n}${u[i]}`;
}

function firstNonEmpty(counts) {
  return KIND_ORDER.find((k) => (counts[k] || 0) > 0) || '';
}

function renderRail() {
  const rail = $('rail');
  rail.innerHTML = '';
  KIND_ORDER.forEach((kind) => {
    const n = state.counts[kind] || 0;
    const b = document.createElement('button');
    b.className = `rail-item${state.kind === kind ? ' active' : ''}${n ? '' : ' dim'}`;
    b.innerHTML = `<span>${state.labels[kind] || kind}</span><em>${n}</em>`;
    b.onclick = () => { state.kind = kind; renderRail(); load(); };
    rail.appendChild(b);
  });
}

function renderTable() {
  const body = $('table').querySelector('tbody');
  body.innerHTML = '';
  $('empty').hidden = state.items.length > 0;
  state.items.forEach((it) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td title="${it.name}">${it.name}</td>
      <td>${state.labels[it.kind] || it.kind}</td>
      <td>${human(it.size)}</td>
      <td>v${it.current_version}</td>
      <td>${it.sender || it.session}</td>
      <td>${it.updated_at}</td>
      <td><button class="link">打开</button></td>`;
    tr.querySelector('button').onclick = () => openDrawer(it.id);
    tr.onclick = (e) => { if (e.target.tagName !== 'BUTTON') openDrawer(it.id); };
    body.appendChild(tr);
  });
}

async function load() {
  const params = new URLSearchParams();
  if (state.kind) params.set('kind', state.kind);
  if (state.q) params.set('q', state.q);
  const data = await api('/list?' + params.toString());
  state.items = data.items || [];
  state.counts = data.counts || {};
  state.labels = data.labels || {};
  if (!state.kind) state.kind = firstNonEmpty(state.counts);
  const s = data.stats || { files: 0, bytes: 0 };
  $('stat').textContent = `${s.files} 个文件 · ${human(s.bytes || 0)}`;
  renderRail();
  renderTable();
}

async function openDrawer(id) {
  const data = await api('/detail/' + encodeURIComponent(id));
  state.current = data.file;
  const f = data.file;
  $('drawer').hidden = false;
  $('d-name').textContent = f.name;
  $('d-download').href = `${API}/keyfile/${encodeURIComponent(f.id)}`;
  const content = await api('/content/' + encodeURIComponent(f.id));
  const box = $('d-content');
  box.value = content.text || '';
  box.readOnly = !content.editable;
  $('d-save').disabled = !content.editable;
  $('d-hint').textContent = content.editable ? '可直接改，存为新版本' : '这类文件不支持在线编辑';
  const ul = $('d-versions');
  ul.innerHTML = '';
  (data.versions || []).forEach((v) => {
    const li = document.createElement('li');
    li.innerHTML = `<span>v${v.version} · ${human(v.size)} · ${v.created_at}</span>
      <span class="v-actions"><em>${v.note || ''}</em>
      <button class="link">回滚</button></span>`;
    li.querySelector('button').onclick = () => rollback(f.id, v.version);
    ul.appendChild(li);
  });
}

async function rollback(fileId, version) {
  await api('/rollback', { method: 'POST', body: JSON.stringify({ file_id: fileId, version }) });
  await load();
  await openDrawer(fileId);
}

async function saveContent() {
  if (!state.current) return;
  await api('/save', {
    method: 'POST',
    body: JSON.stringify({ file_id: state.current.id, content: $('d-content').value }),
  });
  await load();
  await openDrawer(state.current.id);
}

async function sendToSession() {
  if (!state.current) return;
  const umo = prompt('发到哪个会话？填 UMO，如 QQ-唐小珂:GroupMessage:652135583');
  if (!umo) return;
  const r = await api('/send', { method: 'POST', body: JSON.stringify({ file_id: state.current.id, umo }) });
  alert(r.ok ? '已发送' : '发送失败');
}

async function removeFile() {
  if (!state.current || !confirm(`删除 ${state.current.name}？该文件所有版本都会消失。`)) return;
  await api('/delete', { method: 'POST', body: JSON.stringify({ file_id: state.current.id }) });
  $('drawer').hidden = true;
  await load();
}

async function renderSettings() {
  const data = await api('/config');
  const host = $('settings');
  host.innerHTML = '';
  Object.entries(data.config).forEach(([key, value]) => {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    const type = typeof value === 'boolean' ? 'checkbox' : typeof value === 'number' ? 'number' : 'text';
    wrap.innerHTML = `<span>${key}</span>`;
    const input = document.createElement('input');
    input.type = type;
    input.dataset.key = key;
    if (type === 'checkbox') input.checked = value; else input.value = value;
    wrap.appendChild(input);
    host.appendChild(wrap);
  });
}

async function saveSettings() {
  const body = {};
  $('settings').querySelectorAll('input').forEach((el) => {
    const key = el.dataset.key;
    body[key] = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value;
  });
  await api('/config', { method: 'POST', body: JSON.stringify(body) });
  alert('已保存');
}

document.querySelectorAll('.tab').forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === tab));
    $('view-files').hidden = tab.dataset.tab !== 'files';
    $('view-settings').hidden = tab.dataset.tab !== 'settings';
    if (tab.dataset.tab === 'settings') renderSettings();
  };
});

$('q').oninput = (e) => { state.q = e.target.value.trim(); clearTimeout(window._t); window._t = setTimeout(load, 250); };
$('refresh').onclick = load;
$('d-close').onclick = () => { $('drawer').hidden = true; };
$('d-save').onclick = saveContent;
$('d-send').onclick = sendToSession;
$('d-delete').onclick = removeFile;
$('s-save').onclick = saveSettings;

load();
