import {createTallnumGame,dropTile,rotateTower,groupTiles,edgeMerge} from '../vendor/tallnum.mjs';
import fs from 'node:fs';

const view = s => ({tower:s.tower.map(t=>[t.value,t.physicalCount,t.kind]),queue:s.queue,
  rngState:s.rngState,drops:s.drops,actions:s.actions,gameOver:s.gameOver,unlocked:s.unlocked});
const apply = (s, op) => op.kind==='drop'?dropTile(s):op.kind==='edge'?edgeMerge(s):
  op.kind==='group'?groupTiles(s,op.indices):rotateTower(s,op.kind);
const input = fs.readFileSync(0,'utf8').trim();
if(input){
  const fixtures=JSON.parse(input);
  console.log(JSON.stringify(fixtures.map(({state,actions})=>{
    let s=state; const trace=[];
    for(const op of actions){s=apply(s,op);trace.push(view(s));}
    return trace;
  })));
}else{
  const cases=[];
  for(const cells of [7,10])for(let seed=1;seed<=100;seed++){
    let s=createTallnumGame({towerLimit:cells,numberSet:'standard',seed});
    const actions=[],trace=[view(s)];
    for(let step=0;step<250&&!s.gameOver;step++){
      const choices=[{kind:'drop'},{kind:'up'},{kind:'down'},{kind:'edge'}];
      for(let start=0;start<s.tower.length-1;start++)
        for(let length=2;length<=5&&start+length<=s.tower.length;length++)
          choices.push({kind:'group',indices:Array.from({length},(_,i)=>start+i)});
      const op=choices[(seed*17+step*7)%choices.length];
      const next=apply(s,op);
      if(next!==s){actions.push(op);s=next;trace.push(view(s));}
    }
    cases.push({seed,cells,actions,trace});
  }
  console.log(JSON.stringify(cases));
}
