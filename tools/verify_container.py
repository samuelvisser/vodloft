"""Check a freshly started VodLoft container through its public HTTP interface."""
import argparse
import base64
import hashlib
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.request


def verify(base: str, password: str, timeout: int):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, *, method='GET', body=None, expected=200):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base.rstrip('/') + path, method=method, data=data,
            headers={'Content-Type': 'application/json'} if body is not None else {})
        try:
            response = opener.open(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read()
            assert response.status == expected, f'{path}: HTTP {response.status}, expected {expected}: {content[:300]!r}'
            return content
    deadline = time.monotonic() + timeout
    while True:
        try:
            html = request('/').decode()
            if 'VodLoft' in html:
                # nginx serves the shell before the ASGI lifespan is ready.
                request('/api/auth/status', expected=401)
                break
        except (OSError, AssertionError):
            if time.monotonic() >= deadline:
                raise
        time.sleep(2)
    assert '<div id="root">' in html
    for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', html):
        assert request(asset), f'Empty production asset: {asset}'
    request('/api/auth/status', expected=401)
    request('/api/auth/login', method='POST', body={
        'username': 'admin', 'passwordHash': base64.urlsafe_b64encode(hashlib.sha256(password.encode()).digest()).decode().rstrip('=')}, expected=204)
    assert json.loads(request('/api/auth/status'))['authenticated']
    request('/api/onboarding/complete', method='POST')
    assert json.loads(request('/api/vodloft/me'))['role'] == 'admin'
    assert json.loads(request('/api/vodloft/library')) == []
    home = json.loads(request('/api/vodloft/home'))
    assert home['recent'] == [] and home['activity'] == []
    sources = json.loads(request('/api/vodloft/sources'))
    assert {source['source_id'] for source in sources} == {'yt-dlp', 'dailywire', 'npo'}, json.loads(request('/api/vodloft/sources/runtimes'))
    assert {source['source_id']: source['version'] for source in sources} == {
        'yt-dlp': '1.0.1', 'dailywire': '1.0.0', 'npo': '1.0.0'}
    runtime = json.loads(request('/api/vodloft/sources/runtimes'))
    assert runtime['active'] == {'yt-dlp': '1.0.1', 'dailywire': '1.0.0', 'npo': '1.0.0'}
    for source in ('yt-dlp', 'dailywire', 'npo'):
        verified = next(event['manifest'] for event in reversed(runtime['history'])
            if event.get('source_id') == source and event.get('manifest'))
        assert verified['python_version'] and verified['helper_versions']['ffmpeg']
        assert verified['metadata_schema_version'] == 1
    request('/feeds/vodloft/secret-fixture-token.xml', expected=404)
    request('/api/vodloft/stream/secret-fixture-token', expected=404)
    request('/api/auth/logout', method='POST', expected=204)
    request('/api/vodloft/library', expected=401)
    print('Container acceptance passed: authentication, production assets, library, and all isolated Sources.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url')
    parser.add_argument('--password', required=True)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    verify(args.base_url, args.password, args.timeout)
