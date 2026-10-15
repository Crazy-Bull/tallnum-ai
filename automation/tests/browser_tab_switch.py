"""Opt-in existing-Chrome tab switching regression; creates no tabs or inputs."""
import argparse
import json
from pathlib import Path
import time

from automation.browser import existing_endpoint, select_existing_page, READ_STATE
from automation.common import atomic_json
from automation.existing_browser import ExistingConnection


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--cycles',type=int,default=100)
    args=parser.parse_args()
    if not 1<=args.cycles<=100: parser.error('cycles must be between 1 and 100')
    connection=ExistingConnection(existing_endpoint())
    page=select_existing_page(connection.contexts)
    try:
        targets=connection.call('Target.getTargets')['targetInfos']
        other=next((t for t in targets if t['type']=='page' and t['url'].startswith('chrome://')),None)
        if other is None: raise RuntimeError('An existing chrome:// tab is required; no tab was created')
        control=args.directory/'control.json'
        before=page.evaluate(READ_STATE)
        journal=args.directory/'actions.jsonl'
        offset=journal.stat().st_size
        assert json.loads(control.read_text())['mode']=='run','Start autoplay first'
        for i in range(args.cycles):
            connection.call('Target.activateTarget',{'targetId':other['targetId']})
            time.sleep(.25)
            page.bring_to_front()
            time.sleep(.25)
            assert json.loads(control.read_text())['mode']=='run',f'Autoplay paused at switch {i+1}'
            if (i+1)%20==0: print(f'Checked {i+1} tab-switch cycles',flush=True)
        after=page.evaluate(READ_STATE)
        with journal.open('rb') as stream:
            stream.seek(offset)
            records=[json.loads(line) for line in stream.read().splitlines() if line]
        confirmed=sum('after' in row for row in records)
        assert confirmed,'No confirmed game progress during switching'
        result={'passed':True,'cycles':args.cycles,'targetId':page.target_id,
                'confirmedActions':confirmed,'initialActions':before['actions'],'finalActions':after['actions'],
                'initialDrops':before['drops'],'finalDrops':after['drops'],'controller':'run'}
        atomic_json(args.directory/'tab-switch-regression.json',result)
        print(json.dumps(result),flush=True)
    finally:
        try: page.bring_to_front()
        finally: connection.close()


if __name__=='__main__': main()
