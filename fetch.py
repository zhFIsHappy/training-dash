"""Fetch the last few days of 训记 trainings (full mode) into data/trains/YYYY-MM-DD.json.

Key: XUNJI_API_KEY env var. Days are America/Los_Angeles dates. A day is written only when it has trainings and the
content changed; an empty reply never replaces a day that has trainings (a glitch must not wipe history — a training
deleted in the app has to be removed from data/trains by hand).
"""
import datetime as dt
import gzip
import json
import os
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
URL = 'https://trains.xunjiapp.cn/api_trains_for_llm_v2'
DAYS_BACK = 7               # re-read a week: catches late edits and days the job didn't run


def fetch(datestr, key, tries=3):
    body = json.dumps({'schema_version': 'train_open_api_v2', 'datestr': datestr, 'include_full_data': True}).encode()
    req = urllib.request.Request(URL, body, {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    raw = urllib.request.urlopen(req, timeout=30).read()
    data = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    if isinstance(data.get('res'), dict):
        return data
    msg = json.dumps(data, ensure_ascii=False)
    if ('frequent' in msg or '频繁' in msg) and tries > 1:     # rate limit: 30 s per day in full mode
        time.sleep(31)
        return fetch(datestr, key, tries - 1)
    raise RuntimeError(f'{datestr}: {msg[:300]}')


def main():
    key = os.environ.get('XUNJI_API_KEY')
    if not key:
        sys.exit('XUNJI_API_KEY is not set')
    today = dt.datetime.now(ZoneInfo('America/Los_Angeles')).date()
    changed = []
    for i in range(DAYS_BACK - 1, -1, -1):
        datestr = (today - dt.timedelta(days=i)).isoformat()
        data = fetch(datestr, key)
        path = os.path.join(ROOT, 'data', 'trains', f'{datestr}.json')
        text = json.dumps(data, ensure_ascii=False)
        old = open(path, encoding='utf-8').read() if os.path.exists(path) else None
        if data['res'].get('trains') and text != old and not (old and data['res'].get('truncated')):
            open(path, 'w', encoding='utf-8').write(text)
            changed.append(datestr)
    print('updated:', ', '.join(changed) or 'nothing')


if __name__ == '__main__':
    main()
