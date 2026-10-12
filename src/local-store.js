/* Expo Compass 本地数据层：给页面提供和 Claude 版相同的 window.claude.use('db') 接口，
   数据读写走本机的 server.py（/api/data、/api/doc/<集合>/<id>）。页面其余代码不需要改。
   Supports collection and single-document onSnapshot (the catalogue date and Highlight settings use the latter). */
(() => {
  'use strict';
  const state = { data: null, colListeners: new Map(), docListeners: new Map() };
  const clone = o => JSON.parse(JSON.stringify(o));
  const deepFreeze = o => { if (o && typeof o === 'object') { Object.values(o).forEach(deepFreeze); Object.freeze(o); } return o; };
  const rid = () => Array.from(crypto.getRandomValues(new Uint8Array(15)), b => 'abcdefghijklmnopqrstuvwxyz0123456789'[b % 36]).join('');
  function merge(target, patch) {
    for (const [k, v] of Object.entries(patch)) {
      if (v && typeof v === 'object' && !Array.isArray(v) && target[k] && typeof target[k] === 'object' && !Array.isArray(target[k])) merge(target[k], v);
      else target[k] = clone(v);
    }
  }
  function docSnap(col, id) {
    const d = (state.data[col] || {})[id];
    if (d === undefined) return { id, exists: false, data: () => undefined };
    const frozen = deepFreeze(clone(d));
    return { id, exists: true, data: () => frozen };
  }
  function emit(col) {
    const docs = Object.keys(state.data[col] || {}).map(id => docSnap(col, id));
    (state.colListeners.get(col) || []).forEach(cb => cb({ docs, size: docs.length, empty: !docs.length }));
    state.docListeners.forEach((cbs, key) => {
      const [c, id] = key.split('/');
      if (c === col) cbs.forEach(cb => cb(docSnap(c, id)));
    });
  }
  async function reload() {
    const r = await fetch('/api/data', { cache: 'no-store' });
    if (!r.ok) throw new Error('load failed');
    state.data = (await r.json()).collections || {};
    const cols = new Set([...state.colListeners.keys(), ...[...state.docListeners.keys()].map(k => k.split('/')[0])]);
    cols.forEach(emit);
  }
  /* 多个窗口：一个窗口保存后通知其他窗口重新读取；窗口回到前台时也重读一次。
     本窗口还有没保存完的修改时先不重读，等保存完再读，免得把刚做的修改闪回去。 */
  const chan = 'BroadcastChannel' in window ? new BroadcastChannel('expo-compass') : null;
  let inflight = 0, reloadWanted = false;
  function refresh() {
    if (!state.data) return;
    if (inflight) { reloadWanted = true; return; }
    reload().catch(() => { /* server gone; keep showing what we have */ });
  }
  if (chan) chan.onmessage = refresh;
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  async function write(method, col, id, body) {
    inflight++;
    try { return await send(method, col, id, body); } finally {
      if (!--inflight && reloadWanted) { reloadWanted = false; refresh(); }
    }
  }
  /* Optimistic: the page sees the change at once; if saving fails, reload the saved data and report it. */
  async function send(method, col, id, body) {
    const docs = state.data[col] || (state.data[col] = {});
    if (method === 'PATCH' && !docs[id]) throw { code: 'invalid_argument', message: 'document does not exist' };
    if (method === 'PUT') docs[id] = clone(body);
    else if (method === 'PATCH') merge(docs[id], body);
    else delete docs[id];
    emit(col);
    let r;
    try {
      r = await fetch(`/api/doc/${encodeURIComponent(col)}/${encodeURIComponent(id)}`, {
        method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) { r = null; }
    if (!r || !r.ok) {
      try { await reload(); } catch { /* server gone; keep showing what we have */ }
      throw { code: r && r.status === 404 ? 'invalid_argument' : 'unavailable', message: r ? `HTTP ${r.status}` : '本地程序没有响应' };
    }
    if (chan) chan.postMessage({ col, id });
  }
  const docRef = (col, id) => ({
    id,
    get: async () => docSnap(col, id),
    set: d => write('PUT', col, id, d),
    update: p => write('PATCH', col, id, p),
    delete: () => write('DELETE', col, id),
    onSnapshot(cb) {
      const key = `${col}/${id}`;
      if (!state.docListeners.has(key)) state.docListeners.set(key, []);
      state.docListeners.get(key).push(cb);
      setTimeout(() => cb(docSnap(col, id)), 0);
      return () => { const l = state.docListeners.get(key); const i = l.indexOf(cb); if (i >= 0) l.splice(i, 1); };
    },
  });
  const db = {
    collection: col => ({
      onSnapshot(cb) {
        if (!state.colListeners.has(col)) state.colListeners.set(col, []);
        state.colListeners.get(col).push(cb);
        setTimeout(() => emit(col), 0);
        return () => { const l = state.colListeners.get(col); const i = l.indexOf(cb); if (i >= 0) l.splice(i, 1); };
      },
      doc: id => docRef(col, id || rid()),
    }),
    doc: path => { const [col, id] = path.split('/'); return docRef(col, id); },
  };
  /* 导出备份 / 日历：普通浏览器里直接下载文件。 */
  const MIME = { json: 'application/json', ics: 'text/calendar;charset=utf-8' };
  const downloads = {
    async save({ filename, data }) {
      const ext = filename.split('.').pop();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([data], { type: MIME[ext] || 'application/octet-stream' }));
      a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      return { status: 'saved' };
    },
  };
  window.EXPO_LOCAL = true;
  window.claude = {
    use: async name => {
      if (name === 'db') {
        try { if (!state.data) await reload(); } catch { return null; }
        return db;
      }
      if (name === 'downloads') return downloads;
      return null;
    },
  };
})();
