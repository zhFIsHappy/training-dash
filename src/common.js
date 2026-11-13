// Shared helpers for the design comps. window.DASH comes from build.py.
const D = window.DASH;
const KG = 2.20462;
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const wv = (lbs, unit) => unit === 'kg' ? Math.round(lbs / KG * 2) / 2 : Math.round(lbs * 10) / 10;
const setTxt = (s, m) => (s[0] > 0 ? `${m.assist ? '辅助 ' : ''}${wv(s[0], m.unit)}×${s[1]}` : `自重×${s[1]}`);
const unitTxt = (m) => (m.unit === 'kg' ? 'kg' : '磅');
const VL = { weight: '涨重量', reps: '涨次数', same: '持平', down: '退步', watch: '待观察', unit: '单位存疑', first: '首次', swap: '换动作' };
const UP = ['weight', 'reps'];
const md = (s) => { const [, m, d] = s.split('-'); return `${+m}/${+d}`; };
const sessionsOf = (t) => D.days.filter(d => d.template === t);
const slotsOf = (sess) => { const m = new Map(); for (const d of sess) for (const x of d.moves) m.set(x.pos, x); return [...m].sort((a, b) => a[0] - b[0]); };
const last = D.days[D.days.length - 1];
const tally = (moves) => { const c = {}; for (const m of moves) c[m.verdict] = (c[m.verdict] || 0) + 1; return c; };
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
const nearW = (a, b) => Math.abs(a - b) <= 0.01 * Math.max(a, b, 1);  // = build.py SAME_WEIGHT_TOL
const deltaTxt = (m, prev) => {
  if (!prev || m.verdict === 'first' || m.verdict === 'swap') return '';
  const dw = wv(m.best[0], m.unit) - wv(prev.best[0], m.unit), dr = m.best[1] - prev.best[1];  // both in this session's unit
  if (!nearW(m.best[0], prev.best[0])) return `${dw > 0 ? '+' : '−'}${Math.abs(Math.round(dw * 10) / 10)} ${unitTxt(m)}`;
  if (dr) return `${dr > 0 ? '+' : '−'}${Math.abs(dr)} 次`;
  const { diff } = setDiff(m, prev);
  return diff ? `${diff > 0 ? '+' : '−'}${Math.abs(diff)} 次` : '±0';
};
// Best set unchanged: compare the working sets at that weight one by one (only the sets both sessions have).
const setDiff = (m, prev) => {
  const at = (x) => x.sets.filter(s => s[2] !== '热' && Math.abs(s[0] - x.best[0]) <= 0.01 * Math.max(x.best[0], 1)).map(s => s[1]);
  const a = at(m), b = at(prev), n = Math.min(a.length, b.length), parts = [];
  let diff = 0;
  for (let i = 0; i < n; i++) if (a[i] !== b[i]) { diff += a[i] - b[i]; parts.push(`第 ${i + 1} 组 ${b[i]}→${a[i]}`); }
  if (a.length !== b.length) parts.push(`这次 ${a.length} 组,上次 ${b.length} 组`);
  return { diff, why: parts.join(',') };
};
const whyTxt = (m, prev) => {  // one line under the change: where it came from
  if (!prev || ['first', 'swap'].includes(m.verdict)) return '';
  if (Math.abs(m.best[0] - prev.best[0]) > 0.01 || m.best[1] !== prev.best[1]) return `最佳组 ${setTxt(prev.best, prev)} → ${setTxt(m.best, m)}`;
  return setDiff(m, prev).why || '每组都一样';
};
const prevOf = (tpl, date, m) => {  // previous session of this template with the same name at this slot
  const s = sessionsOf(tpl).filter(d => d.date < date).reverse();
  if (m.verdict === 'first') return null;
  if (m.verdict === 'swap') return s.length ? s[0].moves.find(y => y.pos === m.pos) || null : null;  // what this slot replaced
  for (const d of s) {  // same name, nearest position (a lift done twice in one session keeps its own slot)
    const xs = d.moves.filter(y => y.name === m.name);
    if (xs.length) return xs.reduce((a, y) => Math.abs(y.pos - m.pos) < Math.abs(a.pos - m.pos) ? y : a);
  }
  return null;
};
