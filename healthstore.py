"""Apple Health days (date -> sleep h, deep min, steps, rhr, hrv, kcal), kept in the public repo only encrypted.

data/health/daily.enc.json holds them AES-GCM encrypted with HEALTH_STORE_KEY (GitHub secret, 32 bytes base64url;
locally ~/.config/training-dash/health_store_key). This is a different key from HEALTH_KEY, which only encrypts the
copy embedded in the page. No key → load() gives {} and save() refuses.
"""
import base64
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, 'data', 'health', 'daily.enc.json')
LOCAL_KEY = os.path.expanduser('~/.config/training-dash/health_store_key')


def _aes():
    key = os.environ.get('HEALTH_STORE_KEY')
    if not key and os.path.exists(LOCAL_KEY):
        key = open(LOCAL_KEY).read().strip()
    if not key:
        return None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(base64.urlsafe_b64decode(key + '=' * (-len(key) % 4)))


def load():
    aes = _aes()
    if not aes or not os.path.exists(PATH):
        if not aes:
            print('HEALTH_STORE_KEY not set: no health')
        return {}
    box = json.load(open(PATH, encoding='utf-8'))
    return json.loads(aes.decrypt(base64.b64decode(box['iv']), base64.b64decode(box['ct']), None))


def save(health):
    aes = _aes()
    if not aes:
        raise SystemExit('HEALTH_STORE_KEY not set: refusing to save health')
    iv = os.urandom(12)
    ct = aes.encrypt(iv, json.dumps(dict(sorted(health.items())), separators=(',', ':')).encode(), None)
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump({'iv': base64.b64encode(iv).decode(), 'ct': base64.b64encode(ct).decode()}, open(PATH, 'w'))
