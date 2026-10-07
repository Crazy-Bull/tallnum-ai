// Independent original-engine replay with seeded RNG; bounded to one game in memory.
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';
import {createTallnumGame,dropTile,rotateTower,groupTiles,edgeMerge} from './vendor/tallnum.mjs';
const path=process.argv[2];
const helper=fileURLToPath(new URL('./stream_replay_report.py',import.meta.url));
const python=process.env.TALLNUM_PYTHON || 'python';
const source=spawn(python,[helper,path],{stdio:['ignore','pipe','inherit']});
const finished=new Promise((resolve,reject)=>{
  source.on('error',reject);
  source.on('close',code=>code===0 ? resolve() : reject(new Error(`Replay stream failed: ${code}`)));
});
finished.catch(()=>{}); // Keep early stream errors handled until the loop awaits completion.
const board=s=>s.tower.map(t=>[t.value,t.physicalCount,t.kind]);
let games=0,actions=0;
try {
  for await(const line of readline.createInterface({input:source.stdout,crlfDelay:Infinity})) {
    const {mode,replay}=JSON.parse(line);
    let state=createTallnumGame({towerLimit:replay.initial.towerLimit,numberSet:'standard',seed:replay.seed});
    if(mode==='synthetic-checkpoint')state={...state,...replay.initial};
    assert.deepEqual(board(state),board(replay.initial));
    assert.deepEqual(state.queue,replay.initial.queue);
    assert.equal(state.rngState,replay.initial.rngState);
    for(const row of replay.trace){
      const a=row.action;
      if(a.kind==='drop')state=dropTile(state);
      else if(a.kind==='up'||a.kind==='down')state=rotateTower(state,a.kind);
      else if(a.kind==='group')state=groupTiles(state,a.indices);
      else if(a.kind==='edge')state=edgeMerge(state);
      else throw Error('Unknown action');
      assert.deepEqual(board(state),row.board);
      assert.deepEqual(state.queue,row.queue);
      assert.deepEqual(state.unlocked,row.unlocked);
      assert.equal(state.rngState,row.rngState);
      assert.equal(state.gameOver,row.gameOver);
      actions++;
    }
    games++;
    if(games%10===0)console.log(JSON.stringify({stage:'replay-check',games,actions}));
  }
  await finished;
  if(!games)throw Error('Validation report contains no replays');
  const result={games,actions,seededRngParity:true,forcedDraws:false};
  const saved=spawnSync(python,[helper,'--attach',path,JSON.stringify(result)],{encoding:'utf8'});
  if(saved.error)throw saved.error;
  if(saved.status!==0)throw Error(saved.stderr || 'Cannot save original engine check');
  console.log(JSON.stringify(result));
} catch(error) {
  source.kill();
  await finished.catch(()=>{});
  throw error;
}
