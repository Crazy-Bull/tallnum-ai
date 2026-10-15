import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createTallnumGame,dropTile,rotateTower,groupTiles,edgeMerge} from '../vendor/tallnum.mjs';

const replay=JSON.parse(readFileSync(process.argv[2],'utf8'));
let complete=createTallnumGame({towerLimit:replay.initial.towerLimit,numberSet:'standard',seed:replay.seed});
let bounded=structuredClone(complete);
const apply=(state,a)=>a.kind==='drop'?dropTile(state):a.kind==='up'||a.kind==='down'?rotateTower(state,a.kind):
  a.kind==='group'?groupTiles(state,a.indices):edgeMerge(state);
const comparable=state=>{
  const {actionLog,updatedAt,...rest}=state;
  return rest;
};
const kinds=new Set();
for(const row of replay.trace){
  kinds.add(row.action.kind);
  bounded.actionLog=[];
  complete=apply(complete,row.action);
  bounded=apply(bounded,row.action);
  assert.deepEqual(comparable(bounded),comparable(complete));
}
for(const kind of ['drop','up','down','group','edge'])assert(kinds.has(kind),`Missing ${kind}`);
console.log(JSON.stringify({actions:replay.trace.length,kinds:[...kinds],allGameStateFieldsMatch:true}));
