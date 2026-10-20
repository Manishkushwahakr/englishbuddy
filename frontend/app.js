
const API_BASE = (window.IMPROBUDDY_API_BASE || "").replace(/\/+$/, "");
const TOKEN_KEY = "improbuddy_access_token";

// DOM elements
const notice = document.getElementById("notice");
const userEmail = document.getElementById("user-email");
const userArea = document.getElementById("user-area");

const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");

// Show status messages
function showNotice(message, type = "") {
  notice.textContent = message;
  notice.className = "show";

  if (type) {
    notice.classList.add(type);
  }
}

// Hide status messages
function hideNotice() {
  notice.textContent = "";
  notice.className = "";
}

// Read the saved JWT token
function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

// Make authenticated API requests
async function apiRequest(path, options = {}) {
  if (!API_BASE) {
    throw new Error(
      "The backend URL is not configured. Set IMPROBUDDY_API_BASE in frontend/config.js."
    );
  }

  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  const token = getToken();

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });
  } catch (error) {
    if (error?.name !== "TypeError") {
      throw error;
    }

    throw new Error(
      `Could not reach the backend at ${API_BASE}. The browser cannot distinguish a network failure from CORS blocking this origin (${window.location.origin}). Check the Render service and its FRONTEND_ORIGINS setting.`
    );
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    if (
      token &&
      (response.status === 401 || response.status === 403) &&
      path !== "/auth/login" &&
      path !== "/auth/register"
    ) {
      localStorage.removeItem(TOKEN_KEY);
      userEmail.textContent = "";
      userArea.classList.add("hidden");
      const error = new Error(
        "Your session has expired or is invalid. Please log in again."
      );
      error.sessionExpired = true;
      throw error;
    }

    const detail = data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : `Request failed (${response.status})`;

    throw new Error(message);
  }

  return data;
}

// Switch between login, dashboard and other screens
function showView(viewId) {
  const target = document.getElementById(viewId);

  if (!target || !target.classList.contains("view")) {
    throw new Error(`Cannot display unknown view: ${viewId}`);
  }

  if (
    viewId !== "matching-view" &&
    document.getElementById("matching-view").classList.contains("active")
  ) {
    clearTimeout(matchingPollTimer);
    matchingPollTimer = null;
    matchingFlowId += 1;
  }

  if (
    viewId !== "call-view" &&
    document.getElementById("call-view").classList.contains("active")
  ) {
    cleanupCall();
  }

  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view === target);
  });
}

// Display the dashboard
async function loadDashboard() {
  const user = await apiRequest("/auth/me");
  userEmail.textContent = user.email;
  userArea.classList.remove("hidden");
  showView("dashboard-view");
  hideNotice();

  try {
    await apiRequest("/profile");
  } catch (error) {
    if (error.sessionExpired) {
      throw error;
    }
    console.warn("Could not load profile:", error.message);
  }
}

// Login
loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideNotice();

  const button = loginForm.querySelector('button[type="submit"]');
  if (button) button.disabled = true;

  try {
    const email = loginForm.elements.namedItem("email").value.trim();
    const password = loginForm.elements.namedItem("password").value;

    const data = await apiRequest("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });

    localStorage.setItem(TOKEN_KEY, data.access_token);

    await loadDashboard();
    loginForm.reset();
  } catch (error) {
    localStorage.removeItem(TOKEN_KEY);
    userEmail.textContent = "";
    userArea.classList.add("hidden");
    showView("auth-view");
    showNotice(error.message || "Login failed.", "error");
  } finally {
    if (button) button.disabled = false;
  }
});

// Register
registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideNotice();

  const button = registerForm.querySelector('button[type="submit"]');
  if (button) button.disabled = true;

  try {
    const name = registerForm.elements.namedItem("name").value.trim();
    const email = registerForm.elements.namedItem("email").value.trim();
    const password = registerForm.elements.namedItem("password").value;

    await apiRequest("/auth/register", {
      method: "POST",
      body: JSON.stringify({ name, email, password }),
    });

    // Automatically log in after successful registration
    const data = await apiRequest("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });

    localStorage.setItem(TOKEN_KEY, data.access_token);

    await loadDashboard();
    registerForm.reset();
  } catch (error) {
    showNotice(error.message || "Registration failed.", "error");
  } finally {
    if (button) button.disabled = false;
  }
});

// Login/register tabs
document.querySelectorAll("[data-auth-tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    const selectedTab = tab.dataset.authTab;

    document.querySelectorAll("[data-auth-tab]").forEach((item) => {
      item.classList.toggle("active", item === tab);
    });

    loginForm.classList.toggle("hidden", selectedTab !== "login");
    registerForm.classList.toggle("hidden", selectedTab !== "register");

    hideNotice();
  });
});

// Logout
const logoutButton = document.getElementById("logout-btn");

if (logoutButton) {
  logoutButton.addEventListener("click", async () => {
    let logoutMessage = "You have logged out successfully.";

    if (document.getElementById("matching-view").classList.contains("active")) {
      matchingFlowId += 1;
      stopMatchingPolling();
      try {
        await apiRequest("/matching/cancel", { method: "POST" });
      } catch (error) {
        console.warn("Could not leave the matching queue before logout:", error.message);
        logoutMessage = "You logged out, but your matching search may still be active.";
      }
    }

    localStorage.removeItem(TOKEN_KEY);
    userEmail.textContent = "";
    userArea.classList.add("hidden");
    showView("auth-view");
    showNotice(logoutMessage, logoutMessage.includes("may still") ? "error" : "success");
  });
}

const matchingTitle = document.getElementById("matching-title");
const matchingMessage = document.getElementById("matching-message");
const cancelMatchingButton = document.getElementById("cancel-matching-btn");
const matchingLoader = document.querySelector("#matching-view .loader");
const callStatus = document.getElementById("call-status");
const startCallButton = document.getElementById("start-call-btn");
const endCallButton = document.getElementById("end-call-btn");
const muteButton = document.getElementById("mute-btn");
const remoteAudio = document.getElementById("remote-audio");
const MATCHING_POLL_INTERVAL = 2000;
let matchingPollTimer = null;
let matchingFlowId = 0;
let activeMatch = null;
let callSession = null;
let callSocket = null;
let peerConnection = null;
let localAudioStream = null;

function stopMatchingPolling() {
  if (matchingPollTimer !== null) {
    clearTimeout(matchingPollTimer);
    matchingPollTimer = null;
  }
}

function showMatchedPartner(match) {
  stopMatchingPolling();
  matchingLoader.classList.add("hidden");
  activeMatch = match;
  matchingTitle.textContent = "Partner found!";
  const partnerLabel = match.partner_name || match.partner_email || "another learner";
  matchingMessage.textContent =
    `Matched with ${partnerLabel}` +
    `${match.partner_email ? ` (${match.partner_email})` : ""}.`;
  cancelMatchingButton.classList.add("hidden");
  callStatus.textContent = `Partner found: ${partnerLabel}. Connecting to the audio call...`;
  showView("call-view");
  startCall(match);
}

function sendCallSignal(message, session = callSession) {
  if (!session || session !== callSession || !callSocket || callSocket.readyState !== WebSocket.OPEN) {
    return false;
  }

  callSocket.send(JSON.stringify(message));
  return true;
}

function updateCallStatus(message) {
  callStatus.textContent = message;
}

function cleanupCall() {
  const socket = callSocket;
  const connection = peerConnection;
  const stream = localAudioStream;
  const session = callSession;

  callSession = null;
  callSocket = null;
  peerConnection = null;
  localAudioStream = null;

  if (session?.readyTimer !== null && session?.readyTimer !== undefined) {
    clearInterval(session.readyTimer);
  }

  if (socket) {
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    if (socket.readyState < WebSocket.CLOSING) {
      socket.close(1000, "Call ended");
    }
  }

  if (connection) {
    connection.onicecandidate = null;
    connection.ontrack = null;
    connection.onconnectionstatechange = null;
    connection.oniceconnectionstatechange = null;
    connection.close();
  }

  if (stream) {
    stream.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
  }

  remoteAudio.srcObject = null;
  muteButton.disabled = true;
  muteButton.textContent = "Mute microphone";
  startCallButton.classList.add("hidden");
  startCallButton.disabled = false;
}

function startMicrophone(session) {
  if (session !== callSession || localAudioStream) return;

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    updateCallStatus(
      "Microphone access requires a secure context (HTTPS or localhost) and a supported browser."
    );
    startCallButton.textContent = "Try microphone again";
    startCallButton.classList.remove("hidden");
    return;
  }

  startCallButton.disabled = true;
  startCallButton.classList.remove("hidden");
  updateCallStatus("Requesting microphone permission...");

  navigator.mediaDevices.getUserMedia({ audio: true, video: false })
    .then((stream) => {
      if (session !== callSession) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      localAudioStream = stream;
      session.microphoneError = null;
      muteButton.disabled = false;
      startCallButton.classList.add("hidden");
      maybeStartCallNegotiation(session);
      if (session.pendingOffer) {
        const pendingOffer = session.pendingOffer;
        session.pendingOffer = null;
        handleCallSignal(pendingOffer, session).catch((error) => {
          if (session === callSession) {
            updateCallStatus(`Audio negotiation failed: ${error.message}`);
          }
        });
      }
    })
    .catch((error) => {
      if (session !== callSession) return;

      const message =
        error.name === "NotAllowedError" || error.name === "PermissionDeniedError"
          ? "Microphone permission was denied. Allow microphone access in your browser, then retry."
          : error.name === "NotFoundError"
            ? "No microphone was found. Connect a microphone and retry."
            : `Could not access the microphone: ${error.message}`;
      session.microphoneError = message;
      updateCallStatus(
        callSocket?.readyState === WebSocket.OPEN
          ? `${message} Signaling is connected; retry microphone access to continue.`
          : message
      );
      startCallButton.textContent = "Retry microphone access";
      startCallButton.disabled = false;
      startCallButton.classList.remove("hidden");
    });
}

function createCallPeerConnection(session) {
  if (session !== callSession || peerConnection || !localAudioStream) return;

  const connection = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });
  peerConnection = connection;

  localAudioStream.getAudioTracks().forEach((track) => {
    connection.addTrack(track, localAudioStream);
  });

  connection.onicecandidate = (event) => {
    if (event.candidate) {
      sendCallSignal({
        type: "ice_candidate",
        candidate: event.candidate.toJSON(),
      }, session);
    }
  };

  connection.ontrack = (event) => {
    if (session !== callSession) return;
    remoteAudio.srcObject = event.streams[0] || new MediaStream([event.track]);
    remoteAudio.play().catch(() => {
      updateCallStatus("Your partner is connected. Press play on the audio player to hear them.");
    });
  };

  connection.onconnectionstatechange = () => {
    if (session !== callSession) return;

    if (connection.connectionState === "connected") {
      updateCallStatus("Audio call connected.");
    } else if (connection.connectionState === "connecting") {
      updateCallStatus("Negotiating the audio connection...");
    } else if (connection.connectionState === "disconnected") {
      updateCallStatus(
        "The audio connection was interrupted. Automatic reconnection is not available; wait briefly or end the call."
      );
    } else if (connection.connectionState === "failed") {
      updateCallStatus(
        "The audio connection failed. Network restrictions may require a TURN server; end the call and try matching again."
      );
    }
  };
}

async function processPendingCallCandidates(session) {
  if (session !== callSession || !peerConnection?.remoteDescription) return;

  while (session.pendingCandidates.length > 0) {
    const candidate = session.pendingCandidates.shift();
    try {
      await peerConnection.addIceCandidate(candidate);
    } catch (error) {
      if (!session.ignoreOffer) {
        console.error("Could not add a queued ICE candidate:", error);
      }
    }
  }
}

async function handleCallSignal(message, session) {
  if (session !== callSession || message.sender_id !== session.match.partner_id) return;

  if (message.type === "ready") {
    session.partnerReady = true;
    if (session.readyTimer !== null) {
      clearInterval(session.readyTimer);
      session.readyTimer = null;
    }
    if (!session.readyAckSent) {
      session.readyAckSent = true;
      sendCallSignal({ type: "ready" }, session);
    }
    maybeStartCallNegotiation(session);
    return;
  }

  if (message.type === "offer") {
    if (!localAudioStream) {
      session.pendingOffer = message;
      updateCallStatus("Your partner is calling. Waiting for microphone access...");
      return;
    }

    if (!peerConnection) createCallPeerConnection(session);
    if (!peerConnection) return;

    const readyForOffer =
      !session.makingOffer &&
      (peerConnection.signalingState === "stable" || session.settingRemoteAnswer);
    const offerCollision = !readyForOffer;
    session.ignoreOffer = !session.polite && offerCollision;
    if (session.ignoreOffer) return;

    if (offerCollision && session.polite) {
      await peerConnection.setLocalDescription({ type: "rollback" });
    }

    await peerConnection.setRemoteDescription({ type: "offer", sdp: message.sdp });
    await processPendingCallCandidates(session);
    const answer = await peerConnection.createAnswer();
    await peerConnection.setLocalDescription(answer);
    sendCallSignal({
      type: "answer",
      sdp: peerConnection.localDescription.sdp,
    }, session);
    return;
  }

  if (message.type === "answer" && peerConnection) {
    session.settingRemoteAnswer = true;
    try {
      await peerConnection.setRemoteDescription({ type: "answer", sdp: message.sdp });
      await processPendingCallCandidates(session);
    } finally {
      session.settingRemoteAnswer = false;
    }
    return;
  }

  if (message.type === "ice_candidate" && message.candidate) {
    const candidate = new RTCIceCandidate(message.candidate);
    if (!peerConnection?.remoteDescription) {
      session.pendingCandidates.push(candidate);
    } else {
      try {
        await peerConnection.addIceCandidate(candidate);
      } catch (error) {
        if (!session.ignoreOffer) {
          console.error("Could not add ICE candidate:", error);
        }
      }
    }
    return;
  }

  if (message.type === "user_disconnected") {
    updateCallStatus(
      "Your partner disconnected. Automatic reconnection is not available; end the call and start a new search."
    );
  }
}

async function maybeStartCallNegotiation(session) {
  if (
    session !== callSession ||
    !session.partnerReady ||
    !session.userId ||
    !localAudioStream ||
    !callSocket ||
    callSocket.readyState !== WebSocket.OPEN
  ) {
    return;
  }

  try {
    createCallPeerConnection(session);
  } catch (error) {
    updateCallStatus(`Could not initialize WebRTC: ${error.message}`);
    return;
  }
  if (!peerConnection || session.offerStarted) return;

  // A stable user-id ordering elects one initial offerer for the matched pair.
  if (session.userId.localeCompare(session.match.partner_id) >= 0) {
    updateCallStatus("Microphone ready. Waiting for your partner to start the audio connection...");
    return;
  }

  session.offerStarted = true;
  session.makingOffer = true;
  try {
    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);
    if (!sendCallSignal({
      type: "offer",
      sdp: peerConnection.localDescription.sdp,
    }, session)) {
      throw new Error("The signaling connection is not available.");
    }
    updateCallStatus("Calling your partner...");
  } catch (error) {
    updateCallStatus(`Could not start the audio connection: ${error.message}`);
  } finally {
    session.makingOffer = false;
  }
}

function startCall(match) {
  cleanupCall();
  const session = {
    match,
    userId: null,
    partnerReady: false,
    polite: false,
    makingOffer: false,
    settingRemoteAnswer: false,
    ignoreOffer: false,
    offerStarted: false,
    readyTimer: null,
    readyAckSent: false,
    pendingOffer: null,
    microphoneError: null,
    pendingCandidates: [],
  };
  callSession = session;
  startCallButton.textContent = "Enable microphone and start audio";
  startCallButton.classList.add("hidden");
  muteButton.disabled = true;
  remoteAudio.srcObject = null;

  let signalingUrl;
  try {
    const backend = new URL(API_BASE);
    backend.protocol = backend.protocol === "https:" ? "wss:" : "ws:";
    signalingUrl = new URL(
      `${backend.protocol}//${backend.host}/ws/conversation/${encodeURIComponent(match.conversation_id)}`
    );
    signalingUrl.searchParams.set("token", getToken());
    callSocket = new WebSocket(signalingUrl.toString());
  } catch (error) {
    updateCallStatus(`Could not open call signaling: ${error.message}`);
    startCallButton.textContent = "End the call and try again";
    return;
  }

  const socket = callSocket;
  socket.onopen = () => {
    if (session !== callSession) return;
    updateCallStatus(
      session.microphoneError
        ? `${session.microphoneError} Signaling is connected; retry microphone access to continue.`
        : "Signaling connected. Allow microphone access to start audio."
    );
  };

  socket.onmessage = async (event) => {
    if (session !== callSession) return;
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      console.error("Invalid WebSocket signaling message:", error);
      updateCallStatus("Received an invalid signaling message.");
      return;
    }

    if (message.type === "connected") {
      if (message.conversation_id !== match.conversation_id) {
        updateCallStatus("Signaling connected to an unexpected conversation.");
        return;
      }
      session.userId = String(message.user_id);
      session.polite = session.userId.localeCompare(match.partner_id) > 0;
      const announceReady = () => {
        if (session !== callSession || session.partnerReady) {
          clearInterval(session.readyTimer);
          session.readyTimer = null;
          return;
        }
        sendCallSignal({ type: "ready" }, session);
      };
      announceReady();
      if (!session.partnerReady) {
        session.readyTimer = setInterval(announceReady, 1000);
      }
      maybeStartCallNegotiation(session);
    } else {
      try {
        await handleCallSignal(message, session);
      } catch (error) {
        if (session === callSession) {
          updateCallStatus(`Audio negotiation failed: ${error.message}`);
        }
      }
    }
  };

  socket.onerror = () => {
    if (session === callSession) {
      updateCallStatus("Signaling error. Check your network and try ending the call.");
    }
  };

  socket.onclose = (event) => {
    if (session === callSession) {
      updateCallStatus(
        `Signaling disconnected (${event.code}). Automatic reconnection is not available; end the call and start a new search.`
      );
    }
  };

  startMicrophone(session);
}

startCallButton.addEventListener("click", () => {
  if (callSession) startMicrophone(callSession);
});

muteButton.addEventListener("click", () => {
  if (!localAudioStream) return;
  const enabled = localAudioStream.getAudioTracks().some((track) => track.enabled);
  localAudioStream.getAudioTracks().forEach((track) => {
    track.enabled = !enabled;
  });
  muteButton.textContent = enabled ? "Unmute microphone" : "Mute microphone";
  updateCallStatus(enabled ? "Microphone muted." : "Microphone unmuted.");
});

endCallButton.addEventListener("click", () => {
  cleanupCall();
  showView("dashboard-view");
  showNotice("Call ended.", "success");
});

window.addEventListener("pagehide", cleanupCall);

async function pollForMatch(flowId) {
  if (
    flowId !== matchingFlowId ||
    !document.getElementById("matching-view").classList.contains("active")
  ) {
    return;
  }

  try {
    const result = await apiRequest("/matching/find", { method: "POST" });
    if (flowId !== matchingFlowId) return;

    if (result.status === "matched") {
      if (!result.conversation_id || !result.partner_id) {
        throw new Error("The server reported a match without conversation details.");
      }
      showMatchedPartner(result);
      return;
    }

    if (result.status !== "waiting") {
      throw new Error(
        result.status === "cancelled"
          ? "The matching search was cancelled."
          : "You are no longer in the matching queue. Please try again."
      );
    }

    matchingLoader.classList.remove("hidden");
    matchingTitle.textContent = "Searching for a partner...";
    matchingMessage.textContent = "Keep this page open. We’ll notify you as soon as a learner at your level is found.";
    matchingPollTimer = setTimeout(() => pollForMatch(flowId), MATCHING_POLL_INTERVAL);
  } catch (error) {
    if (flowId !== matchingFlowId) return;
    matchingTitle.textContent = "Matching could not continue";
    matchingMessage.textContent = error.message || "Please try again.";
    matchingLoader.classList.add("hidden");
    cancelMatchingButton.classList.remove("hidden");
    cancelMatchingButton.disabled = false;

    if (error.sessionExpired) {
      showView("auth-view");
      showNotice(error.message, "error");
    }
  }
}

// Join the queue and start one controlled, non-overlapping poll loop.
const practiceForm = document.getElementById("practice-form");
practiceForm.addEventListener("submit", (event) => {
  event.preventDefault();
  hideNotice();
  const flowId = ++matchingFlowId;
  stopMatchingPolling();
  activeMatch = null;
  matchingTitle.textContent = "Joining the queue...";
  matchingMessage.textContent = "We’re getting your practice search ready.";
  matchingLoader.classList.remove("hidden");
  cancelMatchingButton.classList.remove("hidden");
  cancelMatchingButton.disabled = true;
  showView("matching-view");

  apiRequest("/matching/join", {
    method: "POST",
    body: JSON.stringify({
      english_level: document.getElementById("english-level").value,
    }),
  }).then((result) => {
    if (flowId !== matchingFlowId) return;

    cancelMatchingButton.disabled = false;
    matchingTitle.textContent =
      result.status === "matched"
        ? "Checking your existing match..."
        : "Searching for a partner...";
    matchingMessage.textContent = "Looking for another learner at your selected level.";
    pollForMatch(flowId);
  }).catch((error) => {
    if (flowId !== matchingFlowId) return;
    cancelMatchingButton.disabled = false;
    matchingLoader.classList.add("hidden");
    matchingTitle.textContent = "Could not join the queue";
    matchingMessage.textContent = error.message || "Please try again.";
    if (error.sessionExpired) {
      showView("auth-view");
      showNotice(error.message, "error");
    }
  });
});

cancelMatchingButton.addEventListener("click", async () => {
  const flowId = ++matchingFlowId;
  stopMatchingPolling();
  cancelMatchingButton.disabled = true;
  matchingLoader.classList.remove("hidden");
  matchingTitle.textContent = "Cancelling your search...";
  matchingMessage.textContent = "Leaving the matching queue.";

  try {
    const result = await apiRequest("/matching/cancel", { method: "POST" });
    if (flowId !== matchingFlowId) return;

    if (result.status === "matched") {
      await pollForMatch(flowId);
      return;
    }

    showView("dashboard-view");
    showNotice("Your search was cancelled.", "success");
  } catch (error) {
    if (flowId !== matchingFlowId) return;
    cancelMatchingButton.disabled = false;
    matchingLoader.classList.add("hidden");
    matchingTitle.textContent = "Could not cancel the search";
    matchingMessage.textContent = error.message || "Please try again.";
    if (error.sessionExpired) {
      showView("auth-view");
      showNotice(error.message, "error");
    }
  }
});

// Restore login after refreshing the page
async function initializeApp() {
  if (!getToken()) {
    showView("auth-view");
    return;
  }

  try {
    await loadDashboard();
  } catch (error) {
    showView("auth-view");
    showNotice(
      error.sessionExpired
        ? error.message
        : "Could not load your dashboard. Please try again.",
      "error"
    );
  }
}

initializeApp();
