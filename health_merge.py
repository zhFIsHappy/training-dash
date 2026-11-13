"""Merge Apple Health days sent by the iPhone Shortcut (a repository_dispatch event) into the encrypted store (healthstore.py).

Payload: one day {"date": "2026-10-24", "sleep": 7.2, "deep": 61, "rhr": 55, "hrv": 52} or {"days": [<day>, ...]}.
Fields: sleep h (counted toward the day you wake up), deep min, rhr, hrv, steps, kcal. Sleep may instead be sent in
minutes as sleep_min. Only fields sent with a value change; an empty one (phone locked, no reading) keeps the old value.

The iPhone Shortcut sends raw lists joined by "|" instead (Shortcuts can't do this math simply): sleep_v = stage names
of last night's Sleep samples (English or Chinese UI), sleep_d = their durations ("28:09" = m:ss, "1:06:52", or seconds),
sleep_s = each sample's source (Watch + a sleep app can both write stages for the same night: only one source
is counted), hrv / rhr = all of today's readings (median, so one outlier reading can't move it).
"""
import datetime as dt
import json
import os
import re
import statistics
from zoneinfo import ZoneInfo

import healthstore

FIELDS = ('sleep', 'deep', 'steps', 'rhr', 'hrv', 'kcal')


def num(v):
    try:
        return float(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


def seconds(t):
    t = str(t).strip()
    if ':' in t:
        parts = [float(x) for x in t.split(':')]
        return sum(v * 60 ** i for i, v in enumerate(reversed(parts)))  # m:ss or h:mm:ss
    m = re.match(r'\d+(?:\.\d+)?', re.sub(r',(?=\d{3}\b)', '', t).replace(',', '.'))  # 1,800 → 1800; 40,5 → 40.5
    return float(m.group()) if m else 0


def from_shortcut(d):
    """Turn the Shortcut's raw "|" lists into the stored fields."""
    for k in ('hrv', 'rhr'):
        if isinstance(d.get(k), str):
            found = (re.search(r'\d+(?:\.\d+)?', x.replace(',', '.')) for x in re.split(r'[|\n]', d[k]))
            vals = [v for v in (num(m.group()) for m in found if m) if v]
            d[k] = round(statistics.median(vals)) if vals else None
    if 'sleep_v' in d and 'sleep_s' not in d:  # old Shortcut without sources: stages of two sources would add up
        d.pop('sleep_v'), d.pop('sleep_d', None)
    if 'sleep_v' in d:
        stages, durs = str(d.pop('sleep_v')).split('|'), str(d.pop('sleep_d', '')).split('|')
        sources = str(d.pop('sleep_s')).split('|')
        sources += [''] * (len(stages) - len(sources))  # Source detail can come through empty
        rows = [(st, seconds(du), src) for st, du, src in zip(stages, durs, sources)
                if not re.search(r'awake|in bed|清醒|卧床|在床', st, re.I)]
        staged = [src for st, _, src in rows if re.search(r'core|deep|rem|核心|深|快速', st, re.I)]
        if staged:  # several sources wrote stages: keep one, the Watch if it's there, else the one with most stage samples
            keep = next((s for s in staged if re.search(r'watch|手表', s, re.I)), max(set(staged), key=staged.count))
            rows = [r for r in rows if r[2] == keep]
        samples = [(st, sec) for st, sec, _ in rows]
        if any(re.search(r'core|deep|rem|核心|深|快速', st, re.I) for st, _ in samples):  # Watch stages present: drop
            samples = [(st, sec) for st, sec in samples if re.search(r'core|deep|rem|核心|深|快速', st, re.I)]  # the phone's plain "Asleep" for the same night
        asleep = sum(sec for _, sec in samples)
        deep = sum(sec for st, sec in samples if re.search(r'deep|深', st, re.I))
        d['sleep'] = round(asleep / 3600, 2) if asleep else None
        d['deep'] = round(deep / 60) if asleep else None  # tracked night with no deep sleep = 0, not missing
    return d


def main():
    event = json.load(open(os.environ['GITHUB_EVENT_PATH'], encoding='utf-8'))
    payload = event.get('client_payload') or {}
    days = payload.get('days') or [payload]
    today = dt.datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
    health = healthstore.load()
    for d in days:
        d = from_shortcut(dict(d))
        if not str(d.get('date') or '').strip():
            d['date'] = today  # the Shortcut's date came through empty; it runs the same LA day
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(d.get('date', ''))):
            if num(d.get('sleep_min')) is not None:
                d['sleep'] = num(d['sleep_min']) and round(num(d['sleep_min']) / 60, 2)
            day = health.setdefault(d['date'], dict.fromkeys(FIELDS))
            new = {k: num(d[k]) if k == 'deep' else num(d[k]) or None for k in FIELDS if k in d}  # 0 sleep/HRV/RHR = not measured
            day.update({k: v for k, v in new.items() if v is not None})
    healthstore.save(health)
    print('merged:', ', '.join(str(d.get('date') or today) for d in days))


if __name__ == '__main__':
    main()
