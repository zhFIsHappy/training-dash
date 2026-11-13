"""Upload dist/index.html to COS as dash/index.html (served at https://training.zhehaofan.com/dash/).

Credentials: TENCENT_SECRET_ID / TENCENT_SECRET_KEY env vars (CI), else ~/.tccli/default.credential (local).
"""
import json
import os

from qcloud_cos import CosConfig, CosS3Client

ROOT = os.path.dirname(os.path.abspath(__file__))
BUCKET = 'zhfan-training-1515704897'
REGION = 'ap-hongkong'


def credentials():
    sid, skey = os.environ.get('TENCENT_SECRET_ID'), os.environ.get('TENCENT_SECRET_KEY')
    if sid and skey:
        return sid, skey
    c = json.load(open(os.path.expanduser('~/.tccli/default.credential')))
    return c['secretId'], c['secretKey']


def deploy():
    page = open(os.path.join(ROOT, 'dist', 'index.html'), encoding='utf-8').read()
    if 'window.HEALTH = null' in page and os.environ.get('ALLOW_NO_HEALTH') != '1':
        raise SystemExit('built without HEALTH_KEY: the live page would lose health (deploy from CI, or ALLOW_NO_HEALTH=1)')
    sid, skey = credentials()
    client = CosS3Client(CosConfig(Region=REGION, SecretId=sid, SecretKey=skey, Scheme='https'))
    client.upload_file(Bucket=BUCKET, Key='dash/index.html', LocalFilePath=os.path.join(ROOT, 'dist', 'index.html'),
                       ContentType='text/html; charset=utf-8', CacheControl='no-cache')
    print('uploaded dash/index.html')


if __name__ == '__main__':
    deploy()
