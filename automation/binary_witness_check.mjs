// Independent rule parity for a controlled draw path, not a seeded RNG test.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createTallnumGame, dropTile, groupTiles, edgeMerge} from './vendor/tallnum.mjs';

const report=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
let state=createTallnumGame({towerLimit:10,numberSet:'standard',seed:123});
const board=s=>s.tower.map(t=>[t.value,t.physicalCount,t.kind]);
let peak=2;
for(const row of report.trace){
  assert.deepEqual(board(state),row.before);
  if(row.draw!==null){
    assert(state.unlocked.includes(row.draw));
    state={...state,queue:[row.draw,...state.queue.slice(1)]};
    state=dropTile(state);
  }else if(row.action.kind==='group')state=groupTiles(state,row.action.indices);
  else if(row.action.kind==='edge')state=edgeMerge(state);
  else throw new Error('Unsupported witness action');
  assert.deepEqual(board(state),row.after);
  assert.deepEqual(state.unlocked,row.unlocked);
  assert.equal(state.gameOver,false);
  peak=Math.max(peak,state.tower.reduce((n,t)=>n+t.physicalCount,0));
}
assert.deepEqual(board(state),[[report.target,1,'tile']]);
assert.equal(peak,report.maximumPhysicalCells);
console.log(JSON.stringify({actions:report.trace.length,originalEngineParity:true,maximumPhysicalCells:peak,seededRngWitness:false}));
