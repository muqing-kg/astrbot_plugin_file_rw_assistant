const API = '/api/plug/astrbot_plugin_file_rw_assistant';
const KIND_ORDER = ['word', 'excel', 'ppt', 'pdf', 'text', 'markdown', 'code', 'csv', 'video'];
const state = { kind: '', q: '', items: [], counts: {}, labels: {}, error: '' };

const $ = (id) => document.getElementById(id);

// 面板把插件页放进 sandbox iframe（无 allow-same-origin），localStorage 与 Cookie
// 都取不到，只能走面板注入的 AstrBotPluginView 桥（postMessage 转发到父窗口带凭证请求）。
// 桥的 <script> 由面板插在 </body> 前，晚于本文件执行，所以只能调用时再取。
const bridge = () => window.AstrBotPluginView || window.AstrBotPluginPage;

async function api(path, opt = {}) {
  const [p, qs] = path.split('?');
  const rel = p.replace(/^\/+/, '');
  const VIEW = bridge();
  if (VIEW) {
    if ((opt.method || 'GET').toUpperCase() === 'POST') {
      return VIEW.apiPost(rel, JSON.parse(opt.body || '{}'));
    }
    return VIEW.apiGet(rel, Object.fromEntries(new URLSearchParams(qs || '')));
  }
  // 直接打开页面（不在面板 iframe 里）时的兜底
  let token = '';
  try { token = localStorage.getItem('token') || ''; } catch (e) { token = ''; }
  const res = await fetch(API + path, {
    ...opt,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(opt.body ? { 'Content-Type': 'application/json' } : {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

// 下载走桥的 files:download（父窗口带凭证取二进制）；直开页面时用 fetch+blob。
async function downloadDirect(it, version) {
  let token = '';
  try { token = localStorage.getItem('token') || ''; } catch (e) { token = ''; }
  const q = new URLSearchParams({ file_id: it.id });
  if (version) q.set('version', String(version));
  const res = await fetch(`${API}/download?${q}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = it.name || 'download';
  a.click();
  URL.revokeObjectURL(url);
}

async function downloadFile(it, version) {
  try {
    const VIEW = bridge();
    const params = { file_id: it.id };
    if (version) params.version = String(version);
    if (VIEW) await VIEW.download('download', params, it.name || 'download');
    else await downloadDirect(it, version);
  } catch (err) {
    toast(`下载失败：${err.message}`);
  }
}

let viewing = null;

// 点「查看」出内联预览：文本类直接看，Office/PDF 给出提示；可切历史版本并下载那一版
async function openViewer(it, version) {
  viewing = { ...it, version };
  $('viewer').hidden = false;
  $('v-name').textContent = it.name || '';
  $('v-meta').textContent = '正在读取…';
  $('v-text').value = '';
  $('v-version').innerHTML = '';
  try {
    const q = new URLSearchParams({ file_id: it.id });
    if (version) q.set('version', String(version));
    const d = await api(`/file?${q}`);
    $('v-meta').textContent = `${d.file ? d.file.kind : ''} · v${d.version}${d.editable ? '' : ' · 二进制文件不显示正文，可下载查看'}`;
    $('v-text').value = d.text || '';
    $('v-text').readOnly = true;
    const sel = $('v-version');
    (d.versions || []).forEach((v) => {
      const opt = document.createElement('option');
      opt.value = v.version;
      opt.textContent = `v${v.version} · ${v.created_at}`;
      opt.selected = Number(v.version) === Number(d.version);
      sel.appendChild(opt);
    });
    viewing = { ...it, version: d.version };
  } catch (err) {
    $('v-meta').textContent = `读取失败：${err.message}`;
  }
}

async function deleteFile(id) {
  if (!id) return;
  try {
    await api('/delete', { method: 'POST', body: JSON.stringify({ file_id: id }) });
    await load();
    toast('已删除');
  } catch (err) {
    toast(`删除失败：${err.message}`);
  }
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
  $('empty').textContent = state.error
    ? `列表加载失败：${state.error}`
    : (state.kind ? '这个分类里还没有文件' : '左边先选一个类型');
  $('empty').hidden = state.items.length > 0;
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
    const dl = document.createElement('button');
    dl.type = 'button';
    dl.className = 'link';
    dl.textContent = '查看';
    dl.onclick = (e) => { e.stopPropagation(); openViewer(it); };
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'link link-danger';
    del.textContent = '删除';
    del.onclick = (e) => { e.stopPropagation(); deleteFile(it.id); };
    actTd.append(dl, del);
    tr.appendChild(actTd);
    body.appendChild(tr);
  });
}

async function load() {
  const params = new URLSearchParams();
  if (state.kind) params.set('kind', state.kind);
  if (state.q) params.set('q', state.q);
  try {
    const data = await api('/list?' + params.toString());
    state.counts = data.counts || {};
    state.labels = data.labels || {};
    // 只显示选中的类型；没选就空着，不替用户切到「有文件的类型」
    state.items = state.kind ? (data.items || []) : [];
    state.error = '';
  } catch (err) {
    const V = bridge();
    state.error = `${err.message}（${V ? '桥已就绪' : '桥未注入'}）`;
  }
  let total = 0;
  Object.values(state.counts).forEach((n) => { total += n; });
  $('stat').textContent = `${total} 个文件 · ${state.kind ? state.labels[state.kind] || state.kind : '未选分类'}`;
  renderKinds();
  renderTable();
}

const CHUNK = bridge() ? 2 * 1024 * 1024 : 8 * 1024 * 1024;

function toB64(buf) {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 1) s += String.fromCharCode(bytes[i]);
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

$('q').oninput = (e) => { state.q = e.target.value.trim(); clearTimeout(window._t); window._t = setTimeout(load, 250); };
$('refresh').onclick = load;
$('v-close').onclick = () => { $('viewer').hidden = true; viewing = null; };
$('v-download').onclick = () => { if (viewing) downloadFile(viewing, viewing.version); };
$('v-version').onchange = (e) => {
  if (!viewing) return;
  openViewer(viewing, Number(e.target.value));
};
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

// 桥的 <script> 在 </body> 前，本文件先执行；直接 load() 会赶在桥出现前发请求。
// 等桥 ready()（父窗口首帧上下文），最多等 1.5s，拿不到就按直连兜底。
(async () => {
  const V = bridge();
  if (V && V.ready) {
    await Promise.race([V.ready().catch(() => {}), new Promise((r) => setTimeout(r, 1500))]);
  }
  load();
})();
