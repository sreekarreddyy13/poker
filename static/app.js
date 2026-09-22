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

el.waitingForPlayersBanner = document.createElement("p");
el.waitingForPlayersBanner.id = "waiting-for-players-banner";
el.waitingForPlayersBanner.textContent = "Waiting for enough connected players to continue…";
el.waitingForPlayersBanner.hidden = true;
el.showdown.appendChild(el.waitingForPlayersBanner);

// Shows this player's hand category ("Two Pair, Kings and Fours") under
// their hole cards when their hand was shown at showdown.
el.holeCardsCategory = document.createElement("p");
el.holeCardsCategory.id = "hole-cards-category";
el.holeCardsCategory.className = "hand-category";
el.holeCardsCategory.hidden = true;
el.holeCards.insertAdjacentElement("afterend", el.holeCardsCategory);

// Countdown for the current actor's turn; created here so index.html/style.css
// don't need to change.
el.turnTimer = document.createElement("div");
el.turnTimer.id = "turn-timer";
el.turnTimer.hidden = true;
el.stageLabel.insertAdjacentElement("afterend", el.turnTimer);

// Lobby stage: shown while the room is WAITING for the host to start the
// match. Built here for the same reason as the elements above.
el.lobbyCount = document.createElement("p");
el.lobbyCount.id = "lobby-count";
el.lobbyCount.hidden = true;
el.waitingBanner.insertAdjacentElement("afterend", el.lobbyCount);

el.startMatchBtn = document.createElement("button");
el.startMatchBtn.id = "start-match-btn";
el.startMatchBtn.type = "button";
el.startMatchBtn.textContent = "Start Match";
el.startMatchBtn.hidden = true;
el.lobbyCount.insertAdjacentElement("afterend", el.startMatchBtn);

el.waitingForHostBanner = document.createElement("p");
el.waitingForHostBanner.id = "waiting-for-host-banner";
el.waitingForHostBanner.textContent = "Waiting for the host to start the match…";
el.waitingForHostBanner.hidden = true;
el.startMatchBtn.insertAdjacentElement("afterend", el.waitingForHostBanner);

let ws = null;
let myPlayerId = null;
let myName = null;
let roomCode = null;
let turnDeadlineMs = null;
let turnTimerInterval = null;

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

function stopTurnTimer() {
  if (turnTimerInterval !== null) {
    clearInterval(turnTimerInterval);
    turnTimerInterval = null;
  }
  turnDeadlineMs = null;
  el.turnTimer.hidden = true;
}

function updateTurnTimerDisplay() {
  if (turnDeadlineMs === null) return;
  const remaining = Math.max(0, Math.ceil((turnDeadlineMs - Date.now()) / 1000));
  el.turnTimer.textContent = `Time left: ${remaining}s`;
}

// deadlineSeconds is a fixed server clock timestamp (seconds since epoch) at
// which the current turn expires, not a duration. Reading it straight off
// each state message (instead of re-deriving "time left" from a duration
// every time one arrives) keeps the countdown from jumping around: it only
// moves when the server actually starts a new turn and sends a new deadline.
function startTurnTimer(deadlineSeconds) {
  const deadlineMs = deadlineSeconds * 1000;
  el.turnTimer.hidden = false;
  if (deadlineMs === turnDeadlineMs) {
    return;
  }
  turnDeadlineMs = deadlineMs;
  updateTurnTimerDisplay();
  if (turnTimerInterval === null) {
    turnTimerInterval = setInterval(updateTurnTimerDisplay, 250);
  }
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

function extractErrorMessage(body, fallback) {
  const detail = body && body.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((d) => (d && d.msg) || String(d)).join("; ");
  }
  return fallback;
}

async function joinRoom(code, name, playerId) {
  const res = await fetch(`/rooms/${encodeURIComponent(code)}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(playerId ? { name, player_id: playerId } : { name }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessage(body, "Could not join room"));
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
  el.waitingForPlayersBanner.hidden = true;
  el.holeCardsCategory.hidden = true;
  el.lobbyCount.hidden = true;
  el.startMatchBtn.hidden = true;
  el.waitingForHostBanner.hidden = true;
  stopTurnTimer();
  setStatus("");
  showGameError("");
}

function renderState(state) {
  roomCode = state.code;
  el.roomCodeDisplay.textContent = state.code;

  const isLobby = state.room_status === "WAITING";
  el.waitingBanner.hidden = isLobby || !state.waiting;

  if (state.waiting) {
    el.communityCards.innerHTML = "";
    el.potAmount.textContent = "0";
    el.stageLabel.textContent = "";
    el.holeCards.innerHTML = "";
    el.holeCardsCategory.hidden = true;
    el.showdown.hidden = true;
    el.nextHandBtn.hidden = true;
    el.gameOverBanner.hidden = true;
    el.waitingForPlayersBanner.hidden = true;
    stopTurnTimer();
    renderSeats(state, null);
    disableAllActions();

    if (isLobby) {
      const isHost = state.host_id != null && state.host_id === myPlayerId;
      const count = state.players.length;
      el.lobbyCount.hidden = false;
      el.lobbyCount.textContent = `${count} player${count === 1 ? "" : "s"} in the lobby`;
      el.startMatchBtn.hidden = !isHost;
      el.startMatchBtn.disabled = count < 2;
      el.waitingForHostBanner.hidden = isHost;
    } else {
      el.lobbyCount.hidden = true;
      el.startMatchBtn.hidden = true;
      el.waitingForHostBanner.hidden = true;
    }
    return;
  }

  el.lobbyCount.hidden = true;
  el.startMatchBtn.hidden = true;
  el.waitingForHostBanner.hidden = true;

  el.stageLabel.textContent = state.stage;
  el.potAmount.textContent = String(state.pot);
  renderCards(el.communityCards, state.community_cards);

  if (typeof state.turn_deadline === "number") {
    startTurnTimer(state.turn_deadline);
  } else {
    stopTurnTimer();
  }

  const me = state.players.find((p) => p.player_id === myPlayerId);
  renderCards(el.holeCards, me ? me.hole_cards : []);
  el.holeCardsCategory.hidden = !(me && me.hand_category);
  if (me && me.hand_category) el.holeCardsCategory.textContent = me.hand_category;

  renderSeats(state, me);

  if (state.stage === "SHOWDOWN") {
    el.showdown.hidden = !state.payouts;
    if (state.payouts) {
      const nameById = Object.fromEntries(state.players.map((p) => [p.player_id, p.name]));
      const categoryById = Object.fromEntries(
        state.players.filter((p) => p.hand_category).map((p) => [p.player_id, p.hand_category])
      );
      el.payoutsList.innerHTML = Object.entries(state.payouts)
        .filter(([, amount]) => amount > 0)
        .map(([playerId, amount]) => {
          const category = categoryById[playerId];
          const suffix = category ? ` (${escapeHtml(category)})` : "";
          return `<li>${escapeHtml(nameById[playerId] ?? playerId)}: +${amount}${suffix}</li>`;
        })
        .join("");
    }
    if (state.game_over) {
      el.nextHandBtn.hidden = true;
      el.waitingForPlayersBanner.hidden = true;
      el.gameOverBanner.hidden = false;
      el.gameOverBanner.textContent = state.winner_name
        ? `${state.winner_name} wins the game!`
        : "Game over.";
    } else if (state.waiting_for_players) {
      el.gameOverBanner.hidden = true;
      el.nextHandBtn.hidden = true;
      el.waitingForPlayersBanner.hidden = false;
    } else {
      el.gameOverBanner.hidden = true;
      el.waitingForPlayersBanner.hidden = true;
      el.nextHandBtn.hidden = !state.payouts;
    }
    disableAllActions();
    return;
  }

  el.showdown.hidden = true;
  el.nextHandBtn.hidden = true;
  el.gameOverBanner.hidden = true;
  el.waitingForPlayersBanner.hidden = true;
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
    const revealedCards = state.stage === "SHOWDOWN" && p.player_id !== myPlayerId && p.hole_cards;

    const parts = [`<div class="seat-name">${escapeHtml(p.name)}${p.player_id === myPlayerId ? " (you)" : ""}</div>`];
    if (p.player_id === state.host_id) parts.push('<div class="badge">Host</div>');
    if (p.stack !== undefined) parts.push(`<div class="seat-stack">${p.stack} chips</div>`);
    if (p.current_bet) parts.push(`<div class="seat-bet">Bet: ${p.current_bet}</div>`);
    if (p.folded) parts.push('<div class="badge">Folded</div>');
    if (p.all_in) parts.push('<div class="badge">All-in</div>');
    if (p.eliminated) parts.push('<div class="badge">Eliminated</div>');
    if (!p.connected) parts.push('<div class="badge">Disconnected</div>');
    if (revealedCards) {
      parts.push(`<div class="cards">${p.hole_cards.map(cardHtml).join("")}</div>`);
    } else if (showBackCards) {
      parts.push(`<div class="cards">${cardBackHtml()}${cardBackHtml()}</div>`);
    }
    if (p.hand_category) parts.push(`<div class="hand-category">${escapeHtml(p.hand_category)}</div>`);

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

  const callAmount = Math.min(toCall, me.stack || 0);

  el.foldBtn.disabled = false;
  el.checkBtn.disabled = toCall > 0;
  el.callBtn.disabled = toCall <= 0;
  el.callBtn.textContent =
    toCall > 0 ? `Call ${callAmount}${callAmount < toCall ? " (All-In)" : ""}` : "Call";

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
    const session = loadSession();
    const existingPlayerId = session && session.roomCode === code ? session.myPlayerId : undefined;
    const player = await joinRoom(code, name, existingPlayerId);
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
el.startMatchBtn.addEventListener("click", () => sendAction("start_match"));

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
