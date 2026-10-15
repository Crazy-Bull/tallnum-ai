"""Verify compact published evidence without tables, native code or a browser."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'docs/validation/route-execution-2026-10'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

manifest = read(BASE/'manifest.json')
for item in manifest['files']:
    assert digest(ROOT/item['file']) == item['sha256'], item['file']

expected = {8192:(94,308,60,14),10240:(87,426,64,14),12288:(91,448,80,10)}
for target, (wins, stages, peak, calls) in expected.items():
    folder = BASE/str(target)
    route = read(folder/'route.json')
    config = read(folder/'configuration.json')
    summary = read(folder/'summary.json')
    result = read(folder/'repair-results.json')
    assert digest(folder/'route.json') == config['routeSha256']
    assert digest(ROOT/'desktop/peak13-assets/probability-catalog.json') == config['catalogSha256']
    for name, value in config['sources'].items():
        archived = folder/'sources'/name
        source = archived if archived.exists() else ROOT/'automation'/name
        assert digest(source) == value, name
    assert route['target'] == target and len(route['steps']) == stages
    leaves = Counter(s['target'] for s in route['steps']
                     if s['kind']=='leaf' and s['policyCells']==5)
    assert max(leaves) == peak and leaves[peak] == calls
    assert result['acceptancePassed'] and config['probabilityOnly'] and not config['forcedDraws']
    assert summary['complete'] and summary['completed'] == 100 and summary['successes'] == wins
    assert len(summary['records']) == 100
    assert [r['seed'] for r in summary['records']] == config['seeds']
    assert sum(r['outcome']=='success' for r in summary['records']) == wins
    assert not any(r['outcome']=='limit' for r in summary['records'])
    engine = summary['originalEngineCheck']
    assert engine['games'] == 100 and engine['seededRngParity']
    print(f'{target}: {wins}/100; {stages} stages; five-cell peak {peak}, {calls} main-route calls; identities verified')

print('Compact evidence verified; full action replays and probability tables are not included.')
