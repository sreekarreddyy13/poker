// Plain JS frontend for the poker app. No build step, no dependencies.

const RANK_DISPLAY = {
  TWO: "2", THREE: "3", FOUR: "4", FIVE: "5", SIX: "6", SEVEN: "7",
  EIGHT: "8", NINE: "9", TEN: "10", JACK: "J", QUEEN: "Q", KING: "K", ACE: "A",
};
const SUIT_DISPLAY = { CLUBS: "♣", DIAMONDS: "♦", HEARTS: "♥", SPADES: "♠" };
const RED_SUITS = new Set(["DIAMONDS", "HEARTS"]);
const STORAGE_KEY = "poker-app-session";

const el = {
  status: document.getElementById("connection-status"),
  lobby: document.getElementById("lobby"),
  lobbyMessage: document.getElementById("lobby-message"),
  createRoomBtn: document.getElementById("create-room-btn"),
  joinForm: document.getElementById("join-form"),
  joinCode: document.getElementById("join-code"),
  joinName: document.getElementById("join-name"),
  table: document.getElementById("table"),
  roomCodeDisplay: document.getElementById("room-code-display"),
  leaveBtn: document.getElementById("leave-btn"),
  waitingBanner: document.getElementById("waiting-banner"),
  stageLabel: document.getElementById("stage-label"),
  communityCards: document.getElementById("community-cards"),
  potAmount: document.getElementById("pot-amount"),
  seats: document.getElementById("seats"),
  showdown: document.getElementById("showdown"),
  payoutsList: document.getElementById("payouts-list"),
  holeCards: document.getElementById("hole-cards"),
  foldBtn: document.getElementById("fold-btn"),
  checkBtn: document.getElementById("check-btn"),
  callBtn: document.getElementById("call-btn"),
  raiseAmount: document.getElementById("raise-amount"),
  raiseBtn: document.getElementById("raise-btn"),
  maxRaiseBtn: document.getElementById("max-raise-btn"),
  gameError: document.getElementById("game-error"),
};

// Created here (not in index.html) so the next-hand flow only touches app.js.
el.gameOverBanner = document.createElement("p");
el.gameOverBanner.id = "game-over-banner";
el.gameOverBanner.hidden = true;
el.showdown.appendChild(el.gameOverBanner);

el.nextHandBtn = document.createElement("button");
el.nextHandBtn.id = "next-hand-btn";
el.nextHandBtn.type = "button";
el.nextHandBtn.textContent = "Next Hand";
el.nextHandBtn.hidden = true;
el.showdown.appendChild(el.nextHandBtn);

let ws = null;
let myPlayerId = null;
let myName = null;
let roomCode = null;

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

function cardHtml(card) {
  const red = RED_SUITS.has(card.suit);
  return `<div class="card ${red ? "red" : "black"}">` +
    `<span class="rank">${RANK_DISPLAY[card.rank] ?? "?"}</span>` +
    `<span class="suit">${SUIT_DISPLAY[card.suit] ?? "?"}</span></div>`;
}

function cardBackHtml() {
  return '<div class="card back"></div>';
}

function renderCards(container, cards) {
  if (!cards || cards.length === 0) {
    container.innerHTML = '<span class="placeholder">&mdash;</span>';
    return;
  }
  container.innerHTML = cards.map(cardHtml).join("");
}

function setStatus(text) {
  el.status.textContent = text;
}

function showLobbyMessage(text) {
  el.lobbyMessage.textContent = text ?? "";
}

function showGameError(text) {
  el.gameError.textContent = text ?? "";
}

function saveSession() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ roomCode, myPlayerId, myName }));
}

function clearSession() {
  localStorage.removeItem(STORAGE_KEY);
}

function loadSession() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

async function createRoom() {
  showLobbyMessage("");
  try {
    const res = await fetch("/rooms", { method: "POST" });
    if (!res.ok) throw new Error("Could not create room");
    const data = await res.json();
    el.joinCode.value = data.code;
    showLobbyMessage(`Room ${data.code} created. Enter your name and join.`);
  } catch (err) {
    showLobbyMessage(err.message);
  }
}

async function joinRoom(code, name) {
  const res = await fetch(`/rooms/${encodeURIComponent(code)}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Could not join room");
  }
  return res.json();
}

function connect(code, playerId) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/${encodeURIComponent(code)}?player_id=${encodeURIComponent(playerId)}`);

  ws.onopen = () => setStatus("Connected");
  ws.onclose = () => setStatus("Disconnected");
  ws.onerror = () => setStatus("Connection error");
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "state") {
      showGameError("");
      renderState(msg);
    } else if (msg.type === "error") {
      showGameError(msg.message);
    }
  };
}

function enterTable() {
  el.lobby.hidden = true;
  el.table.hidden = false;
  el.roomCodeDisplay.textContent = roomCode;
}

function leaveTable() {
  if (ws) {
    ws.close();
    ws = null;
  }
  clearSession();
  myPlayerId = null;
  myName = null;
  roomCode = null;
  el.table.hidden = true;
  el.lobby.hidden = false;
  el.nextHandBtn.hidden = true;
  el.gameOverBanner.hidden = true;
  setStatus("");
  showGameError("");
}

function renderState(state) {
  roomCode = state.code;
  el.roomCodeDisplay.textContent = state.code;

  el.waitingBanner.hidden = !state.waiting;

  if (state.waiting) {
    el.communityCards.innerHTML = "";
    el.potAmount.textContent = "0";
    el.stageLabel.textContent = "";
    el.holeCards.innerHTML = "";
    el.showdown.hidden = true;
    el.nextHandBtn.hidden = true;
    el.gameOverBanner.hidden = true;
    renderSeats(state, null);
    disableAllActions();
    return;
  }

  el.stageLabel.textContent = state.stage;
  el.potAmount.textContent = String(state.pot);
  renderCards(el.communityCards, state.community_cards);

  const me = state.players.find((p) => p.player_id === myPlayerId);
  renderCards(el.holeCards, me ? me.hole_cards : []);

  renderSeats(state, me);

  if (state.stage === "SHOWDOWN") {
    el.showdown.hidden = !state.payouts;
    if (state.payouts) {
      const nameById = Object.fromEntries(state.players.map((p) => [p.player_id, p.name]));
      el.payoutsList.innerHTML = Object.entries(state.payouts)
        .filter(([, amount]) => amount > 0)
        .map(([playerId, amount]) => `<li>${escapeHtml(nameById[playerId] ?? playerId)}: +${amount}</li>`)
        .join("");
    }
    if (state.game_over) {
      el.nextHandBtn.hidden = true;
      el.gameOverBanner.hidden = false;
      el.gameOverBanner.textContent = state.winner_name
        ? `${state.winner_name} wins the game!`
        : "Game over.";
    } else {
      el.gameOverBanner.hidden = true;
      el.nextHandBtn.hidden = !state.payouts;
    }
    disableAllActions();
    return;
  }

  el.showdown.hidden = true;
  el.nextHandBtn.hidden = true;
  el.gameOverBanner.hidden = true;
  updateActions(state, me);
}

function renderSeats(state, me) {
  el.seats.innerHTML = "";
  for (const p of state.players) {
    const seat = document.createElement("div");
    seat.className = "seat";
    if (!state.waiting && p.player_id === state.current_actor) seat.classList.add("active");
    if (p.player_id === myPlayerId) seat.classList.add("me");
    if (p.folded) seat.classList.add("folded");
    if (!p.connected) seat.classList.add("disconnected");

    const showBackCards = !state.waiting && p.player_id !== myPlayerId && !p.folded && p.stack !== undefined;

    const parts = [`<div class="seat-name">${escapeHtml(p.name)}${p.player_id === myPlayerId ? " (you)" : ""}</div>`];
    if (p.stack !== undefined) parts.push(`<div class="seat-stack">${p.stack} chips</div>`);
    if (p.current_bet) parts.push(`<div class="seat-bet">Bet: ${p.current_bet}</div>`);
    if (p.folded) parts.push('<div class="badge">Folded</div>');
    if (p.all_in) parts.push('<div class="badge">All-in</div>');
    if (p.eliminated) parts.push('<div class="badge">Eliminated</div>');
    if (!p.connected) parts.push('<div class="badge">Disconnected</div>');
    if (showBackCards) parts.push(`<div class="cards">${cardBackHtml()}${cardBackHtml()}</div>`);

    seat.innerHTML = parts.join("");
    el.seats.appendChild(seat);
  }
}

function disableAllActions() {
  el.foldBtn.disabled = true;
  el.checkBtn.disabled = true;
  el.callBtn.disabled = true;
  el.raiseBtn.disabled = true;
  el.maxRaiseBtn.disabled = true;
  el.callBtn.textContent = "Call";
}

function updateActions(state, me) {
  const isMyTurn = Boolean(me) && state.current_actor === myPlayerId;
  if (!isMyTurn || !me) {
    disableAllActions();
    return;
  }

  const toCall = state.current_bet - (me.current_bet || 0);
  const maxRaiseTo = (me.current_bet || 0) + (me.stack || 0);
  const minRaiseTo = state.current_bet + state.min_raise;

  el.foldBtn.disabled = false;
  el.checkBtn.disabled = toCall > 0;
  el.callBtn.disabled = toCall <= 0;
  el.callBtn.textContent = toCall > 0 ? `Call ${toCall}` : "Call";

  const canRaise = maxRaiseTo >= minRaiseTo && (me.stack || 0) > 0;
  el.raiseBtn.disabled = !canRaise;
  el.maxRaiseBtn.disabled = !canRaise;
  el.raiseAmount.disabled = !canRaise;
  if (canRaise) {
    el.raiseAmount.min = String(minRaiseTo);
    el.raiseAmount.max = String(maxRaiseTo);
    const current = Number(el.raiseAmount.value);
    if (!current || current < minRaiseTo || current > maxRaiseTo) {
      el.raiseAmount.value = String(minRaiseTo);
    }
  }
}

function sendAction(action, amount) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const payload = { action };
  if (amount !== undefined) payload.amount = amount;
  ws.send(JSON.stringify(payload));
}

el.createRoomBtn.addEventListener("click", createRoom);

el.joinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const code = el.joinCode.value.trim().toUpperCase();
  const name = el.joinName.value.trim();
  if (!code || !name) return;

  showLobbyMessage("");
  try {
    const player = await joinRoom(code, name);
    myPlayerId = player.player_id;
    myName = player.name;
    roomCode = player.code;
    saveSession();
    enterTable();
    connect(roomCode, myPlayerId);
  } catch (err) {
    showLobbyMessage(err.message);
  }
});

el.leaveBtn.addEventListener("click", leaveTable);

el.foldBtn.addEventListener("click", () => sendAction("fold"));
el.checkBtn.addEventListener("click", () => sendAction("check"));
el.callBtn.addEventListener("click", () => sendAction("call"));
el.raiseBtn.addEventListener("click", () => {
  const amount = parseInt(el.raiseAmount.value, 10);
  if (Number.isNaN(amount)) return;
  sendAction("raise", amount);
});
el.maxRaiseBtn.addEventListener("click", () => {
  el.raiseAmount.value = el.raiseAmount.max || el.raiseAmount.value;
});
el.nextHandBtn.addEventListener("click", () => sendAction("next_hand"));

(function init() {
  const session = loadSession();
  if (session && session.roomCode && session.myPlayerId) {
    myPlayerId = session.myPlayerId;
    myName = session.myName;
    roomCode = session.roomCode;
    enterTable();
    connect(roomCode, myPlayerId);
  }
})();
