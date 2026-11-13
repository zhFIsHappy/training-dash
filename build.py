"""Build a self-contained training dashboard (dist/index.html) from data/trains/*.json.

Each data file is one day of 训记 Open API output (api_trains_for_llm_v2). The page embeds its data and d3,
so it loads nothing from outside — it works behind the GFW.

Progress is judged per slot: the same position (movement index) in the same template, compared with the
previous session of that template. A title used with different exercise orders splits into variants (推, 推 (2));
within a template, sessions are aligned by move names so an inserted/removed move doesn't shift the later slots. A slot's "best set" is its heaviest completed set (ties: more reps).
"""
import base64
import datetime as dt
import difflib
import glob
import json
import os
import re
from collections import defaultdict

import healthstore

ROOT = os.path.dirname(os.path.abspath(__file__))
KG_TO_LBS = 2.20462
E1RM_MAX_REPS = 12
SAME_WEIGHT_TOL = 0.01      # weights within 1% count as the same
E1RM_DROP_TOL = 0.03        # heavier but e1RM down more than this → 待观察
UNIT_RATIO = (2.0, 2.4)     # consecutive best weights this far apart → likely kg/lbs mix-up
STALL_SESSIONS = 3          # this many comparisons in a row without ↑ → 停滞
MATCH_MIN = 0.5             # share of slots a session must share with a template variant to join it
POS_SLACK = 1               # a move one slot off (one insertion/removal before it) still counts as the same slot
UP = ('weight', 'reps')
HEALTH_BASE_DAYS = 7        # health values are judged against the mean of the 7 days before
HEALTH_BAD = {'sleep': lambda v, b: v < b - 0.75, 'deep': lambda v, b: v < b * 0.75,  # clearly worse than usual → red
              'hrv': lambda v, b: v < b * 0.85, 'rhr': lambda v, b: v > b + 4}


def load_days():
    aliases = {k: v for k, v in json.load(open(os.path.join(ROOT, 'data', 'aliases.json'), encoding='utf-8')).items()
               if not k.startswith('_')}
    days = []
    for path in sorted(glob.glob(os.path.join(ROOT, 'data', 'trains', '*.json'))):
        res = json.load(open(path, encoding='utf-8')).get('res')
        if not isinstance(res, dict):
            continue
        for train in res.get('trains', []):
            moves = []
            for m in train.get('movements', []):
                sets, kg = [], 0
                for s in m.get('sets', []):
                    if not s.get('done'):
                        continue
                    try:
                        w, r = float(s.get('weight') or 0), float(s.get('reps') or 0)
                    except ValueError:
                        continue
                    if r <= 0 or (w <= 0 and not s.get('selfWeight')):
                        continue
                    kg += s.get('unit') == 'kg'
                    lbs = w * KG_TO_LBS if s.get('unit') == 'kg' else w
                    sets.append([round(lbs, 1), int(r), s.get('setType') or ''])  # setType: 热 = warm-up, 递 = descending-rep set
                if sets:
                    rm = re.search(r'(\d+)RM重量', m.get('note') or '')  # not the 1-2RM warm-up target
                    name = aliases.get(m['name'], m['name'])
                    moves.append({'pos': m['index'], 'name': name, 'rm': int(rm.group(1)) if rm else None, 'sets': sets,
                                  'unit': 'kg' if kg * 2 > len(sets) else 'lbs',  # display unit: what most sets were logged in; weights stay lbs
                                  'assist': '辅助' in name})  # assisted machine: weight is assistance, lighter = harder
            if moves:
                days.append({'date': train.get('datestr') or res['datestr'], 'title': train.get('title', ''), 'moves': moves})
    days.sort(key=lambda d: d['date'])
    return days


def align(prev, cur):
    """Order-preserving pairing of two sessions' moves by name (an insertion doesn't shift the rest).
    Returns [(cur_move, prev_move or None)]; a pair with different names is a replaced slot."""
    sm = difflib.SequenceMatcher(None, [m['name'] for m in prev], [m['name'] for m in cur], autojunk=False)
    return [(cur[j1 + k], prev[i1 + k] if i1 + k < i2 else None)
            for _, i1, i2, j1, j2 in sm.get_opcodes() for k in range(j2 - j1)]


def match_share(prev, cur):
    """Share of slots where both sessions do the same move at (about) the same position."""
    hits = sum(1 for c, p in align(prev, cur) if p and p['name'] == c['name'] and abs(p['pos'] - c['pos']) <= POS_SLACK)
    return hits / max(len(prev), len(cur))


def assign_templates(days):
    """Fixed mapping from data/templates.json wins. Otherwise a day joins the best-matching variant of its title
    (增肌 days: or any 增肌 template), else starts a new variant: 推, 推 (2), …"""
    fixed = {k: v for k, v in json.load(open(os.path.join(ROOT, 'data', 'templates.json'), encoding='utf-8')).items()
             if not k.startswith('_')}
    latest = {}                    # template -> moves of its latest session
    variants = defaultdict(list)   # title -> its templates
    plan = set(fixed.values())     # 增肌 templates
    for d in days:
        tpl = fixed.get(d['date'])
        if not tpl:
            cands = set(variants[d['title']]) | (plan if '增肌' in d['title'] else set())
            score, best = max(((match_share(latest[t], d['moves']), t) for t in cands if t in latest), default=(0, None))
            tpl = best if score >= MATCH_MIN else None
        if not tpl:
            n = len(variants[d['title']])
            tpl = d['title'] if not n else f"{d['title']} ({n + 1})"
            variants[d['title']].append(tpl)
            if '增肌' in d['title']:
                plan.add(tpl)
        d['template'] = tpl
        latest[tpl] = d['moves']


def working(sets):
    """Sets that count for progress: everything but warm-ups. (递 marks the plan's descending-rep sets — real work.)"""
    return [s for s in sets if s[2] != '热'] or sets


def best_set(sets, assist=False):
    """Heaviest working set (ties: more reps); for assisted machines the lightest assistance."""
    return (min(working(sets), key=lambda s: (s[0], -s[1])) if assist else
            max(working(sets), key=lambda s: (s[0], s[1])))


def e1rm(w, r, assist=False):
    return w * (1 + r / 30) if w > 0 and r <= E1RM_MAX_REPS and not assist else None


def at_best(m):
    """Working sets done at the best set's weight."""
    w = m['best'][0]
    return sum(1 for s in working(m['sets']) if abs(s[0] - w) <= SAME_WEIGHT_TOL * max(w, 1))


def wfmt(lbs, unit, sign=True):
    """A weight (or difference) in lbs, written in the move's display unit."""
    v = round(lbs / KG_TO_LBS * 2) / 2 if unit == 'kg' else round(lbs, 1)
    return f"{v:+g} kg" if sign and unit == 'kg' else f"{v:+g} 磅" if sign else f"{v:g}"


def add_weight(m):
    """The plan works at an NRM weight, so hitting N once is on target. Beating N, or hitting it on two sets, means the weight is light."""
    w, r = m['best'][0], m['best'][1]
    if not m['rm'] or w <= 0:
        return False
    hits = sum(1 for s in working(m['sets']) if abs(s[0] - w) <= SAME_WEIGHT_TOL * w and s[1] >= m['rm'])
    return r > m['rm'] or hits >= 2


def judge(cur, prev):
    """Verdict of this slot vs the previous session of the same template. Returns (verdict, detail)."""
    if prev is None:
        return 'first', '首次'
    if prev['name'] != cur['name']:
        return 'swap', f"上次是 {prev['name']}"
    (w, r, _), (pw, pr, _) = cur['best'], prev['best']
    u, assist = cur.get('unit'), cur.get('assist')
    if not assist and w > 0 and pw > 0 and (UNIT_RATIO[0] <= w / pw <= UNIT_RATIO[1] or UNIT_RATIO[0] <= pw / w <= UNIT_RATIO[1]):
        return 'unit', '重量差约 2.2 倍,可能 kg/磅 记混了'
    same = abs(w - pw) <= SAME_WEIGHT_TOL * max(w, pw)
    pre = '辅助 ' if assist else ''
    if not same and (w < pw if assist else w > pw):
        e, pe = e1rm(w, r, assist), e1rm(pw, pr, assist)
        if e and pe and e < pe * (1 - E1RM_DROP_TOL):
            return 'watch', f'加了重量但次数掉太多(估算 1RM {wfmt(pe, u, False)}→{wfmt(e, u, False)})'
        n, nw = at_best(cur), len(working(cur['sets']))
        return 'weight', pre + wfmt(w - pw, u) + (f',新重量只做了 {n} 组(共 {nw} 组)' if n < nw else '')
    if not same:
        return 'down', pre + wfmt(w - pw, u)
    if r != pr:
        return ('reps', f'+{r - pr} 次') if r > pr else ('down', f'{r - pr} 次')
    # same best set: look at all sets done at that weight
    top = [s[1] for s in working(cur['sets']) if abs(s[0] - w) <= SAME_WEIGHT_TOL * max(w, 1)]
    ptop = [s[1] for s in working(prev['sets']) if abs(s[0] - pw) <= SAME_WEIGHT_TOL * max(pw, 1)]
    n = min(len(top), len(ptop))  # different set counts: compare only the sets both sessions have
    diff = sum(top[:n]) - sum(ptop[:n])
    sets_note = f',这次 {len(top)} 组 上次 {len(ptop)} 组' if len(top) != len(ptop) else ''
    if diff:
        return ('reps' if diff > 0 else 'down'), f'这个重量前 {n} 组合计 {diff:+d} 次{sets_note}'
    return 'same', '和上次一样' + sets_note


def summarize(days):
    assign_templates(days)
    last_sess = {}                    # template -> moves of its previous session
    last_slot = {}                    # slot -> previous move; slot = (template, name, nth time today)
    history = defaultdict(list)       # slot -> verdicts in order
    slot_of = {}                      # id(move) -> slot
    for d in days:
        nth = defaultdict(int)
        for m, p in align(last_sess.get(d['template'], []), d['moves']):  # p: aligned move of last session
            key = slot_of[id(m)] = (d['template'], m['name'], nth[m['name']])
            nth[m['name']] += 1
            m['best'] = best_set(m['sets'], m['assist'])
            e = e1rm(m['best'][0], m['best'][1])
            m['e1rm'] = round(e) if e else None
            ref = p if p and p['name'] == m['name'] else last_slot.get(key) or p  # not last time: an older session, else the replaced move
            m['verdict'], m['detail'] = judge(m, ref)
            if ref and ref['name'] == m['name'] and ref['pos'] != m['pos']:
                m['prev_pos'] = ref['pos']
                m['detail'] += f",上次第 {ref['pos']} 个"
            m['add_weight'] = add_weight(m)
            if m['verdict'] in UP + ('same', 'down', 'watch'):
                history[key].append(m['verdict'])
            tail = history[key][-STALL_SESSIONS:]
            m['stall'] = len(tail) == STALL_SESSIONS and not any(v in UP for v in tail)
            last_slot[key] = m
        last_sess[d['template']] = d['moves']

    templates = defaultdict(lambda: {'sessions': 0, 'last_date': ''})
    for d in days:
        t = templates[d['template']]
        t['sessions'] += 1
        t['last_date'] = d['date']
        t['plan'] = t.get('plan') or '增肌' in d['title']
    templates = sorted(({'name': k, **v} for k, v in templates.items()), key=lambda t: t['last_date'], reverse=True)
    templates.sort(key=lambda t: not t['plan'])  # 增肌 templates first, each group most recent first

    weeks = defaultdict(lambda: defaultdict(int))  # Monday -> verdict -> count
    for d in days:
        day = dt.date.fromisoformat(d['date'])
        wk = weeks[(day - dt.timedelta(days=day.weekday())).isoformat()]
        for m in d['moves']:
            wk[m['verdict']] += 1
    weekly = [{'week': k, **v} for k, v in sorted(weeks.items())]

    stalls = []
    seen = set()
    for d in reversed(days):
        for m in d['moves']:
            key = slot_of[id(m)]
            if key in seen:
                continue
            seen.add(key)
            if m['stall']:
                stalls.append({'template': d['template'], 'pos': m['pos'], 'name': m['name'], 'date': d['date']})

    for d in days:
        for m in d['moves']:
            if m['verdict'] == 'weight':
                m['new_weight_sets'] = at_best(m)  # working sets at the new best weight (vs all working sets: a partial ↑)
            if m['assist']:
                m['e1rm'] = None  # assistance weight: e1RM means nothing
            m['sets'] = [s if s[2] else s[:2] for s in m['sets']]
            m['best'] = m['best'][:2]
    return {'days': days, 'templates': templates, 'stalls': stalls, 'weekly': weekly,
            'summary': {'days': len(days), 'first_date': days[0]['date'], 'last_date': days[-1]['date']}}


def attach_health(days):
    """Apple Health state on each training day (healthstore: date -> sleep h, deep min, hrv, rhr; sleep counts
    toward the day you wake up). Shown as context only — over Jun–Oct it didn't correlate with progress."""
    health = healthstore.load()
    for d in days:
        h = health.get(d['date']) or {}
        day = dt.date.fromisoformat(d['date'])
        state, bad = {}, []
        for k, worse in HEALTH_BAD.items():
            if h.get(k) is None:
                continue
            state[k] = round(h[k], 1) if k == 'sleep' else round(h[k])
            prior = [v for i in range(1, HEALTH_BASE_DAYS + 1)
                     if (v := (health.get((day - dt.timedelta(days=i)).isoformat()) or {}).get(k)) is not None]
            if len(prior) >= 4 and worse(h[k], sum(prior) / len(prior)):
                bad.append(k)
        if state:
            d['health'] = {**state, 'bad': bad}


def encrypt_health(health):
    """The page is public, so health goes in AES-GCM encrypted with HEALTH_KEY (GitHub secret, 32 bytes base64url).
    The page decrypts it only when opened with #k=<key> (the fragment never reaches the server) or a key it saved
    before. No key here (local build) → no health in the page at all; deploy.py refuses such a page."""
    key = os.environ.get('HEALTH_KEY')
    if not key:
        print('HEALTH_KEY not set: health left out')
        return None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = os.urandom(12)
    ct = AESGCM(base64.urlsafe_b64decode(key + '=' * (-len(key) % 4))).encrypt(iv, json.dumps(health).encode(), None)
    return {'iv': base64.b64encode(iv).decode(), 'ct': base64.b64encode(ct).decode()}


def build():
    days = load_days()
    attach_health(days)
    data = summarize(days)
    data['generated_at'] = dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes')
    health = {d['date']: d.pop('health') for d in data['days'] if 'health' in d}
    tpl = open(os.path.join(ROOT, 'src', 'template.html'), encoding='utf-8').read()
    d3 = open(os.path.join(ROOT, 'vendor', 'd3.v7.min.js'), encoding='utf-8').read()
    common = open(os.path.join(ROOT, 'src', 'common.js'), encoding='utf-8').read()
    page = (tpl.replace('/*__D3__*/', d3).replace('/*__COMMON__*/', common)
               .replace('/*__DATA__*/', 'window.DASH = ' + json.dumps(data, ensure_ascii=False).replace('</', '<\\/') + ';'
                        + 'window.HEALTH = ' + json.dumps(encrypt_health(health)) + ';'))
    os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
    out = os.path.join(ROOT, 'dist', 'index.html')
    open(out, 'w', encoding='utf-8').write(page)
    s = data['summary']
    print(f"built {out}: {len(page) // 1024} KB, {s['days']} sessions {s['first_date']}..{s['last_date']}, "
          f"{len(data['templates'])} templates, {len(data['stalls'])} stalls")


if __name__ == '__main__':
    build()
