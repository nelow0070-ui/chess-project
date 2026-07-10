const accounts = JSON.parse(localStorage.getItem('chessAccounts') || '[]');
const game = new Chess();
const defaultStartFen = game.fen();
let lineStartFen = game.fen();
let moveLine = [];
let currentPly = -1;
let board = null;
let myColor = localStorage.getItem('myChessColor') || 'white';
let orientation = myColor;
let selectedSquare = null;
let requestId = 0;
let moveSort = localStorage.getItem('moveSort') || 'frequency';
let detailMode = false;
let analysisPollTimer = null;

const els = {
  status: document.getElementById('positionStatus'),
  fenPopover: document.getElementById('fenPopover'),
  fenSearchInput: document.getElementById('fenSearchInput'),
  fenMessage: document.getElementById('fenMessage'),
  openFenInput: document.getElementById('openFenInput'),
  closeFenInput: document.getElementById('closeFenInput'),
  applyFenSearch: document.getElementById('applyFenSearch'),
  copyFen: document.getElementById('copyFen'),
  pgnPopover: document.getElementById('pgnPopover'),
  pgnPasteInput: document.getElementById('pgnPasteInput'),
  pgnMessage: document.getElementById('pgnMessage'),
  openPgnInput: document.getElementById('openPgnInput'),
  closePgnInput: document.getElementById('closePgnInput'),
  applyPgnPaste: document.getElementById('applyPgnPaste'),
  copyPgn: document.getElementById('copyPgn'),
  evalFill: document.getElementById('evalFill'),
  evalLabel: document.getElementById('evalLabel'),
  moveList: document.getElementById('moveList'),
  resultCount: document.getElementById('resultCount'),
  moveSortFrequency: document.getElementById('moveSortFrequency'),
  moveSortQuality: document.getElementById('moveSortQuality'),
  moveListTitle: document.getElementById('moveListTitle'),
  databaseTab: document.getElementById('databaseTab'),
  pgnDisplay: document.getElementById('pgnDisplay'),
  myColorWhite: document.getElementById('myColorWhite'),
  myColorBlack: document.getElementById('myColorBlack'),
  viewWhite: document.getElementById('viewWhite'),
  viewBlack: document.getElementById('viewBlack'),
  analysisManager: document.getElementById('analysisManager'),
  settingsAnalysisPanel: document.getElementById('settingsAnalysisPanel'),
  settingsBoardPanel: document.getElementById('settingsBoardPanel'),
  settingsUserPanel: document.getElementById('settingsUserPanel'),
  managerAccountList: document.getElementById('managerAccountList'),
  settingsAccountList: document.getElementById('settingsAccountList'),
  settingsDepth: document.getElementById('settingsDepth'),
  settingsViewWhite: document.getElementById('settingsViewWhite'),
  settingsViewBlack: document.getElementById('settingsViewBlack'),
  settingsMyColorWhite: document.getElementById('settingsMyColorWhite'),
  settingsMyColorBlack: document.getElementById('settingsMyColorBlack'),
  addGamesPlaceholder: document.getElementById('addGamesPlaceholder'),
  toggleDateFilter: document.getElementById('toggleDateFilter'),
  dateFilterControls: document.getElementById('dateFilterControls'),
  managerDateFrom: document.getElementById('managerDateFrom'),
  managerDateTo: document.getElementById('managerDateTo'),
  managerSummary: document.getElementById('managerSummary'),
  managerMessage: document.getElementById('managerMessage'),
  resetConfirmation: document.getElementById('resetConfirmation'),
  resetDatabase: document.getElementById('resetDatabase'),
  previousMove: document.getElementById('previousMove'),
  nextMove: document.getElementById('nextMove'),
  openTutorial: document.getElementById('openTutorial'),
  tutorialModal: document.getElementById('tutorialModal'),
  closeTutorial: document.getElementById('closeTutorial'),
  timeClassFilters: document.getElementById('timeClassFilters'),
};
