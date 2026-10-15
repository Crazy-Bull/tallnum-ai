import {createTallnumGame,dropTile,rotateTower,groupTiles,edgeMerge} from '../vendor/tallnum.mjs';
const cases=[];
for(let seed=1;seed<=100;seed++){
 let s=createTallnumGame({towerLimit:7,numberSet:'standard',seed}),actions=[];
 for(let step=0;step<150 && !s.gameOver;step++){
  const choices=[{kind:'drop'},{kind:'up'},{kind:'down'},{kind:'edge'}];
  for(let i=0;i<s.tower.length-1;i++)choices.push({kind:'group',indices:[i,i+1]});
  const op=choices[(seed*17+step*7)%choices.length];
  const next=op.kind==='drop'?dropTile(s):op.kind==='edge'?edgeMerge(s):op.kind==='group'?groupTiles(s,op.indices):rotateTower(s,op.kind);
  if(next!==s){actions.push(op);s=next;}
 }
 cases.push({seed,actions,result:{tower:s.tower.map(t=>[t.value,t.physicalCount,t.kind]),queue:s.queue,rngState:s.rngState,drops:s.drops,actions:s.actions,gameOver:s.gameOver}});
}
console.log(JSON.stringify(cases));
