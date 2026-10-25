
const API_BASE = (window.IMPROBUDDY_API_BASE || "").replace(/\/+$/, "");
const TOKEN_KEY = "improbuddy_access_token";

// DOM elements
const notice = document.getElementById("notice");
const userEmail = document.getElementById("user-email");
const userArea = document.getElementById("user-area");

const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");
const loginButton = loginForm.querySelector('button[type="submit"]');
const loginButtonLabel = loginButton.querySelector(".auth-submit-label");
const loginSpinner = loginButton.querySelector(".auth-spinner");
const LOGIN_TIMEOUT_MS = 20000;
let loginInProgress = false;

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
    const error = new Error(
      typeof detail === "string"
        ? detail
        : detail?.message || `Request failed (${response.status})`
    );
    error.status = response.status;
    error.data = data;
    throw error;
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
  document.body.classList.toggle("auth-active", viewId === "auth-view");
  document.body.classList.toggle("call-active", viewId === "call-view");
  document.querySelector('meta[name="theme-color"]').content =
    viewId === "call-view" ? "#10111b" : "#f7f8fc";
}

// Display the dashboard
async function loadDashboard({ signal } = {}) {
  const user = await apiRequest("/auth/me", { signal });
  userEmail.textContent = user.email;
  userArea.classList.remove("hidden");
  showView("dashboard-view");
  hideNotice();

  try {
    await apiRequest("/profile", { signal });
  } catch (error) {
    if (error.sessionExpired || signal?.aborted) {
      throw error;
    }
    console.warn("Could not load profile:", error.message);
  }
}

// Login
loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (loginInProgress) return;
  loginInProgress = true;
  hideNotice();

  loginButton.disabled = true;
  loginButton.classList.add("is-loading");
  loginButton.setAttribute("aria-busy", "true");
  loginButtonLabel.textContent = "Signing you in…";
  loginSpinner.hidden = false;
  const requestController = new AbortController();
  let requestTimedOut = false;
  const timeout = setTimeout(() => {
    requestTimedOut = true;
    requestController.abort();
  }, LOGIN_TIMEOUT_MS);

  try {
    const email = loginForm.elements.namedItem("email").value.trim();
    const password = loginForm.elements.namedItem("password").value;

    const data = await apiRequest("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
      signal: requestController.signal,
    });

    localStorage.setItem(TOKEN_KEY, data.access_token);

    await loadDashboard({ signal: requestController.signal });
    loginForm.reset();
  } catch (error) {
    clearTimeout(timeout);
    localStorage.removeItem(TOKEN_KEY);
    userEmail.textContent = "";
    userArea.classList.add("hidden");
    showView("auth-view");
    showNotice(
      requestTimedOut
        ? "Login request timed out. Check your connection and try again."
        : error.message || "Login failed. Please check your details and try again.",
      "error"
    );
  } finally {
    clearTimeout(timeout);
    loginInProgress = false;
    loginButton.disabled = false;
    loginButton.classList.remove("is-loading");
    loginButton.setAttribute("aria-busy", "false");
    loginButtonLabel.textContent = "Log in";
    loginSpinner.hidden = true;
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
const callPanel = document.querySelector(".call-panel");
const startCallButton = document.getElementById("start-call-btn");
const remoteAudioRetryButton = document.getElementById("remote-audio-retry-btn");
const endCallButton = document.getElementById("end-call-btn");
const skipPartnerButton = document.getElementById("skip-partner-btn");
const skipLimitMessage = document.getElementById("skip-limit-message");
const muteButton = document.getElementById("mute-btn");
const muteLabel = document.getElementById("mute-label");
const skipLabel = document.getElementById("skip-label");
const callConnectionState = document.getElementById("call-connection-state");
const callConnectionLabel = document.getElementById("call-connection-label");
const callDuration = document.getElementById("call-duration");
const partnerName = document.getElementById("partner-name");
const partnerAvatar = document.getElementById("partner-avatar");
const transcriptToggle = document.getElementById("transcript-toggle");
const transcriptContent = document.getElementById("transcript-content");
const transcriptState = document.getElementById("transcript-state");
const browserTranscriptButton = document.getElementById("browser-transcript-button");
const remoteAudio = document.getElementById("remote-audio");
const transcriptStatus = document.getElementById("transcript-status");
const serverTranscriptStatus = document.getElementById("server-transcript-status");
const transcriptInterim = document.getElementById("transcript-interim");
const transcriptList = document.getElementById("transcript-list");
const MATCHING_POLL_INTERVAL = 2000;
let matchingPollTimer = null;
let matchingFlowId = 0;
let matchingStartedAt = 0;
let matchingFallbackAfterSeconds = 9;
let activeMatch = null;
let callSession = null;
let callSocket = null;
let peerConnection = null;
let localAudioStream = null;
let skipLimitTimer = null;

function setTranscriptStatus(message, state = null) {
  transcriptStatus.textContent = message;
  if (state) setTranscriptState(state);
}

function setServerTranscriptStatus(message) {
  serverTranscriptStatus.textContent = message;
}

function setTranscriptState(state) {
  transcriptState.textContent = state;
  transcriptState.dataset.state = state.toLowerCase();
}

function setCallConnectionState(state) {
  const labels = {
    connecting: "Connecting",
    connected: "Connected",
    disconnected: "Disconnected",
  };
  callConnectionState.dataset.state = state;
  callConnectionLabel.textContent = labels[state];
}

function formatCallDuration(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}

function updateCallDuration(session) {
  if (session !== callSession || session.connectedAt === null) return;
  const elapsed = session.callDurationMs + Date.now() - session.connectedAt;
  callDuration.textContent = formatCallDuration(Math.floor(elapsed / 1000));
}

function startCallDuration(session) {
  if (session !== callSession || session.durationTimer !== null) return;
  session.connectedAt = Date.now();
  updateCallDuration(session);
  session.durationTimer = setInterval(() => updateCallDuration(session), 1000);
}

function stopCallDuration(session) {
  if (!session) return;
  if (session.durationTimer !== null) {
    clearInterval(session.durationTimer);
    session.durationTimer = null;
  }
  if (session.connectedAt !== null) {
    session.callDurationMs += Date.now() - session.connectedAt;
    session.connectedAt = null;
  }
  if (session === callSession) {
    callDuration.textContent = formatCallDuration(
      Math.floor(session.callDurationMs / 1000)
    );
  }
}

function updateMuteControl(isMuted) {
  muteButton.classList.toggle("is-muted", isMuted);
  muteButton.setAttribute("aria-pressed", String(isMuted));
  muteButton.setAttribute("aria-label", isMuted ? "Unmute microphone" : "Mute microphone");
  muteLabel.textContent = isMuted ? "Unmute" : "Mute";
}

function clearPrivateTranscript() {
  transcriptList.replaceChildren();
  const emptyMessage = document.createElement("p");
  emptyMessage.id = "transcript-empty";
  emptyMessage.className = "muted empty-state";
  emptyMessage.textContent =
    "Your private transcript will appear here when speech is recognized.";
  transcriptList.append(emptyMessage);
  transcriptInterim.textContent = "";
}

function appendPrivateTranscript(text) {
  if (!text) return;
  document.getElementById("transcript-empty")?.remove();
  const entry = document.createElement("p");
  entry.className = "transcript-entry";
  entry.textContent = text;
  transcriptList.append(entry);

  while (transcriptList.children.length > 200) {
    transcriptList.firstElementChild?.remove();
  }
}

function speechRecognitionConstructor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

const SPEECH_RESTART_DELAYS = [750, 1500, 3000];
const SPEECH_START_TIMEOUT_MS = 10000;
const SPEECH_STABLE_DURATION_MS = 12000;

function updateBrowserTranscriptButton(session) {
  const supported = Boolean(speechRecognitionConstructor());
  browserTranscriptButton.classList.toggle("hidden", !supported);
  if (!supported) return;

  browserTranscriptButton.textContent =
    session.speechRecognitionActive || session.speechRecognitionStarting
      ? "Stop live transcript"
      : session.speechRecognitionRequested
        ? "Resume live transcript"
        : "Start live transcript";
  browserTranscriptButton.disabled = !session.callConnected;
}

function prepareBrowserSpeechRecognition(session) {
  if (session !== callSession) return;
  if (!speechRecognitionConstructor()) {
    browserTranscriptButton.classList.add("hidden");
    setTranscriptStatus(
      "Live transcript is not supported in this browser.",
      "unavailable"
    );
    return;
  }

  updateBrowserTranscriptButton(session);
  if (session.speechRecognitionActive) return;
  if (session.speechRecognitionStarting) return;
  if (session.speechRecognitionRequested && session.speechNeedsUserGesture) {
    setTranscriptStatus(
      "Tap Resume live transcript to continue after the browser interruption.",
      "paused"
    );
    return;
  }
  if (session.speechRecognitionRequested && session.speechRestartTimer !== null) {
    return;
  }
  setTranscriptStatus(
    "Tap Start live transcript to begin private browser speech recognition.",
    "ready"
  );
}

function clearSpeechTimers(session) {
  clearTimeout(session.speechRestartTimer);
  clearTimeout(session.speechStartTimer);
  session.speechRestartTimer = null;
  session.speechStartTimer = null;
}

function scheduleBrowserSpeechRestart(session, recognition) {
  if (
    session !== callSession ||
    !session.speechRecognitionRequested ||
    session.speechNeedsUserGesture ||
    !session.callConnected ||
    document.visibilityState !== "visible" ||
    !localAudioStream?.getAudioTracks().some((track) => track.enabled)
  ) {
    return;
  }

  if (session.speechRestartAttempts >= SPEECH_RESTART_DELAYS.length) {
    session.speechRecognitionRequested = false;
    updateBrowserTranscriptButton(session);
    setTranscriptStatus(
      "Live transcript stopped after repeated browser interruptions. Tap to try again.",
      "unavailable"
    );
    return;
  }

  const delay = SPEECH_RESTART_DELAYS[session.speechRestartAttempts];
  session.speechRestartAttempts += 1;
  updateBrowserTranscriptButton(session);
  setTranscriptStatus(
    `Browser speech recognition stopped. Retrying (${session.speechRestartAttempts}/${SPEECH_RESTART_DELAYS.length})…`,
    "reconnecting"
  );
  session.speechRestartTimer = setTimeout(() => {
    session.speechRestartTimer = null;
    if (
      session === callSession &&
      session.speechRecognition === recognition &&
      session.speechRecognitionRequested
    ) {
      startBrowserSpeechRecognition(session);
    }
  }, delay);
}

function createTranscriptionStreamId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  if (!window.crypto?.getRandomValues) return null;
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function startBrowserSpeechRecognition(session, fromUserGesture = false) {
  if (session !== callSession) return;
  const SpeechRecognition = speechRecognitionConstructor();
  if (!SpeechRecognition) {
    browserTranscriptButton.classList.add("hidden");
    setTranscriptStatus(
      "Live transcript is not supported in this browser.",
      "unavailable"
    );
    return;
  }

  if (fromUserGesture) {
    session.speechRecognitionRequested = true;
    session.speechNeedsUserGesture = false;
    session.speechRestartAttempts = 0;
  }
  if (!session.callConnected) {
    setTranscriptStatus("Connect the audio call before starting a live transcript.", "waiting");
    return;
  }
  if (!localAudioStream?.getAudioTracks().some((track) => track.enabled)) {
    setTranscriptStatus("Unmute your microphone before starting the live transcript.", "paused");
    updateBrowserTranscriptButton(session);
    return;
  }
  if (document.visibilityState !== "visible") {
    session.speechNeedsUserGesture = true;
    setTranscriptStatus(
      "Live transcript is paused while this page is in the background. Return and tap Resume live transcript.",
      "paused"
    );
    updateBrowserTranscriptButton(session);
    return;
  }
  if (!session.speechRecognitionRequested) return;
  if (session.speechRecognitionActive || session.speechRecognitionStarting) return;

  if (!session.speechRecognition) {
    try {
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";
      session.speechRecognition = recognition;

      recognition.onstart = () => {
        if (session !== callSession) return;
        clearSpeechTimers(session);
        session.speechRecognitionStarting = false;
        session.speechRecognitionActive = true;
        session.speechStartedAt = Date.now();
        session.speechLastFinalIndex = -1;
        updateBrowserTranscriptButton(session);
        setTranscriptStatus("Listening for your speech on this device.", "listening");
      };

      recognition.onresult = (event) => {
        if (session !== callSession) return;
        let interim = "";
        const firstChangedResult = Math.max(0, event.resultIndex || 0);
        for (let index = firstChangedResult; index < event.results.length; index += 1) {
          const result = event.results[index];
          const text = result[0]?.transcript?.trim();
          if (!text) continue;
          if (result.isFinal) {
            if (index > session.speechLastFinalIndex) {
              appendPrivateTranscript(text);
              session.speechLastFinalIndex = index;
            }
          } else {
            interim += `${text} `;
          }
        }
        transcriptInterim.textContent = interim.trim();
      };

      recognition.onerror = (event) => {
        if (session !== callSession) return;
        clearTimeout(session.speechStartTimer);
        session.speechStartTimer = null;
        session.speechRecognitionStarting = false;
        session.speechRecognitionActive = false;
        updateBrowserTranscriptButton(session);
        const fatalErrors = [
          "not-allowed",
          "service-not-allowed",
          "audio-capture",
          "language-not-supported",
        ];
        if (fatalErrors.includes(event.error)) {
          session.speechRecognitionRequested = false;
          const message = event.error === "not-allowed" || event.error === "service-not-allowed"
            ? "Browser speech recognition permission was denied. Check browser microphone permissions and try again."
            : event.error === "audio-capture"
              ? "Browser speech recognition cannot access a microphone. The audio call can continue."
              : "English speech recognition is not available in this browser.";
          setTranscriptStatus(message, "unavailable");
          updateBrowserTranscriptButton(session);
        } else if (event.error === "no-speech") {
          setTranscriptStatus(
            "No speech was detected. Waiting for the browser to restart recognition.",
            "reconnecting"
          );
        } else if (event.error !== "aborted") {
          setTranscriptStatus(
            `Browser speech recognition was interrupted (${event.error}).`,
            "reconnecting"
          );
        }
      };

      recognition.onend = () => {
        if (session !== callSession || session.speechRecognition !== recognition) return;
        clearTimeout(session.speechStartTimer);
        session.speechStartTimer = null;
        const ranFor = session.speechStartedAt
          ? Date.now() - session.speechStartedAt
          : 0;
        session.speechRecognitionActive = false;
        session.speechRecognitionStarting = false;
        session.speechStartedAt = null;
        transcriptInterim.textContent = "";
        if (ranFor >= SPEECH_STABLE_DURATION_MS) {
          session.speechRestartAttempts = 0;
        }
        updateBrowserTranscriptButton(session);
        if (session.speechRecognitionRequested && !session.speechNeedsUserGesture) {
          scheduleBrowserSpeechRestart(session, recognition);
        }
      };
    } catch (error) {
      session.speechRecognitionRequested = false;
      setTranscriptStatus(
        `Browser speech recognition could not be initialized: ${error.message}`,
        "unavailable"
      );
      updateBrowserTranscriptButton(session);
      return;
    }
  }

  session.speechRecognitionStarting = true;
  setTranscriptStatus("Starting browser speech recognition…", "starting");
  updateBrowserTranscriptButton(session);
  try {
    session.speechRecognition.start();
    clearTimeout(session.speechStartTimer);
    session.speechStartTimer = setTimeout(() => {
      if (
        session === callSession &&
        session.speechRecognitionStarting &&
        session.speechRecognition
      ) {
        session.speechRecognitionStarting = false;
        session.speechRecognitionRequested = false;
        stopBrowserSpeechRecognition(session);
        setTranscriptStatus(
          "Browser speech recognition did not start. Check microphone permission and try again.",
          "unavailable"
        );
        updateBrowserTranscriptButton(session);
      }
    }, SPEECH_START_TIMEOUT_MS);
  } catch (error) {
    session.speechRecognitionStarting = false;
    if (error.name === "InvalidStateError") {
      setTranscriptStatus(
        "The browser is already starting speech recognition. Wait briefly or tap Resume to try again.",
        "reconnecting"
      );
      updateBrowserTranscriptButton(session);
      return;
    }
    session.speechRecognitionRequested = false;
    setTranscriptStatus(
      `Browser speech recognition could not start: ${error.message}`,
      "unavailable"
    );
    updateBrowserTranscriptButton(session);
  }
}

function stopBrowserSpeechRecognition(session, preserveRequest = false) {
  if (!session) return;
  clearSpeechTimers(session);
  session.speechRecognitionActive = false;
  session.speechRecognitionStarting = false;
  if (!preserveRequest) {
    session.speechRecognitionRequested = false;
    session.speechNeedsUserGesture = false;
  }
  if (session.speechRecognition) {
    session.speechRecognition.onstart = null;
    session.speechRecognition.onresult = null;
    session.speechRecognition.onerror = null;
    session.speechRecognition.onend = null;
    try {
      session.speechRecognition.abort();
    } catch (error) {
      console.warn("Could not stop browser speech recognition:", error.message);
    }
    session.speechRecognition = null;
  }
  transcriptInterim.textContent = "";
}

function resampleTo16k(samples, sourceRate) {
  const ratio = sourceRate / 16000;
  const outputLength = Math.floor(samples.length / ratio);
  const output = new Int16Array(outputLength);

  for (let index = 0; index < outputLength; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(samples.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    for (let sourceIndex = start; sourceIndex < end; sourceIndex += 1) {
      sum += samples[sourceIndex];
    }
    const sample = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function createWavBuffer(samples) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeAscii = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true);
  view.setUint32(28, 32000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => view.setInt16(44 + index * 2, sample, true));
  return buffer;
}

function bufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const blockSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += blockSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + blockSize));
  }
  return btoa(binary);
}

function sendAudioChunk(session, audioSamples, sourceRate) {
  const socket = session.transcriptionSocket;
  if (
    session !== callSession ||
    !session.callConnected ||
    !socket ||
    socket.readyState !== WebSocket.OPEN ||
    !localAudioStream?.getAudioTracks().some((track) => track.enabled)
  ) {
    audioSamples.fill(0);
    return;
  }
  if (session.serverChunkPendingSequence !== null) {
    setServerTranscriptStatus("A Faster-Whisper chunk is still processing; this chunk was skipped.");
    audioSamples.fill(0);
    return;
  }
  if (socket.bufferedAmount > 500_000) {
    setServerTranscriptStatus("Faster-Whisper is busy; a chunk was skipped to keep the call responsive.");
    audioSamples.fill(0);
    return;
  }

  let pcmSamples;
  let wav;
  let message = null;
  let serialized = "";
  try {
    pcmSamples = resampleTo16k(audioSamples, sourceRate);
    wav = createWavBuffer(pcmSamples);
    if (wav.byteLength > 256 * 1024) {
      setServerTranscriptStatus("A Faster-Whisper audio chunk exceeded the size limit and was discarded.");
      return;
    }

    const sequence = session.transcriptionSequence++;
    message = {
      type: "audio_chunk",
      stream_id: session.transcriptionStreamId,
      sequence,
      captured_at: new Date().toISOString(),
      audio: bufferToBase64(wav),
    };
    session.serverChunkPendingSequence = sequence;
    serialized = JSON.stringify(message);
    socket.send(serialized);
    setServerTranscriptStatus("Faster-Whisper is processing a private audio chunk.");
  } catch (error) {
    session.serverChunkPendingSequence = null;
    setServerTranscriptStatus(`Faster-Whisper could not process an audio chunk: ${error.message}`);
  } finally {
    audioSamples.fill(0);
    pcmSamples?.fill(0);
    if (wav) new Uint8Array(wav).fill(0);
    if (message) message.audio = "";
    serialized = "";
  }
}

async function startAudioChunkCapture(session) {
  if (
    session !== callSession ||
    !session.callConnected ||
    !session.transcriptionReady ||
    session.audioChunkCaptureStarted ||
    !localAudioStream?.getAudioTracks().some((track) => track.enabled)
  ) {
    return;
  }

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (
    !AudioContextClass ||
    typeof AudioWorkletNode === "undefined" ||
    !session.transcriptionStreamId
  ) {
    setServerTranscriptStatus("This browser does not support Faster-Whisper audio capture.");
    return;
  }

  session.audioChunkCaptureStarted = true;
  try {
    const context = new AudioContextClass();
    session.audioContext = context;
    await context.audioWorklet.addModule("audio-chunk-processor.js");
    if (session !== callSession) {
      await context.close();
      return;
    }

    const source = context.createMediaStreamSource(localAudioStream);
    const worklet = new AudioWorkletNode(context, "improbuddy-audio-chunk", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      channelCount: 1,
      channelCountMode: "explicit",
    });
    const silentOutput = context.createGain();
    silentOutput.gain.value = 0;
    source.connect(worklet);
    worklet.connect(silentOutput);
    silentOutput.connect(context.destination);
    worklet.port.onmessage = (event) => {
      if (!(event.data?.samples instanceof ArrayBuffer)) {
        return;
      }
      const audioSamples = new Float32Array(event.data.samples);
      if (session !== callSession || !Number.isFinite(event.data.sampleRate)) {
        audioSamples.fill(0);
        return;
      }
      sendAudioChunk(
        session,
        audioSamples,
        event.data.sampleRate
      );
    };

    session.audioSource = source;
    session.audioWorklet = worklet;
    session.silentOutput = silentOutput;
    await context.resume();
    if (context.state !== "running") {
      throw new Error("The audio processor could not start.");
    }
    setServerTranscriptStatus("Faster-Whisper audio capture is active for this call.");
  } catch (error) {
    session.audioChunkCaptureStarted = false;
    if (session !== callSession) return;
    setServerTranscriptStatus(
      `Faster-Whisper is unavailable: ${error.message}. Browser transcription and the audio call can continue.`
    );
    if (session.audioContext && session.audioContext.state !== "closed") {
      await session.audioContext.close().catch((closeError) => {
        console.warn("Could not close the transcription audio context:", closeError.message);
      });
    }
    session.audioContext = null;
  }
}

function closeAudioChunkCapture(session) {
  session.audioChunkCaptureStarted = false;
  if (session.audioWorklet) {
    session.audioWorklet.port.onmessage = null;
    session.audioWorklet.disconnect();
    session.audioWorklet = null;
  }
  session.audioSource?.disconnect();
  session.audioSource = null;
  session.silentOutput?.disconnect();
  session.silentOutput = null;
  if (session.audioContext && session.audioContext.state !== "closed") {
    session.audioContext.close().catch((error) => {
      console.warn("Could not close the transcription audio context:", error.message);
    });
  }
  session.audioContext = null;
}

function startCallTranscription(session) {
  if (session !== callSession || !session.callConnected) return;
  prepareBrowserSpeechRecognition(session);
  const speakerIdentityMatches = !(
    session.transcriptionSpeakerId &&
    session.userId &&
    session.transcriptionSpeakerId !== session.userId
  );
  if (!speakerIdentityMatches) {
    session.transcriptionReady = false;
    setServerTranscriptStatus("Faster-Whisper speaker identity did not match this call.");
  } else {
    startAudioChunkCapture(session);
  }
}

function createCallSocketUrl(conversationId, suffix = "") {
  const backend = new URL(API_BASE);
  backend.protocol = backend.protocol === "https:" ? "wss:" : "ws:";
  const socketUrl = new URL(
    `${backend.protocol}//${backend.host}/ws/conversation/${encodeURIComponent(conversationId)}${suffix}`
  );
  socketUrl.searchParams.set("token", getToken());
  return socketUrl.toString();
}

function clearSkipLimitTimer() {
  if (skipLimitTimer !== null) {
    clearTimeout(skipLimitTimer);
    skipLimitTimer = null;
  }
}

function setSkipAvailability(remaining, retryAfterSeconds) {
  clearSkipLimitTimer();
  const limitReached = remaining <= 0;
  skipPartnerButton.disabled = limitReached;
  skipLabel.textContent = limitReached ? "Unavailable" : "Skip Partner";
  skipLimitMessage.classList.toggle("hidden", !limitReached);

  if (!limitReached) {
    skipLimitMessage.textContent = "";
    return;
  }

  const minutes = Math.ceil(retryAfterSeconds / 60);
  const remainingTime = retryAfterSeconds < 60
    ? `${retryAfterSeconds} second${retryAfterSeconds === 1 ? "" : "s"}`
    : `${minutes} minute${minutes === 1 ? "" : "s"}`;
  skipLimitMessage.textContent =
    `Skip limit reached. You can skip again in about ${remainingTime}.`;
  skipLimitTimer = setTimeout(() => {
    if (activeMatch) refreshSkipAvailability(activeMatch);
  }, Math.max(1, retryAfterSeconds) * 1000);
}

async function refreshSkipAvailability(match) {
  try {
    const availability = await apiRequest("/matching/skip-status");
    if (activeMatch !== match) return;
    setSkipAvailability(
      availability.skips_remaining,
      availability.retry_after_seconds ?? 0
    );
  } catch (error) {
    if (activeMatch !== match) return;
    if (error.sessionExpired) {
      showView("auth-view");
      showNotice(error.message, "error");
      return;
    }
    console.warn("Could not load skip availability:", error.message);
  }
}

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
  const partnerLabel = typeof match.partner_name === "string" && match.partner_name.trim()
    ? match.partner_name.trim()
    : "Your practice partner";
  const initials = partnerLabel === "Your practice partner"
    ? "?"
    : partnerLabel.split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase();
  partnerName.textContent = partnerLabel;
  partnerAvatar.textContent = initials;
  matchingMessage.textContent = `Matched with ${partnerLabel}.`;
  cancelMatchingButton.classList.add("hidden");
  setSkipAvailability(1, 0);
  callStatus.textContent = "Connecting to your audio practice session...";
  showView("call-view");
  refreshSkipAvailability(match);
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

function pauseCallUi(session) {
  if (session !== callSession) return;
  session.callConnected = false;
  callPanel.classList.remove("is-connected");
  remoteAudioRetryButton.classList.add("hidden");
  setCallConnectionState("disconnected");
  stopCallDuration(session);
  stopBrowserSpeechRecognition(session);
  browserTranscriptButton.classList.add("hidden");
  closeAudioChunkCapture(session);
  setTranscriptStatus(
    "Browser transcript stopped because the audio call is disconnected.",
    "paused"
  );
  setServerTranscriptStatus("Faster-Whisper capture stopped because the audio call disconnected.");
}

function cleanupCall() {
  clearSkipLimitTimer();
  const socket = callSocket;
  const connection = peerConnection;
  const stream = localAudioStream;
  const session = callSession;

  stopCallDuration(session);
  if (session) {
    stopBrowserSpeechRecognition(session);
    closeAudioChunkCapture(session);
    const transcriptionSocket = session.transcriptionSocket;
    if (transcriptionSocket) {
      transcriptionSocket.onopen = null;
      transcriptionSocket.onmessage = null;
      transcriptionSocket.onerror = null;
      transcriptionSocket.onclose = null;
      if (transcriptionSocket.readyState < WebSocket.CLOSING) {
        transcriptionSocket.close(1000, "Call ended");
      }
    }
  }
  clearPrivateTranscript();

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
  callPanel.classList.remove("is-connected");
  muteButton.disabled = true;
  updateMuteControl(false);
  setCallConnectionState("disconnected");
  startCallButton.classList.add("hidden");
  startCallButton.disabled = false;
  remoteAudioRetryButton.classList.add("hidden");
}

async function startMicrophone(session) {
  if (
    session !== callSession ||
    localAudioStream ||
    session.microphoneRequestPending
  ) return;

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    updateCallStatus(
      "Microphone access requires a secure context (HTTPS or localhost) and a supported browser."
    );
    startCallButton.textContent = "Try microphone again";
    startCallButton.classList.remove("hidden");
    return;
  }

  session.microphoneRequestPending = true;
  startCallButton.disabled = true;
  startCallButton.classList.remove("hidden");
  updateCallStatus("Requesting microphone permission...");

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  } catch (error) {
    if (session !== callSession) return;

    const message =
      error.name === "NotAllowedError" || error.name === "PermissionDeniedError"
        ? "Microphone permission was denied. Allow microphone access in your browser, then retry."
        : error.name === "NotFoundError"
          ? "No microphone was found. Connect a microphone and retry."
          : `Could not access the microphone: ${error.message}`;
    session.microphoneError = message;
    setTranscriptStatus(
      `${message} Transcription is unavailable until microphone access is granted.`,
      "unavailable"
    );
    updateCallStatus(
      callSocket?.readyState === WebSocket.OPEN
        ? `${message} Signaling is connected; retry microphone access to continue.`
        : message
    );
    startCallButton.textContent = "Retry microphone access";
    startCallButton.disabled = false;
    startCallButton.classList.remove("hidden");
    return;
  } finally {
    session.microphoneRequestPending = false;
  }

  if (session !== callSession) {
    stream.getTracks().forEach((track) => track.stop());
    return;
  }

  localAudioStream = stream;
  session.microphoneError = null;
  muteButton.disabled = false;
  startCallButton.classList.add("hidden");
  setTranscriptStatus("Microphone ready. Waiting for the audio call to connect.", "waiting");
  maybeStartCallNegotiation(session);
  if (session.pendingOffer) {
    const pendingOffer = session.pendingOffer;
    session.pendingOffer = null;
    handleCallSignal(pendingOffer, session).catch((error) => {
      if (session === callSession) {
        pauseCallUi(session);
        updateCallStatus(`Audio negotiation failed: ${error.message}`);
      }
    });
  }
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
      remoteAudioRetryButton.classList.remove("hidden");
      updateCallStatus(
        "Your partner is connected, but browser playback needs your permission."
      );
    });
  };

  connection.onconnectionstatechange = () => {
    if (session !== callSession) return;

    if (connection.connectionState === "connected") {
      callPanel.classList.add("is-connected");
      setCallConnectionState("connected");
      updateCallStatus("Audio call connected.");
      session.callConnected = true;
      startCallDuration(session);
      startCallTranscription(session);
    } else {
      callPanel.classList.remove("is-connected");
      if (connection.connectionState === "disconnected" || connection.connectionState === "failed" || connection.connectionState === "closed") {
        pauseCallUi(session);
      } else if (connection.connectionState === "connecting") {
        setCallConnectionState("connecting");
      }
    }

    if (connection.connectionState === "connecting") {
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
    pauseCallUi(session);
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
    microphoneRequestPending: false,
    pendingCandidates: [],
    callConnected: false,
    callDurationMs: 0,
    connectedAt: null,
    durationTimer: null,
    transcriptionReady: false,
    transcriptionSequence: 0,
    transcriptionStreamId: createTranscriptionStreamId(),
    audioChunkCaptureStarted: false,
    serverChunkPendingSequence: null,
    transcriptionSocket: null,
    speechRecognition: null,
    speechRecognitionActive: false,
    speechRecognitionStarting: false,
    speechRecognitionRequested: false,
    speechNeedsUserGesture: false,
    speechRestartAttempts: 0,
    speechRestartTimer: null,
    speechStartTimer: null,
    speechStartedAt: null,
    speechLastFinalIndex: -1,
    audioContext: null,
    audioSource: null,
    audioWorklet: null,
    silentOutput: null,
  };
  callSession = session;
  clearPrivateTranscript();
  callDuration.textContent = "00:00";
  setCallConnectionState("connecting");
  setTranscriptStatus(
    "Your private browser transcript will be available after the call connects.",
    "waiting"
  );
  setServerTranscriptStatus("Faster-Whisper is connecting separately.");
  browserTranscriptButton.classList.add("hidden");
  startCallButton.textContent = "Enable microphone and start audio";
  startCallButton.disabled = false;
  startCallButton.classList.remove("hidden");
  muteButton.disabled = true;
  updateMuteControl(false);
  callPanel.classList.remove("is-connected");
  transcriptToggle.setAttribute("aria-expanded", "false");
  transcriptContent.classList.add("hidden");
  remoteAudio.srcObject = null;
  remoteAudioRetryButton.classList.add("hidden");

  let signalingUrl;
  try {
    signalingUrl = new URL(createCallSocketUrl(match.conversation_id));
    callSocket = new WebSocket(signalingUrl.toString());
  } catch (error) {
    setCallConnectionState("disconnected");
    updateCallStatus(`Could not open call signaling: ${error.message}`);
    startCallButton.textContent = "End the call and try again";
    return;
  }

  const socket = callSocket;
  try {
    session.transcriptionSocket = new WebSocket(
      createCallSocketUrl(match.conversation_id, "/transcription")
    );
    session.transcriptionSocket.onmessage = (event) => {
      if (session !== callSession) return;
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (error) {
        console.error("Invalid transcription response:", error);
        setServerTranscriptStatus("The Faster-Whisper channel returned an invalid response.");
        return;
      }

      if (
        message.type === "transcription_ready" &&
        message.conversation_id === match.conversation_id
      ) {
        session.transcriptionSpeakerId = message.speaker_id;
        session.transcriptionReady = true;
        if (session.userId && session.transcriptionSpeakerId !== session.userId) {
          setServerTranscriptStatus("Faster-Whisper authenticated a different speaker.");
          session.transcriptionReady = false;
        } else {
          startAudioChunkCapture(session);
        }
      } else if (message.type === "stt_error") {
        if (message.sequence === session.serverChunkPendingSequence) {
          session.serverChunkPendingSequence = null;
        }
        setServerTranscriptStatus(message.message || "Faster-Whisper failed for an audio chunk.");
      } else if (
        (message.type === "transcription_result" || message.type === "chunk_duplicate") &&
        message.sequence === session.serverChunkPendingSequence
      ) {
        session.serverChunkPendingSequence = null;
      }
    };
    session.transcriptionSocket.onerror = () => {
      if (session === callSession) {
        setServerTranscriptStatus("Faster-Whisper is unavailable; the audio call can continue.");
      }
    };
    session.transcriptionSocket.onclose = (event) => {
      if (session === callSession && event.code !== 1000) {
        session.transcriptionReady = false;
        setServerTranscriptStatus("The Faster-Whisper channel disconnected; the audio call can continue.");
      }
    };
  } catch (error) {
    setServerTranscriptStatus(
      `Could not open Faster-Whisper: ${error.message}. Browser transcription remains independent.`
    );
  }

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
      if (
        session.transcriptionSpeakerId &&
        session.transcriptionSpeakerId !== session.userId
      ) {
        session.transcriptionReady = false;
        session.transcriptionSocket?.close(1008, "Speaker identity mismatch");
        setServerTranscriptStatus("Faster-Whisper authenticated a different speaker.");
      }
      startAudioChunkCapture(session);
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
          pauseCallUi(session);
          updateCallStatus(`Audio negotiation failed: ${error.message}`);
        }
      }
    }
  };

  socket.onerror = () => {
    if (session === callSession) {
      pauseCallUi(session);
      updateCallStatus("Signaling error. Check your network and try ending the call.");
    }
  };

  socket.onclose = (event) => {
    if (session === callSession) {
      pauseCallUi(session);
      updateCallStatus(
        `Signaling disconnected (${event.code}). Automatic reconnection is not available; end the call and start a new search.`
      );
    }
  };

}

startCallButton.addEventListener("click", () => {
  if (callSession) startMicrophone(callSession);
});

remoteAudioRetryButton.addEventListener("click", () => {
  if (!remoteAudio.srcObject) return;
  remoteAudioRetryButton.disabled = true;
  remoteAudio.play()
    .then(() => {
      remoteAudioRetryButton.classList.add("hidden");
      updateCallStatus("Audio call connected.");
    })
    .catch((error) => {
      updateCallStatus(`Browser audio playback could not start: ${error.message}`);
    })
    .finally(() => {
      remoteAudioRetryButton.disabled = false;
    });
});

browserTranscriptButton.addEventListener("click", () => {
  const session = callSession;
  if (!session) return;
  if (session.speechRecognitionActive || session.speechRecognitionStarting) {
    stopBrowserSpeechRecognition(session);
    setTranscriptStatus("Browser transcript paused. Tap Start live transcript to resume.", "paused");
    updateBrowserTranscriptButton(session);
    return;
  }
  startBrowserSpeechRecognition(session, true);
});

transcriptToggle.addEventListener("click", () => {
  const expanded = transcriptToggle.getAttribute("aria-expanded") === "true";
  transcriptToggle.setAttribute("aria-expanded", String(!expanded));
  transcriptContent.classList.toggle("hidden", expanded);
});

muteButton.addEventListener("click", () => {
  if (!localAudioStream) return;
  const enabled = localAudioStream.getAudioTracks().some((track) => track.enabled);
  localAudioStream.getAudioTracks().forEach((track) => {
    track.enabled = !enabled;
  });
  updateMuteControl(enabled);
  if (enabled) {
    const resumeBrowserTranscript = Boolean(callSession?.speechRecognitionRequested);
    stopBrowserSpeechRecognition(callSession, resumeBrowserTranscript);
    if (resumeBrowserTranscript && callSession) {
      setTranscriptStatus("Browser transcript paused while your microphone is muted.", "paused");
      updateBrowserTranscriptButton(callSession);
    }
    callSession?.audioContext?.suspend().catch((error) => {
      console.warn("Could not pause server transcription:", error.message);
    });
  } else if (callSession) {
    if (callSession.speechRecognitionRequested) {
      startBrowserSpeechRecognition(callSession, true);
    }
    if (callSession.audioContext) {
      callSession.audioContext.resume().catch((error) => {
        setServerTranscriptStatus(`Faster-Whisper could not resume: ${error.message}`);
      });
    } else {
      startAudioChunkCapture(callSession);
    }
  }
  updateCallStatus(enabled ? "Microphone muted." : "Microphone unmuted.");
});

document.addEventListener("visibilitychange", () => {
  const session = callSession;
  if (!session?.speechRecognitionRequested) return;

  if (document.visibilityState !== "visible") {
    session.speechNeedsUserGesture = true;
    stopBrowserSpeechRecognition(session, true);
    updateBrowserTranscriptButton(session);
    setTranscriptStatus(
      "Browser transcript paused while this page is in the background. Return and tap Resume live transcript.",
      "paused"
    );
  } else if (session.speechNeedsUserGesture && session.callConnected) {
    updateBrowserTranscriptButton(session);
    setTranscriptStatus(
      "Tap Resume live transcript to continue after the browser interruption.",
      "paused"
    );
  }
});

endCallButton.addEventListener("click", async () => {
  const conversationId = activeMatch?.conversation_id;
  cleanupCall();
  activeMatch = null;
  showView("dashboard-view");
  showNotice("Call ended.", "success");

  if (!conversationId) return;

  try {
    await apiRequest("/matching/end", {
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId }),
    });
  } catch (error) {
    showNotice(
      `The call ended on this device, but the server could not update the matching state: ${error.message}`,
      "error"
    );
  }
});

skipPartnerButton.addEventListener("click", async () => {
  if (!activeMatch || skipPartnerButton.disabled) return;

  const conversationId = activeMatch.conversation_id;
  const match = activeMatch;
  const flowId = ++matchingFlowId;
  stopMatchingPolling();
  skipPartnerButton.disabled = true;
  updateCallStatus("Skipping partner...");

  try {
    const result = await apiRequest("/matching/skip", {
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId }),
    });
    if (flowId !== matchingFlowId || activeMatch !== match) return;

    cleanupCall();
    activeMatch = null;
    matchingStartedAt = Date.now();
    matchingFallbackAfterSeconds = result.fallback_after_seconds ?? 9;
    matchingLoader.classList.remove("hidden");
    matchingTitle.textContent = "Searching for another partner...";
    matchingMessage.textContent = "Finding your next partner...";
    cancelMatchingButton.disabled = false;
    cancelMatchingButton.classList.remove("hidden");
    showView("matching-view");
    pollForMatch(flowId);
  } catch (error) {
    if (flowId !== matchingFlowId || activeMatch !== match) return;
    if (error.sessionExpired) {
      activeMatch = null;
      showView("auth-view");
      showNotice(error.message, "error");
      return;
    }
    skipPartnerButton.disabled = false;
    callStatus.textContent = error.message || "Skip failed. Your call is being restored.";
    if (error.status === 429) {
      const retryAfter = error.data?.detail?.retry_after_seconds ?? 60;
      setSkipAvailability(0, retryAfter);
    }
  }
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
    const fallbackReady =
      Date.now() - matchingStartedAt >= matchingFallbackAfterSeconds * 1000;
    matchingTitle.textContent = result.fallback_available
      ? "Searching nearby English levels..."
      : fallbackReady
        ? "No alternative partner available yet"
        : "Searching for a partner...";
    matchingMessage.textContent = result.fallback_available
      ? "No same-level partner was ready, so we’re checking adjacent levels."
      : fallbackReady
        ? "No eligible alternative is available right now. We’ll keep searching and match you when one is ready."
        : `Looking for the same English level first. Nearby levels become available after ${matchingFallbackAfterSeconds} seconds.`;
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
  matchingStartedAt = Date.now();
  matchingFallbackAfterSeconds = 9;
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
    matchingStartedAt = Date.now();
    matchingFallbackAfterSeconds = result.fallback_after_seconds ?? 9;
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
