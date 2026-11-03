const API = '/api/plug/astrbot_plugin_file_rw_assistant';
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
    const cells = [
      it.name,
      state.labels[it.kind] || it.kind,
      human(it.size),
      `v${it.current_version}`,
      it.sender || it.session,
      it.updated_at,
    ];
    cells.forEach((value, i) => {
      const td = document.createElement('td');
      td.textContent = value;
      if (i === 0) td.title = it.name;
      tr.appendChild(td);
    });
    const td = document.createElement('td');
    const btn = document.createElement('button');
    btn.className = 'link';
    btn.textContent = '打开';
    btn.onclick = () => openDrawer(it.id);
    td.appendChild(btn);
    tr.appendChild(td);
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
    const info = document.createElement('span');
    info.textContent = `v${v.version} · ${human(v.size)} · ${v.created_at}`;
    const actions = document.createElement('span');
    actions.className = 'v-actions';
    const note = document.createElement('em');
    note.textContent = v.note || '';
    const btn = document.createElement('button');
    btn.className = 'link';
    btn.textContent = '回滚';
    btn.onclick = () => rollback(f.id, v.version);
    actions.append(note, btn);
    li.append(info, actions);
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

$('q').oninput = (e) => { state.q = e.target.value.trim(); clearTimeout(window._t); window._t = setTimeout(load, 250); };
$('refresh').onclick = load;
$('d-close').onclick = () => { $('drawer').hidden = true; };
$('d-save').onclick = saveContent;
$('d-send').onclick = sendToSession;
$('d-delete').onclick = removeFile;
// 下载要走 fetch 才能带上面板 token，裸链接会被鉴权挡成 401
$('d-download').onclick = async (e) => {
  e.preventDefault();
  if (!state.current) return;
  const res = await fetch(`${API}/keyfile/${encodeURIComponent(state.current.id)}`, { headers: headers() });
  if (!res.ok) { alert(`下载失败：${res.status}`); return; }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = state.current.name;
  a.click();
  URL.revokeObjectURL(url);
};

// 分片上传：8MB 一片，最后一片带 last=true 才入库
const CHUNK = 8 * 1024 * 1024;

function toB64(buf) {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

async function uploadFile(file) {
  const uploadId = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  const total = Math.max(1, Math.ceil(file.size / CHUNK));
  for (let i = 0; i < total; i += 1) {
    $('up-hint').textContent = `上传 ${file.name} ${i + 1}/${total}`;
    const buf = await file.slice(i * CHUNK, (i + 1) * CHUNK).arrayBuffer();
    await api('/upload', {
      method: 'POST',
      body: JSON.stringify({
        name: file.name,
        upload_id: uploadId,
        chunk_b64: toB64(buf),
        last: i === total - 1,
      }),
    });
  }
  $('up-hint').textContent = `${file.name} 已入库`;
  await load();
}

async function uploadFiles(list) {
  for (const file of Array.from(list || [])) {
    try {
      await uploadFile(file);
    } catch (err) {
      $('up-hint').textContent = `${file.name} 失败：${err.message}`;
    }
  }
}

$('pick').onclick = () => $('file').click();
$('file').onchange = (e) => uploadFiles(e.target.files);
const dropzone = document.querySelector('.tablewrap');
dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('drop'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drop'));
dropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropzone.classList.remove('drop');
  uploadFiles(e.dataTransfer.files);
});

load();
