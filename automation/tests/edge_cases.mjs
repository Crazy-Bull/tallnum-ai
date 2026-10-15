import {createTallnumGame, edgeMerge} from '../vendor/tallnum.mjs';

for (const [values, expected] of [
  [[10, 15, 24], [2, 24]],
  [[240, 244, 40], [8]],
]) {
  const state = createTallnumGame({towerLimit: 7, numberSet: 'standard', seed: 4});
  state.tower = values.map((value, index) => ({
    id: `test-${index}`, value, physicalCount: 1, kind: 'tile',
  }));
  const actual = edgeMerge(state).tower.map(tile => tile.value);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${values}: expected ${expected}, got ${actual}`);
  }
}
console.log('Pinned website EDGE examples: passed');
