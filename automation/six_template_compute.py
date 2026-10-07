"""Generate, solve and evaluate bounded six-cell single templates sequentially.

Run from the project root. All large outputs use the configured F-drive root.
Generation checkpoints resume automatically; completed stages are journaled.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .common import atomic_json
from .library import table_header
from .six_template_finish import validate_configuration


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets',nargs='+',type=int,default=[32,40])
    parser.add_argument('--max-value',type=int,default=48)
    parser.add_argument('--aggressiveness',type=float,default=.01)
    parser.add_argument('--data-root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--strict-single',action='store_true',help='protect TARGET head; residual <=1 cell with value <=8')
    parser.add_argument('--generator',type=Path)
    parser.add_argument('--bridge',type=Path)
    args=parser.parse_args()
    if not 0<=args.aggressiveness<=min(args.targets)/7.5:
        parser.error('Invalid aggressiveness')
    if not all(24<=t<=args.max_value<=65535 and args.max_value>=48 and t%2==0 for t in args.targets):
        parser.error('Requires even targets within the intermediate bound')
    root=Path(__file__).resolve().parent.parent
    native=root/'automation/runs/six48'
    tag=format(args.aggressiveness,'.12g').replace('.','')
    for target in args.targets:
        profile='strict-single-v2' if args.strict_single else 'cleanexit'
        work=root/f'automation/runs/six{target}-alpha{tag}-{profile}'
        work.mkdir(parents=True,exist_ok=True)
        storage=args.data_root.resolve()/f'six{target}-single-max{args.max_value}-alpha{tag}-{profile}'
        storage.mkdir(parents=True,exist_ok=True)
        table=storage/'table.bin'
        config={'cells':6,'target':target,'exit':'single','maxGoalCells':1,
                'maxValue':args.max_value,'bases':[1,3,5,15],
                'aggressiveness':args.aggressiveness,'model':'iid-six-clean-exit-v3',
                'entry':'uniform-first-36','successSide':'above','successNoExtraCombos':True,'workspace':str(work),
                'dataDirectory':str(storage),'table':str(table),
                'checkpoint':str(storage/'generator.checkpoint.bin'),
                'nativeBridge':str(root/'desktop/native/tallnum_automation_six_clean.exe'),
                'simulationSeed':600001+target*1000}
        if args.strict_single:
            config.update(singleEdgeGuard=True,singleTidyExit=True,
                          model='iid-six-strict-single-v2')
        if args.bridge:config['nativeBridge']=str(args.bridge.resolve())
        # Reuse the old six-cell table as a migration source. The generator
        # expands every legacy-success row under clean-exit semantics.
        reuse_table=None
        for candidate in ([] if args.strict_single else sorted(root.glob('automation/runs/six*-alpha*/configuration.json'))):
            try:
                prior=json.loads(candidate.read_text(encoding='utf-8'))
                prior_table=Path(prior['table'])
                header=table_header(prior_table)
                if (header['cells']==6 and header['target']==target and header['maxValue']==args.max_value
                        and header['maxGoalCells']==1 and not header['successNoExtraCombos']):
                    reuse_table=prior_table
                    break
            except (OSError,KeyError,ValueError):
                continue
        if reuse_table is not None:
            config['reusedLegacyTable']=str(reuse_table)
        config_path=work/'configuration.json'
        if config_path.exists() and json.loads(config_path.read_text())!=config:
            raise ValueError('Existing workspace has different parameters: '+str(work))
        atomic_json(config_path,config)
        stage_path=work/'progress.json'
        previous=json.loads(stage_path.read_text()) if stage_path.exists() else {}
        stages={name:previous[name] for name in ('generate','solve','evaluate') if name in previous}

        def run_stage(name,command):
            print(json.dumps({'target':target,'stage':name,'status':'started'}),flush=True)
            atomic_json(work/(name+'-command.json'),command)
            atomic_json(stage_path,{**stages,'active':name,'status':'running'})
            with (work/(name+'.log')).open('a') as log:
                result=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
            if result.returncode:
                atomic_json(stage_path,{**stages,'active':name,'status':'failed','returnCode':result.returncode})
                raise RuntimeError(f'Target {target}, {name} failed ({result.returncode}); see {work/name}.log')
            stages[name]=True
            atomic_json(stage_path,{**stages,'active':None,'status':'stage-completed'})
            print(json.dumps({'target':target,'stage':name,'status':'completed'}),flush=True)

        if not stages.get('generate'):
            control=work/'generator.control.txt';control.write_text('run')
            generator=args.generator.resolve() if args.generator else root/'desktop/native/tallnum_reachable_clean.exe'
            generate=[str(generator),
                '--cells','6','--target',str(target),'--max-value',str(args.max_value),
                '--max-goal-cells','1','--bases','1,3,5,15','--success-side','above',
                '--success-no-extra-combos','1',
                '--output',str(table),'--checkpoint',config['checkpoint'],
                '--checkpoint-seconds','120','--control',str(control),
                '--events',str(work/'generator.events.jsonl')]
            if args.strict_single:generate+=['--single-edge-guard','1','--single-tidy-exit','1']
            if reuse_table is not None:
                generate.extend(['--reuse-table',str(reuse_table)])
            run_stage('generate',generate)
        validate_configuration(config,table_header(table))
        if not stages.get('solve'):
            control=work/'vi.control.txt';control.write_text('run')
            checkpoint=storage/'vi.checkpoint.bin'
            command=[str(native/'tallnum_vi_six.exe'),str(table),'1500','1e-10',
                     str(storage/'vi.values.bin'),'--aggressiveness',str(args.aggressiveness),
                     '--checkpoint',str(checkpoint),'--checkpoint-seconds','120',
                     '--control',str(control),'--events',str(work/'vi.events.jsonl')]
            if checkpoint.exists():command+=['--resume',str(checkpoint)]
            run_stage('solve',command)
            vi=json.loads(Path(str(table)+'.result.json').read_text())
            if vi['max_delta']>vi['tolerance']:
                stages['solve']=False;atomic_json(stage_path,stages)
                raise RuntimeError(f'Target {target} not converged; preserve checkpoint and increase round limit')
        if not stages.get('evaluate'):
            run_stage('evaluate',[sys.executable,'-m','automation.six_template_finish',
                                  '--workspace',str(work),'--exact'])
        manifest=json.loads((work/'result.json').read_text())
        stats=manifest['statistics']
        lines=[f'# 六格普通{target}单格，激进度{args.aggressiveness}',
               '',f'中间数字上限{args.max_value}；2、4、6、8、10、15独立等概率且全部解锁。',
               '标准基1、3、5、15；虚拟固定边界F不占六个可用物理格；两个预告的36种组合等概率。',
               '',f"转移表状态数：{manifest['header']['states']:,}。",
               f"固定策略图状态数：{stats['states']:,}。",
               f"原规则成功概率：{stats['p']:.12g}。",
               f"包含失败重开期望投放数：{stats['expectedTotalDrops']}。",
               f"u={stats['u']}，v={stats['v']}，c={stats['c']}。",
               f"策略文件：{manifest['policy']}，{Path(manifest['policy']).stat().st_size:,}字节。",
               '',f'构造人工终止概率为每次非成功投放 {args.aggressiveness*7.5/target:.12g}，成功最后一步豁免。',
               '所有统计评估均关闭该人工风险。方程评估为检查残差的浮点解；没有证明期望投放数全局最优。',
               '该模型没有采用真实游戏的隐藏队列或出数池解锁。',
               '', '复算入口（在项目根目录运行，自动复用已完成阶段及未完成阶段的断点）：',
               f'`python -m automation.six_template_compute --targets {target} --max-value {args.max_value} --aggressiveness {args.aggressiveness}`',
               '', '仅重新导出与评估：',
               f'`python -m automation.six_template_finish --workspace automation/runs/{work.name} --exact`',
               '', '参数见configuration.json；阶段进度见progress.json；统计见statistics.json；随机测试见simulation.json。',
               '生成器使用分段记录、有限临时动作缓存和紧凑状态索引；小规模扩容、清空缓存和恢复断点的表与原版逐字节一致。']
        (work/'README.zh-CN.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        atomic_json(stage_path,{**stages,'active':None,'status':'completed'})


if __name__=='__main__':main()
