export const TALLNUM_SAVE_VERSION=5;
export const TALLNUM_REPLAY_VERSION=4;
export const TALLNUM_REPLAY_VERSIONS=Object.freeze([3,TALLNUM_REPLAY_VERSION]);
export const TALLNUM_LIMITS=Object.freeze([7,10]);

export const TALLNUM_SETS=Object.freeze({
  standard:Object.freeze({
    id:"standard",name:"Standard",opening:Object.freeze([2,4]),initial:Object.freeze([2,4,8]),
    unlocks:Object.freeze([{total:32,value:6},{total:100,value:10},{total:200,value:15}]),
    families:Object.freeze([{base:2,shape:"square"},{base:6,shape:"rectangle"},{base:10,shape:"circle"},{base:15,shape:"triangle"}])
  }),
  odd:Object.freeze({
    id:"odd",name:"OddSet",opening:Object.freeze([3,6]),initial:Object.freeze([3,6,12]),
    unlocks:Object.freeze([{total:32,value:9},{total:100,value:5},{total:200,value:7}]),
    families:Object.freeze([{base:3,shape:"square"},{base:9,shape:"rectangle"},{base:5,shape:"triangle"},{base:7,shape:"circle"}])
  })
});

const copy=value=>JSON.parse(JSON.stringify(value));
const uint=value=>(Number(value)>>>0)||0x6d2b79f5;

function randomUnit(state){
  let x=uint(state.rngState);x^=x<<13;x^=x>>>17;x^=x<<5;state.rngState=x>>>0;
  return state.rngState/4294967296;
}

function nextId(state){state.nextId=(Number(state.nextId)||0)+1;return `t${state.nextId}`}
function makeTile(state,value,extra={}){return {id:nextId(state),value,physicalCount:1,kind:"tile",...extra}}
function setInfo(state){return TALLNUM_SETS[state.numberSet]||TALLNUM_SETS.standard}
function allNumbers(info){return [...info.initial,...info.unlocks.map(rule=>rule.value)]}
function unlockAllNumbers(state){state.unlocked=[...new Set([...state.unlocked,...allNumbers(setInfo(state))])]}

export function towerValue(state){return state.tower.reduce((sum,tile)=>sum+tile.value,0)}
export function physicalCount(state){return state.tower.reduce((sum,tile)=>sum+(Number(tile.physicalCount)||1),0)}
export function towerLimit(state){const limit=Number(state?.towerLimit??10);return TALLNUM_LIMITS.includes(limit)?limit:10}
export function freeSlots(state){return Math.max(0,towerLimit(state)-physicalCount(state))}
export function edgeValue(tile){return Math.floor(Number(tile?.value||0)/10)}
export function canEdgeMerge(first,second){const value=edgeValue(first);return value>0&&value===edgeValue(second)}
export function hasGroup(state){return state.tower.some(tile=>tile.kind==="group")}

export function tileShape(value,numberSet="standard"){
  const info=TALLNUM_SETS[numberSet]||TALLNUM_SETS.standard;
  const family=info.families.find(({base})=>{const quotient=value/base;return Number.isInteger(quotient)&&quotient>=1&&(quotient&(quotient-1))===0});
  return family?.shape||"unknown";
}

function beginAction(state,type){
  const next=copy(state);
  delete next.history;
  next.lastResult={type,merges:0,unlocked:[],addedId:null,addedValue:null,mergeEvents:[],rotatedTower:null,preDropTower:null,afterDropTower:null,organizedTower:null};
  return next;
}

function drawNumber(state){
  let pool=[...state.unlocked];
  if(state.repeatCount>=4&&pool.length>1)pool=pool.filter(value=>value!==state.lastRandomValue);
  const value=pool[Math.min(pool.length-1,Math.floor(randomUnit(state)*pool.length))];
  if(value===state.lastRandomValue)state.repeatCount+=1;else{state.lastRandomValue=value;state.repeatCount=1}
  return value;
}

function mergeTiles(state,index,kind="normal",phase="organize"){
  const first=state.tower[index],second=state.tower[index+1];
  const value=kind==="edge"?edgeValue(first)*2:first.value*2;
  const merged=makeTile(state,value,{physicalCount:1,kind:"tile"});
  const priorEvents=state.lastResult.mergeEvents||[],directSourceIds=[first.id,second.id],sourceIds=[first,second].flatMap(tile=>priorEvents.find(event=>event.id===tile.id)?.sourceIds||[tile.id]);
  state.tower.splice(index,2,merged);priorEvents.push({id:merged.id,value,sourceIds,directSourceIds,phase,tower:copy(state.tower)});state.lastResult.mergeEvents=priorEvents;state.lastResult.merges+=1;
  return merged;
}

function resolveNormal(state,phase="organize"){
  while(true){
    let match=-1;
    for(let index=state.tower.length-2;index>=0;index--){if(state.tower[index].value===state.tower[index+1].value){match=index;break}}
    if(match<0)return;
    mergeTiles(state,match,"normal",phase);
  }
}

function updateUnlocks(state){
  const total=towerValue(state),known=new Set(state.unlocked);
  for(const rule of setInfo(state).unlocks){
    if(total>=rule.total&&!known.has(rule.value)){state.unlocked.push(rule.value);known.add(rule.value);state.lastResult?.unlocked.push(rule.value)}
  }
}

function shiftQueue(state){
  const value=state.queue.shift();state.queue.push(drawNumber(state));return value;
}

function dropInternal(state,{record=true,checkGameOver=true}={}){
  if(state.gameOver)return state;
  const next=record?beginAction(state,"drop"):state;
  if(!next.lastResult)next.lastResult={type:"opening",merges:0,unlocked:[],addedId:null,addedValue:null,mergeEvents:[],rotatedTower:null,preDropTower:null,afterDropTower:null,organizedTower:null};
  const value=shiftQueue(next),added=makeTile(next,value);next.tower.push(added);next.lastResult.addedId=added.id;next.lastResult.addedValue=value;next.lastResult.afterDropTower=copy(next.tower);resolveNormal(next,"after-drop");updateUnlocks(next);
  if(record){next.actions+=1;next.drops+=1;next.actionLog.push("d")}
  if(checkGameOver&&physicalCount(next)>=towerLimit(next))next.gameOver=true;
  next.updatedAt=Date.now();return next;
}

export function createTallnumGame({numberSet="standard",towerLimit:requestedLimit=10,seed=Date.now(),autoStart=true,poolVersion=2}={}){
  const info=TALLNUM_SETS[numberSet];if(!info)throw new Error("未知 Tallnum 数池");
  const limit=Number(requestedLimit);if(!TALLNUM_LIMITS.includes(limit))throw new Error("未知 Tallnum 塔高");
  const resolvedPoolVersion=Number(poolVersion)===1?1:2,unlocked=limit===7&&resolvedPoolVersion>=2?allNumbers(info):[...info.initial];
  const initialSeed=uint(seed),state={version:TALLNUM_SAVE_VERSION,numberSet,towerLimit:limit,poolVersion:resolvedPoolVersion,poolUnlockAction:limit===7&&resolvedPoolVersion>=2?0:null,seed:initialSeed,rngState:initialSeed,nextId:0,tower:[],queue:[...info.opening],unlocked,lastRandomValue:null,repeatCount:0,actions:0,drops:0,actionLog:[],rankedEligible:true,gameOver:false,lastResult:{type:"new",merges:0,unlocked:[],addedId:null,addedValue:null,mergeEvents:[],rotatedTower:null,preDropTower:null,afterDropTower:null,organizedTower:null},createdAt:Date.now(),updatedAt:Date.now()};
  state.queue.push(drawNumber(state),drawNumber(state));
  if(autoStart){dropInternal(state,{record:false,checkGameOver:false});dropInternal(state,{record:false,checkGameOver:false});state.lastResult={type:"new",merges:0,unlocked:[],addedId:null,addedValue:null,mergeEvents:[],rotatedTower:null,preDropTower:null,afterDropTower:null,organizedTower:null}}
  return state;
}

export function dropTile(state){return dropInternal(state)}

export function rotateTower(state,direction){
  if(state.gameOver||state.tower.length<2||!["up","down"].includes(direction))return state;
  const next=beginAction(state,`rotate-${direction}`);
  if(direction==="up")next.tower.push(next.tower.shift());
  else next.tower.unshift(next.tower.pop());
  next.lastResult.rotatedTower=copy(next.tower);
  resolveNormal(next,"before-drop");updateUnlocks(next);next.lastResult.preDropTower=copy(next.tower);
  const value=shiftQueue(next),added=makeTile(next,value);next.tower.push(added);next.lastResult.addedId=added.id;next.lastResult.addedValue=value;next.lastResult.afterDropTower=copy(next.tower);
  resolveNormal(next,"after-drop");updateUnlocks(next);next.actions+=1;next.drops+=1;
  next.actionLog.push(direction==="up"?"u":"n");
  if(physicalCount(next)>=towerLimit(next))next.gameOver=true;
  next.updatedAt=Date.now();return next;
}

export function groupTiles(state,indices){
  if(state.gameOver||hasGroup(state))return state;
  const selected=[...new Set(indices)].filter(Number.isInteger).sort((a,b)=>a-b);
  if(selected.length<2||selected.length>5||selected[0]<0||selected.at(-1)>=state.tower.length||selected.some((value,index)=>index&&value!==selected[index-1]+1))return state;
  const next=beginAction(state,"group"),members=next.tower.slice(selected[0],selected.at(-1)+1),value=members.reduce((sum,tile)=>sum+tile.value,0),physical=members.reduce((sum,tile)=>sum+(tile.physicalCount||1),0);
  next.tower.splice(selected[0],members.length,makeTile(next,value,{kind:"group",physicalCount:physical,members:copy(members)}));
  next.lastResult.organizedTower=copy(next.tower);
  resolveNormal(next,"organize");updateUnlocks(next);next.actions+=1;next.actionLog.push(`g:${selected.join(",")}`);next.updatedAt=Date.now();return next;
}

export function edgeMerge(state){
  if(state.gameOver||!edgePairs(state).length)return state;
  const next=beginAction(state,"edge");
  while(edgePairs(next).length)for(let index=next.tower.length-2;index>=0;index--){
    if(!canEdgeMerge(next.tower[index],next.tower[index+1]))continue;
    mergeTiles(next,index,"edge","organize");index-=1;
  }
  resolveNormal(next,"organize");updateUnlocks(next);next.actions+=1;next.actionLog.push("e");next.updatedAt=Date.now();return next;
}

export function edgePairs(state){
  const pairs=[];for(let index=0;index<state.tower.length-1;index++)if(canEdgeMerge(state.tower[index],state.tower[index+1]))pairs.push([index,index+1]);return pairs;
}

export function validateTallnumState(value){
  const limit=Number(value?.towerLimit??10),legacySmall=limit===7&&value?.poolVersion==null,poolVersion=legacySmall?2:Number(value?.poolVersion??2);
  if(!value||![1,2,3,4,TALLNUM_SAVE_VERSION].includes(value.version)||!TALLNUM_SETS[value.numberSet]||!TALLNUM_LIMITS.includes(limit)||![1,2].includes(poolVersion)||!Array.isArray(value.tower)||!Array.isArray(value.queue)||value.queue.length!==4||!Array.isArray(value.unlocked))return null;
  const validTile=tile=>tile&&typeof tile.id==="string"&&Number.isSafeInteger(tile.value)&&tile.value>0&&Number.isSafeInteger(tile.physicalCount)&&tile.physicalCount>0&&["tile","group"].includes(tile.kind)&&(tile.kind==="tile"||Array.isArray(tile.members)&&tile.members.length>0&&tile.members.every(validTile));
  if(!value.tower.every(validTile)||value.tower.length>10||!value.queue.every(item=>Number.isSafeInteger(item)&&item>0)||!value.unlocked.every(item=>Number.isSafeInteger(item)&&item>0)||!Number.isSafeInteger(value.actions)||value.actions<0||!Number.isSafeInteger(value.drops)||value.drops<0)return null;
  const validAction=action=>typeof action==="string"&&/^(?:d|u|n|e|g:[0-9]+(?:,[0-9]+)+)$/.test(action);
  const replayCapable=value.version===TALLNUM_SAVE_VERSION&&value.rankedEligible!==false;
  if(replayCapable&&(!Number.isSafeInteger(value.seed)||value.seed<0||value.seed>0xffffffff||!Array.isArray(value.actionLog)||value.actionLog.length!==value.actions||!value.actionLog.every(validAction)))return null;
  const normalizeTile=tile=>{const normalized=copy(tile);if(normalized.kind==="group"){normalized.members=normalized.members.map(normalizeTile);normalized.physicalCount=normalized.members.reduce((sum,member)=>sum+member.physicalCount,0)}else normalized.physicalCount=1;return normalized};
  const next=copy(value);next.version=TALLNUM_SAVE_VERSION;next.towerLimit=limit;next.poolVersion=poolVersion;next.rngState=uint(next.rngState);next.nextId=Number(next.nextId)||0;next.tower=next.tower.map(normalizeTile);if(physicalCount(next)>limit)return null;if(legacySmall)unlockAllNumbers(next);if(limit===7&&poolVersion>=2&&TALLNUM_SETS[next.numberSet].unlocks.some(rule=>!next.unlocked.includes(rule.value)))return null;const poolUnlockAction=limit===7&&poolVersion>=2?Number(value.poolUnlockAction??(legacySmall?value.actions:0)):null;if(poolUnlockAction!==null&&(!Number.isSafeInteger(poolUnlockAction)||poolUnlockAction<0||poolUnlockAction>value.actions))return null;next.poolUnlockAction=poolUnlockAction;next.seed=replayCapable?uint(next.seed):null;next.actionLog=replayCapable?[...next.actionLog]:[];next.rankedEligible=replayCapable;delete next.history;return next;
}

export function tallnumReplay(state){
  if(!state?.rankedEligible||!Number.isSafeInteger(state.seed)||!Array.isArray(state.actionLog))return null;
  const version=towerLimit(state)===7&&Number(state.poolVersion??1)<2?3:TALLNUM_REPLAY_VERSION;
  return {version,numberSet:state.numberSet,towerLimit:towerLimit(state),...(version>=4?{poolUnlockAction:Number(state.poolUnlockAction)||0}:{}),seed:state.seed,actions:[...state.actionLog]};
}

export function applyTallnumReplayAction(state,action){
  let next;
  if(action==="d")next=dropTile(state);
  else if(action==="u"||action==="n")next=rotateTower(state,action==="u"?"up":"down");
  else if(action==="e")next=edgeMerge(state);
  else if(/^g:[0-9]+(?:,[0-9]+)+$/.test(action))next=groupTiles(state,action.slice(2).split(",").map(Number));
  else throw new Error("Tallnum Replay 包含未知操作");
  if(next===state)throw new Error("Tallnum Replay 包含无效操作");
  return next;
}

export function replayTallnum(replay){
  const limit=Number(replay?.towerLimit??10),unlockAt=replay?.version>=4?Number(replay.poolUnlockAction??0):null;
  if(!replay||!TALLNUM_REPLAY_VERSIONS.includes(replay.version)||!TALLNUM_SETS[replay.numberSet]||!TALLNUM_LIMITS.includes(limit)||!Number.isSafeInteger(replay.seed)||replay.seed<0||replay.seed>0xffffffff||!Array.isArray(replay.actions)||replay.actions.length>100000||unlockAt!==null&&(!Number.isSafeInteger(unlockAt)||unlockAt<0||unlockAt>replay.actions.length))throw new Error("Tallnum Replay 无效");
  let state=createTallnumGame({numberSet:replay.numberSet,towerLimit:limit,seed:replay.seed,poolVersion:replay.version>=4&&unlockAt===0?2:1});
  for(let index=0;index<replay.actions.length;index++){state=applyTallnumReplayAction(state,replay.actions[index]);if(replay.version>=4&&index+1===unlockAt){unlockAllNumbers(state);state.poolVersion=2;state.poolUnlockAction=unlockAt}}
  return state;
}
