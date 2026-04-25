const callBtn = document.getElementById("callBtn");
const callBtnText = document.getElementById("callBtnText");
const sendBtn = document.getElementById("sendBtn");
const textInput = document.getElementById("textInput");
const statusDot = document.getElementById("statusDot");
const chatWindow = document.getElementById("chatWindow");

const INPUT_RATE = 16000;
let socket = null;
let captureContext = null;
let playbackContext = null;
let mediaStream = null;
let processorNode = null;
let sourceNode = null;
let streaming = false;
let nextPlayAt = 0;
let pingTimer = null;

function isMicSupported() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

let activeUserMsg = null;
let activeBotMsg = null;

function addMessage(text, type = "system") {
  const div = document.createElement("div");
  div.className = `message ${type}`;
  div.textContent = text;
  chatWindow.appendChild(div);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return div;
}

function logEnvironmentHints() {
  if (!window.isSecureContext) {
    addMessage("Mic blocked: insecure context. Open with http://localhost:<port>.", "system");
  }
  if (!isMicSupported()) {
    addMessage("Mic API unavailable in this browser/context.", "system");
  }
}

function clearPingTimer() {
  if (pingTimer) {
    clearInterval(pingTimer);
    pingTimer = null;
  }
}

function getWsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/ws/live`;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
}

function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

function downsampleTo16k(float32Buffer, inSampleRate) {
  if (inSampleRate === INPUT_RATE) {
    return float32Buffer;
  }
  const ratio = inSampleRate / INPUT_RATE;
  const newLength = Math.round(float32Buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;

  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < float32Buffer.length; i += 1) {
      accum += float32Buffer[i];
      count += 1;
    }
    result[offsetResult] = count > 0 ? accum / count : 0;
    offsetResult += 1;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function floatTo16BitPCM(float32Buffer) {
  const output = new Int16Array(float32Buffer.length);
  for (let i = 0; i < float32Buffer.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, float32Buffer[i]));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function pcm16ToAudioBuffer(arrayBuffer, sampleRate) {
  const pcm = new Int16Array(arrayBuffer);
  const buffer = playbackContext.createBuffer(1, pcm.length, sampleRate);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < pcm.length; i += 1) {
    channel[i] = pcm[i] / 0x8000;
  }
  return buffer;
}

function playPcmChunk(base64Pcm, sampleRate = 24000) {
  if (!playbackContext) {
    playbackContext = new AudioContext();
  }

  if (playbackContext.state === "suspended") {
    playbackContext.resume().catch(() => { });
  }

  const audioBuffer = pcm16ToAudioBuffer(base64ToArrayBuffer(base64Pcm), sampleRate);
  const source = playbackContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(playbackContext.destination);

  const now = playbackContext.currentTime;
  if (nextPlayAt < now) {
    nextPlayAt = now + 0.03;
  }
  source.start(nextPlayAt);
  nextPlayAt += audioBuffer.duration;
}

function setCallState(state) {
  if (state === "connecting") {
    callBtn.disabled = true;
    callBtnText.textContent = "Connecting...";
    statusDot.classList.remove("active");
  } else if (state === "connected") {
    callBtn.disabled = false;
    callBtn.classList.add("danger");
    callBtnText.textContent = "Stop Talking";
    statusDot.classList.add("active");
    textInput.disabled = false;
    sendBtn.disabled = false;
  } else {
    callBtn.disabled = false;
    callBtn.classList.remove("danger");
    callBtnText.textContent = "Start Talking";
    statusDot.classList.remove("active");
    textInput.disabled = true;
    sendBtn.disabled = true;
    clearPingTimer();
    activeUserMsg = null;
    activeBotMsg = null;
  }
}

async function startCall() {
  if (!isMicSupported()) {
    addMessage("Error: getUserMedia not available. Use Chrome/Edge/Firefox on localhost or HTTPS.", "system");
    return;
  }

  // Request microphone IMMEDIATELY during user gesture
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    addMessage("Microphone permission denied or error: " + err.message, "system");
    setCallState("disconnected");
    return;
  }

  // Clear welcome message
  chatWindow.innerHTML = "";

  setCallState("connecting");

  socket = new WebSocket(getWsUrl());

  socket.addEventListener("open", async () => {
    addMessage("Connected to server.", "system");
    setCallState("connected");

    clearPingTimer();
    pingTimer = setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "ping" }));
      }
    }, 15000);

    await startStreaming();
  });

  socket.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === "ready") {
      addMessage("Gemini Live session ready! Start speaking.", "system");
    } else if (msg.type === "text" || msg.type === "output_transcript") {
      if (!activeBotMsg) {
        activeBotMsg = addMessage("", "bot");
      }
      activeBotMsg.textContent += msg.text;
      chatWindow.scrollTop = chatWindow.scrollHeight;
    } else if (msg.type === "input_transcript") {
      if (!activeUserMsg) {
        activeUserMsg = addMessage("", "user");
      }
      activeUserMsg.textContent += msg.text;
      chatWindow.scrollTop = chatWindow.scrollHeight;
    } else if (msg.type === "audio_out") {
      playPcmChunk(msg.pcm16, msg.sample_rate || 24000);
    } else if (msg.type === "turn_complete") {
      activeUserMsg = null;
      activeBotMsg = null;
    } else if (msg.type === "interrupted") {
      nextPlayAt = 0;
      if (playbackContext) {
        playbackContext.close().catch(() => { });
        playbackContext = null;
      }
    } else if (msg.type === "error") {
      addMessage(`Error: ${msg.message}`, "system");
    }
  });

  socket.addEventListener("close", () => {
    disconnect();
  });

  socket.addEventListener("error", () => {
    addMessage("WebSocket error", "system");
    disconnect();
  });
}

async function startStreaming() {
  try {

    if (navigator.permissions && navigator.permissions.query) {
      try {
        await navigator.permissions.query({ name: "microphone" });
      } catch (_) { }
    }
    if (!playbackContext) {
      playbackContext = new AudioContext();
    }
    if (playbackContext.state === "suspended") {
      await playbackContext.resume();
    }

    if (!mediaStream) {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }
    captureContext = new AudioContext();
    if (captureContext.state === "suspended") {
      await captureContext.resume();
    }
    sourceNode = captureContext.createMediaStreamSource(mediaStream);
    processorNode = captureContext.createScriptProcessor(4096, 1, 1);

    processorNode.onaudioprocess = (event) => {
      if (!streaming || !socket || socket.readyState !== WebSocket.OPEN) {
        return;
      }
      const input = event.inputBuffer.getChannelData(0);
      const downsampled = downsampleTo16k(input, captureContext.sampleRate);
      const pcm16 = floatTo16BitPCM(downsampled);

      socket.send(
        JSON.stringify({
          type: "audio_in",
          pcm16: arrayBufferToBase64(pcm16.buffer),
        }),
      );
    };

    sourceNode.connect(processorNode);
    processorNode.connect(captureContext.destination);

    streaming = true;
    addMessage("Microphone streaming started. You can talk now.", "system");
  } catch (error) {
    addMessage("Microphone access error: " + error.message, "system");
    console.error("Microphone access error", error);
    disconnect();
  }
}

async function stopStreaming() {
  streaming = false;

  if (processorNode) {
    processorNode.disconnect();
    processorNode.onaudioprocess = null;
  }
  if (sourceNode) {
    sourceNode.disconnect();
  }
  if (captureContext) {
    await captureContext.close();
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
  }

  processorNode = null;
  sourceNode = null;
  captureContext = null;
  mediaStream = null;

  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "audio_stream_end" }));
  }
}

async function disconnect() {
  await stopStreaming();
  if (socket) {
    socket.close();
    socket = null;
  }

  // Immediately stop any currently playing or buffered audio
  nextPlayAt = 0;
  if (playbackContext) {
    playbackContext.close().catch(() => { });
    playbackContext = null;
  }

  setCallState("disconnected");
  addMessage("Call disconnected.", "system");
}

function sendText() {
  const text = textInput.value.trim();
  if (!text || !socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }
  socket.send(JSON.stringify({ type: "text", text }));
  addMessage(text, "user");
  textInput.value = "";
}

callBtn.addEventListener("click", () => {
  if (socket && socket.readyState !== WebSocket.CLOSED) {
    disconnect();
  } else {
    startCall();
  }
});

sendBtn.addEventListener("click", sendText);

textInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    sendText();
  }
});

logEnvironmentHints();
