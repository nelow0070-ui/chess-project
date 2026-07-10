const fs = require('fs');
const vm = require('vm');
const { Chess } = require('../static/chess.js');

function classList() {
  const values = new Set();
  return {
    add: (...names) => names.forEach(name => values.add(name)),
    remove: (...names) => names.forEach(name => values.delete(name)),
    contains: name => values.has(name),
    toggle: (name, force) => {
      if (force === true) values.add(name);
      else if (force === false) values.delete(name);
      else if (values.has(name)) values.delete(name);
      else values.add(name);
      return values.has(name);
    },
  };
}

const elements = new Map();
const handlers = new Map();
const squares = new Map();
const fetchedUrls = [];
const storage = {
  chessAccounts: JSON.stringify([
    { provider: 'chesscom', username: 'Nelo_w' },
    { provider: 'lichess', username: 'hidden_user', hidden: true },
  ]),
};

for (const file of 'abcdefgh') {
  for (let rank = 1; rank <= 8; rank += 1) {
    const square = `${file}${rank}`;
    squares.set(square, { dataset: { square }, classList: classList() });
  }
}

function element(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id,
      classList: classList(),
      style: {},
      value: '',
      textContent: '',
      innerHTML: '',
      addEventListener: (name, handler) => handlers.set(`${id}:${name}`, handler),
      appendChild: () => {},
      getBoundingClientRect: () => ({ width: 520 }),
      clientHeight: 520,
      clientWidth: 620,
      offsetWidth: id === 'evalFill' ? 32 : 0,
    });
  }
  return elements.get(id);
}

const context = {
  Chess,
  URLSearchParams,
  console,
  localStorage: {
    getItem: key => storage[key] || null,
    setItem: (key, value) => {
      storage[key] = value;
    },
  },
  document: {
    getElementById: element,
    addEventListener: () => {},
    querySelector: selector => {
      if (selector === '.eval-bar') return element('evalFill');
      if (selector === '.board-stage') return element('boardStage');
      const match = selector.match(/\.square-([a-h][1-8])/);
      return match ? squares.get(match[1]) : null;
    },
    querySelectorAll: selector => selector.includes('square-55d63')
      ? [...squares.values()]
      : [],
    createElement: () => element(`created-${elements.size}`),
  },
  fetch: async url => {
    fetchedUrls.push(url);
    return {
      ok: true,
      json: async () => url.startsWith('/eval')
        ? { type: 'cp', cp: 0 }
        : [],
    };
  },
  Chessboard: () => ({
    position: () => {},
    start: () => {},
    orientation: () => {},
    resize: () => {},
  }),
  window: {
    addEventListener: () => {},
    clearTimeout,
    setTimeout,
    requestAnimationFrame: callback => callback(),
  },
};

vm.createContext(context);
[
  'static/board/state.js',
  'static/board/core.js',
  'static/board/forms.js',
  'static/board/database.js',
  'static/board/main.js',
].forEach(file => {
  vm.runInContext(fs.readFileSync(file, 'utf8'), context, { filename: file });
});

const click = handlers.get('board:click');
const eventFor = square => ({
  target: {
    closest: selector => selector === '.square-55d63' ? squares.get(square) : null,
  },
});

if (!fetchedUrls.some(url => url.includes('/moves?') && url.includes('perspective=player'))) {
  throw new Error('white turn did not request player moves for white player');
}
if (fetchedUrls.some(url => url.includes('/moves?') && url.includes('hidden_user'))) {
  throw new Error('hidden account was included in move lookup');
}
vm.runInContext('renderSettingsInfo()', context);
if (elements.has('settingsUserStatus')) {
  throw new Error('user tab still renders account count status');
}

const frequencyOrder = vm.runInContext(`(() => {
  moveSort = 'frequency';
  return sortMoves([
    { san: 'Nf3', type: 'best', count: 2, winrate: 60 },
    { san: 'e4', type: 'mistake', count: 5, winrate: 40 },
  ]).map(move => move.san).join(',');
})()`, context);
if (frequencyOrder !== 'e4,Nf3') {
  throw new Error('frequency sorting did not prefer higher count');
}

const qualityOrder = vm.runInContext(`(() => {
  moveSort = 'quality';
  return sortMoves([
    { san: 'e4', type: 'mistake', count: 5, winrate: 40 },
    { san: 'Nf3', type: 'best', count: 2, winrate: 60 },
  ]).map(move => move.san).join(',');
})()`, context);
if (qualityOrder !== 'Nf3,e4') {
  throw new Error('quality sorting did not prefer better evaluation type');
}

click(eventFor('e2'));
if (!squares.get('e3').classList.contains('legal-square')) {
  throw new Error('e2 selection did not highlight e3');
}
if (!squares.get('e4').classList.contains('legal-square')) {
  throw new Error('e2 selection did not highlight e4');
}

click(eventFor('d2'));
if (!squares.get('d2').classList.contains('selected-square')) {
  throw new Error('clicking another friendly piece did not switch selection');
}
if (!squares.get('d4').classList.contains('legal-square')) {
  throw new Error('newly selected friendly piece did not show its legal moves');
}

click(eventFor('e2'));
click(eventFor('e4'));
if (vm.runInContext('game.turn()', context) !== 'b') {
  throw new Error('e2-e4 did not pass the turn to black');
}
if (!fetchedUrls.some(url => url.includes('/moves?') && url.includes('perspective=opponent'))) {
  throw new Error('black turn did not request opponent moves for white player');
}

click(eventFor('e7'));
if (!squares.get('e6').classList.contains('legal-square')) {
  throw new Error('black could not select e7 after white moved');
}
if (!squares.get('e5').classList.contains('legal-square')) {
  throw new Error('e7 selection did not highlight e5');
}

click(eventFor('e5'));
if (vm.runInContext('game.turn()', context) !== 'w') {
  throw new Error('e7-e5 did not pass the turn back to white');
}

click(eventFor('g1'));
click(eventFor('f3'));
click(eventFor('b8'));
click(eventFor('c6'));
click(eventFor('f3'));
click(eventFor('e5'));
const capturedPosition = vm.runInContext('game.get("e5")', context);
if (!capturedPosition || capturedPosition.type !== 'n' || capturedPosition.color !== 'w') {
  throw new Error('clicking an opponent piece did not complete a legal capture');
}

const lineLengthBeforeHistoryJump = vm.runInContext('moveLine.length', context);
vm.runInContext('jumpToHistoryPly(1)', context);
if (vm.runInContext('moveLine.length', context) !== lineLengthBeforeHistoryJump) {
  throw new Error('jumping to an earlier move truncated the saved move line');
}
click(eventFor('g1'));
click(eventFor('f3'));
if (vm.runInContext('moveLine.length', context) !== lineLengthBeforeHistoryJump) {
  throw new Error('replaying an existing continuation truncated later moves');
}
if (vm.runInContext('currentPly', context) !== 2) {
  throw new Error('replaying an existing continuation did not advance the current ply');
}
vm.runInContext('jumpToHistoryPly(moveLine.length - 1)', context);
if (vm.runInContext('moveLine.length', context) !== lineLengthBeforeHistoryJump) {
  throw new Error('jumping to a later move changed the saved move line');
}

handlers.get('myColorBlack:click')();
if (storage.myChessColor !== 'black') {
  throw new Error('black player color was not persisted');
}
if (element('moveListTitle').textContent !== '내가 둔 수') {
  throw new Error('black turn should show player moves for black player');
}

console.log('board click movement regression test passed');
