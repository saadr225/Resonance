const state = {
  token: localStorage.getItem("resonance.token") || "",
  session: null,
  peer: null,
  stream: null,
  socket: null,
  signalSocket: null,
  pendingCandidates: [],
  transcriptCount: 0,
};

const $ = (id) => document.getElementById(id);

function endpoints() {
  return {
    sessionApi: $("sessionApi").value.replace(/\/$/, ""),
    mediaApi: $("mediaApi").value.replace(/\/$/, ""),
    wsApi: $("wsApi").value.replace(/\/$/, ""),
  };
}

function setStatus(message) {
  $("status").textContent = message;
}

function mediaSignalUrl() {
  const { mediaApi } = endpoints();
  const url = new URL(mediaApi);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const basePath = url.pathname.replace(/\/$/, "");
  url.pathname = `${basePath}/ws/${state.session.id}`;
  url.searchParams.set("token", state.token);
  return url.toString();
}

async function fetchIceServers() {
  const { mediaApi } = endpoints();
  const response = await fetch(`${mediaApi}/ice`);
  if (!response.ok) return [];
  const payload = await response.json();
  return payload.iceServers || [];
}

function sendSignal(payload) {
  if (!state.signalSocket || state.signalSocket.readyState !== WebSocket.OPEN) return;
  state.signalSocket.send(JSON.stringify(payload));
}

function queueOrAddCandidate(candidate) {
  if (!state.peer || !state.peer.remoteDescription) {
    state.pendingCandidates.push(candidate);
    return;
  }
  state.peer.addIceCandidate(candidate).catch(() => undefined);
}

async function flushPendingCandidates() {
  if (!state.peer || !state.peer.remoteDescription) return;
  const pending = [...state.pendingCandidates];
  state.pendingCandidates = [];
  await Promise.all(pending.map((candidate) => state.peer.addIceCandidate(candidate)));
}

async function connectSignalSocket() {
  if (state.signalSocket) state.signalSocket.close();
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(mediaSignalUrl());
    state.signalSocket = socket;
    socket.onopen = () => resolve(socket);
    socket.onerror = () => reject(new Error("Media signaling error"));
    socket.onclose = () => setStatus("Media signaling disconnected");
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (!state.peer) return;

      if (payload.type === "offer") {
        state.peer
          .setRemoteDescription({ type: "offer", sdp: payload.sdp })
          .then(() => state.peer.createAnswer())
          .then((answer) => state.peer.setLocalDescription(answer))
          .then(() => {
            sendSignal({ type: "answer", sdp: state.peer.localDescription.sdp });
          })
          .then(() => flushPendingCandidates())
          .catch(() => undefined);
        return;
      }

      if (payload.type === "answer") {
        state.peer
          .setRemoteDescription({ type: "answer", sdp: payload.sdp })
          .then(() => flushPendingCandidates())
          .then(() => setStatus("Audio connected"))
          .catch(() => undefined);
        return;
      }

      if (payload.type === "candidate") {
        if (!payload.candidate) {
          queueOrAddCandidate(null);
          return;
        }
        queueOrAddCandidate(
          new RTCIceCandidate({
            candidate: payload.candidate,
            sdpMid: payload.sdpMid,
            sdpMLineIndex: payload.sdpMLineIndex,
          }),
        );
      }
    };
  });
}

async function api(path, options = {}) {
  const { sessionApi } = endpoints();
  const headers = {
    "content-type": "application/json",
    ...(options.headers || {}),
  };
  if (state.token) {
    headers.authorization = `Bearer ${state.token}`;
  }
  const response = await fetch(`${sessionApi}${path}`, {
    ...options,
    headers,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

async function authenticate(mode) {
  const payload = {
    email: $("email").value,
    password: $("password").value,
  };
  const result = await api(`/auth/${mode}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.token = result.token;
  localStorage.setItem("resonance.token", state.token);
  setStatus(`Signed in as ${result.user.email}`);
}

function setSession(session) {
  state.session = session;
  $("sessionId").textContent = session.id;
  $("activeInvite").textContent = session.invite_token;
  $("inviteToken").value = session.invite_token;
}

async function createRoom() {
  const session = await api("/sessions", {
    method: "POST",
    body: JSON.stringify({ title: $("roomTitle").value || "Untitled Resonance Session" }),
  });
  setSession(session);
  connectSocket();
  setStatus("Room ready");
}

async function joinRoom() {
  const session = await api("/sessions/join", {
    method: "POST",
    body: JSON.stringify({
      invite_token: $("inviteToken").value,
      display_name: $("displayName").value || "Guest",
    }),
  });
  setSession(session);
  connectSocket();
  setStatus("Joined room");
}

function connectSocket() {
  if (!state.session || !state.token) return;
  if (state.socket) state.socket.close();

  const { wsApi } = endpoints();
  state.socket = new WebSocket(`${wsApi}/ws/${state.session.id}?token=${encodeURIComponent(state.token)}`);
  state.socket.onopen = () => setStatus("Insights connected");
  state.socket.onclose = () => setStatus("Insights disconnected");
  state.socket.onerror = () => setStatus("WebSocket error");
  state.socket.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "transcript") {
      addTranscript(payload);
    } else {
      updateInsight(payload);
    }
  };
}

function updateInsight(payload) {
  $("summary").textContent = payload.summary || "Waiting for insight updates.";
  const sentiment = payload.sentiment || "neutral";
  $("sentiment").textContent = sentiment;
  $("sentiment").className = `sentiment ${sentiment}`;

  const actions = Array.isArray(payload.action_items) ? payload.action_items : [];
  $("actionCount").textContent = String(actions.length);
  $("actions").replaceChildren(
    ...actions.map((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      return li;
    }),
  );
}

function addTranscript(payload) {
  if (!payload.text) return;
  state.transcriptCount += 1;
  $("transcriptCount").textContent = String(state.transcriptCount);

  const li = document.createElement("li");
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = payload.speaker_id || "unknown";
  li.append(speaker, document.createTextNode(payload.text));
  $("transcript").append(li);
  li.scrollIntoView({ block: "nearest" });
}

async function startCall() {
  if (!state.session || !state.token) {
    setStatus("Create or join a room first");
    return;
  }

  const iceServers = await fetchIceServers();
  await connectSignalSocket();
  state.pendingCandidates = [];
  state.stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  state.peer = new RTCPeerConnection({ iceServers });
  state.peer.onconnectionstatechange = () => setStatus(`WebRTC ${state.peer.connectionState}`);
  state.peer.onicecandidate = (event) => {
    const candidate = event.candidate;
    if (!candidate) {
      sendSignal({ type: "candidate", candidate: null });
      return;
    }
    sendSignal({
      type: "candidate",
      candidate: candidate.candidate,
      sdpMid: candidate.sdpMid,
      sdpMLineIndex: candidate.sdpMLineIndex,
    });
  };
  state.peer.ontrack = (event) => {
    const audio = new Audio();
    audio.srcObject = event.streams[0];
    audio.autoplay = true;
    audio.play().catch(() => undefined);
  };
  for (const track of state.stream.getTracks()) {
    state.peer.addTrack(track, state.stream);
  }
  const offer = await state.peer.createOffer();
  await state.peer.setLocalDescription(offer);
  sendSignal({ type: "offer", sdp: state.peer.localDescription.sdp });
  setStatus("Audio connecting");
}

function stopCall() {
  if (state.peer) {
    state.peer.close();
    state.peer = null;
  }
  if (state.stream) {
    for (const track of state.stream.getTracks()) track.stop();
    state.stream = null;
  }
  if (state.signalSocket) {
    state.signalSocket.close();
    state.signalSocket = null;
  }
  state.pendingCandidates = [];
  setStatus("Audio stopped");
}

$("authForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const mode = event.submitter.dataset.auth;
  try {
    await authenticate(mode);
  } catch (error) {
    setStatus(error.message);
  }
});

$("createRoom").addEventListener("click", () => createRoom().catch((error) => setStatus(error.message)));
$("joinRoom").addEventListener("click", () => joinRoom().catch((error) => setStatus(error.message)));
$("startCall").addEventListener("click", () => startCall().catch((error) => setStatus(error.message)));
$("stopCall").addEventListener("click", stopCall);

if (state.token) {
  setStatus("Token loaded");
}
