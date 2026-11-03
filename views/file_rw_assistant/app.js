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
    credentials: 'same-origin',
    headers: { ...headers(), ...(opt.body ? { 'Content-Type': 'application/json' } : {}), ...(opt.headers || {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function toast(text) {
  $('up-hint').textContent = text;
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

function renderKinds() {
  const box = $('kinds');
  box.innerHTML = '';
  KIND_ORDER.forEach((kind) => {
    const n = state.counts[kind] || 0;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `kind${state.kind === kind ? ' active' : ''}${n ? '' : ' dim'}`;
    const label = document.createElement('span');
    label.textContent = state.labels[kind] || kind;
    const count = document.createElement('em');
    count.textContent = n;
    b.append(label, count);
    b.onclick = () => { state.kind = kind; renderKinds(); load(); };
    box.appendChild(b);
  });
}

function cell(tr, value, className) {
  const td = document.createElement('td');
  if (className) td.className = className;
  td.textContent = value;
  tr.appendChild(td);
  return td;
}

function renderTable() {
  const body = $('table').querySelector('tbody');
  body.innerHTML = '';
  $('empty').hidden = state.items.length > 0;
  $('table').hidden = state.items.length === 0;
  state.items.forEach((it) => {
    const tr = document.createElement('tr');
    const nameTd = document.createElement('td');
    const box = document.createElement('div');
    box.className = 'cell-name';
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = it.name;
    name.title = it.name;
    const meta = document.createElement('span');
    meta.className = 'meta';
    meta.textContent = it.sender ? `${it.sender} · ${it.session}` : it.session;
    box.append(name, meta);
    nameTd.appendChild(box);
    tr.appendChild(nameTd);
    cell(tr, state.labels[it.kind] || it.kind);
    cell(tr, human(it.size));
    cell(tr, `v${it.current_version}`);
    cell(tr, it.updated_at);
    const actTd = document.createElement('td');
    actTd.className = 'actions-col';
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'link';
    open.textContent = '打开';
    open.onclick = (e) => { e.stopPropagation(); openDrawer(it.id); };
    actTd.appendChild(open);
    tr.appendChild(actTd);
    tr.onclick = () => openDrawer(it.id);
    body.appendChild(tr);
  });
}

async function load() {
  const params = new URLSearchParams();
  if (state.kind) params.set('kind', state.kind);
  if (state.q) params.set('q', state.q);
  try {
    const data = await api('/list?' + params.toString());
    state.items = data.items || [];
    state.counts = data.counts || {};
    state.labels = data.labels || {};
    if (data.all) {
      toast(`「${state.labels[data.all] || data.all}」里还没有文件，先显示全部`);
      state.kind = '';
    } else if (!state.kind) {
      state.kind = firstNonEmpty(state.counts);
    }
  } catch (err) {
    toast(`列表加载失败：${err.message}`);
  }
  let total = 0;
  Object.values(state.counts).forEach((n) => { total += n; });
  $('stat').textContent = `${total} 个文件 · ${state.kind ? state.labels[state.kind] || state.kind : '全部'}`;
  renderKinds();
  renderTable();
}

async function openDrawer(id) {
  const data = await api('/detail/' + encodeURIComponent(id));
  const f = data.file;
  state.current = f;
  $('drawer').hidden = false;
  $('d-name').textContent = f.name;
  $('d-meta').textContent = `${state.labels[f.kind] || f.kind} · ${human(f.size)} · v${f.current_version} · ${f.sender ? f.sender + ' · ' : ''}${f.session}`;
  const content = await api('/content/' + encodeURIComponent(f.id));
  const box = $('d-content');
  box.value = content.text || '';
  box.readOnly = !content.editable;
  $('d-save').disabled = !content.editable;
  $('d-hint').textContent = content.editable ? '改完点右边，存成新版本' : '这类文件不支持在线编辑';
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
    btn.type = 'button';
    btn.className = 'link';
    btn.textContent = '回滚';
    btn.onclick = () => rollback(f.id, v.version);
    actions.append(note, btn);
    li.append(info, actions);
    ul.appendChild(li);
  });
}

async function rollback(fileId, version) {
  try {
    await api('/rollback', { method: 'POST', body: JSON.stringify({ file_id: fileId, version }) });
    await load();
    await openDrawer(fileId);
  } catch (err) {
    toast(`回滚失败：${err.message}`);
  }
}

async function saveContent() {
  if (!state.current) return;
  try {
    await api('/save', {
      method: 'POST',
      body: JSON.stringify({ file_id: state.current.id, content: $('d-content').value }),
    });
    await load();
    await openDrawer(state.current.id);
    toast('已存为新版本');
  } catch (err) {
    toast(`保存失败：${err.message}`);
  }
}

async function sendToSession() {
  if (!state.current) return;
  const umo = prompt('发到哪个会话？填 UMO，如 QQ-唐小珂:GroupMessage:652135583');
  if (!umo) return;
  try {
    const r = await api('/send', { method: 'POST', body: JSON.stringify({ file_id: state.current.id, umo }) });
    toast(r.ok ? '已发送' : '发送失败');
  } catch (err) {
    toast(`发送失败：${err.message}`);
  }
}

async function removeFile() {
  if (!state.current) return;
  const id = state.current.id;
  try {
    await api('/delete', { method: 'POST', body: JSON.stringify({ file_id: id }) });
    $('drawer').hidden = true;
    state.current = null;
    await load();
    toast('已删除');
  } catch (err) {
    toast(`删除失败：${err.message}`);
  }
}

$('q').oninput = (e) => { state.q = e.target.value.trim(); clearTimeout(window._t); window._t = setTimeout(load, 250); };
$('refresh').onclick = load;
$('d-close').onclick = () => { $('drawer').hidden = true; };
$('d-save').onclick = saveContent;
$('d-send').onclick = sendToSession;
$('d-delete').onclick = removeFile;
// 下载要走 fetch 才能带上面板 token，裸链接会被鉴权挡成 401
$('d-download').onclick = async () => {
  if (!state.current) return;
  const res = await fetch(`${API}/keyfile/${encodeURIComponent(state.current.id)}`, { headers: headers(), credentials: 'same-origin' });
  if (!res.ok) { toast(`下载失败：${res.status}`); return; }
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
    toast(`上传 ${file.name} ${i + 1}/${total}`);
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
  toast(`${file.name} 已入库`);
  state.kind = '';
  await load();
}

async function uploadFiles(list) {
  for (const file of Array.from(list || [])) {
    try {
      await uploadFile(file);
    } catch (err) {
      toast(`${file.name} 失败：${err.message}`);
    }
  }
}

$('pick').onclick = () => $('file').click();
$('file').onchange = (e) => uploadFiles(e.target.files);
const card = $('card');
card.addEventListener('dragover', (e) => { e.preventDefault(); card.classList.add('drop'); });
card.addEventListener('dragleave', () => card.classList.remove('drop'));
card.addEventListener('drop', (e) => {
  e.preventDefault();
  card.classList.remove('drop');
  uploadFiles(e.dataTransfer.files);
});

load();
