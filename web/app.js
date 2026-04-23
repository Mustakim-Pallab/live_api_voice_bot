const connectBtn = document.getElementById("connectBtn");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const sendBtn = document.getElementById("sendBtn");
const textInput = document.getElementById("textInput");
const statusPill = document.getElementById("status");
const logEl = document.getElementById("log");

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

function setStatus(message) {
  statusPill.textContent = message;
}

function appendLog(message) {
  logEl.textContent += `${new Date().toLocaleTimeString()} | ${message}\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

function logEnvironmentHints() {
  if (!window.isSecureContext) {
    appendLog("Mic blocked: insecure context. Open with http://localhost:<port> (not LAN IP/0.0.0.0).");
  }
  if (!isMicSupported()) {
    appendLog("Mic API unavailable in this browser/context.");
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
    playbackContext.resume().catch(() => {});
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

async function connect() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    return;
  }

  socket = new WebSocket(getWsUrl());
  setStatus("Connecting...");

  socket.addEventListener("open", () => {
    appendLog("WebSocket connected");
    setStatus("Connected");
    startBtn.disabled = false;
    sendBtn.disabled = false;

    clearPingTimer();
    pingTimer = setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "ping" }));
      }
    }, 15000);
  });

  socket.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === "ready") {
      appendLog("Gemini Live session ready");
    } else if (msg.type === "text") {
      appendLog(`Assistant: ${msg.text}`);
    } else if (msg.type === "input_transcript") {
      appendLog(`You said: ${msg.text}`);
    } else if (msg.type === "output_transcript") {
      appendLog(`Assistant transcript: ${msg.text}`);
    } else if (msg.type === "audio_out") {
      playPcmChunk(msg.pcm16, msg.sample_rate || 24000);
    } else if (msg.type === "turn_complete") {
      appendLog(`Turn complete (${msg.reason || "unspecified"})`);
    } else if (msg.type === "interrupted") {
      appendLog("Bot was interrupted");
      nextPlayAt = 0;
      if (playbackContext) {
        playbackContext.close().catch(() => {});
        playbackContext = null;
      }
    } else if (msg.type === "error") {
      appendLog(`Error: ${msg.message}`);
    }
  });

  socket.addEventListener("close", () => {
    appendLog("WebSocket closed");
    clearPingTimer();
    setStatus("Disconnected");
    startBtn.disabled = true;
    stopBtn.disabled = true;
    sendBtn.disabled = true;
    streaming = false;
  });

  socket.addEventListener("error", () => {
    clearPingTimer();
    appendLog("WebSocket error");
    setStatus("Error");
  });
}

async function startStreaming() {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    appendLog("Connect first");
    return;
  }

  if (streaming) {
    return;
  }

  if (!isMicSupported()) {
    appendLog("Error: getUserMedia not available. Use Chrome/Edge/Firefox on localhost or HTTPS.");
    return;
  }

  if (!window.isSecureContext) {
    appendLog("Error: microphone requires a secure context. Use http://localhost:7860.");
    return;
  }

  try {
    if (navigator.permissions && navigator.permissions.query) {
      try {
        const micPermission = await navigator.permissions.query({ name: "microphone" });
        appendLog(`Mic permission state: ${micPermission.state}`);
      } catch (_) {
        // Permissions API is optional across browsers.
      }
    }

    if (!playbackContext) {
      playbackContext = new AudioContext();
    }
    if (playbackContext.state === "suspended") {
      await playbackContext.resume();
    }

    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    captureContext = new AudioContext({ sampleRate: 48000 });
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
    startBtn.disabled = true;
    stopBtn.disabled = false;
    setStatus("Streaming mic");
    appendLog("Started microphone streaming");
    appendLog("Tip: Gemini handles turn detection automatically; speak naturally.");
  } catch (error) {
    appendLog("Microphone access error: " + error.message);
    console.error("Microphone access error", error);
  }
}

async function stopStreaming() {
  if (!streaming) {
    return;
  }

  streaming = false;
  startBtn.disabled = false;
  stopBtn.disabled = true;

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

  setStatus("Connected");
  appendLog("Stopped microphone streaming");
}

function sendText() {
  const text = textInput.value.trim();
  if (!text || !socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }
  socket.send(JSON.stringify({ type: "text", text }));
  appendLog(`You typed: ${text}`);
  textInput.value = "";
}

connectBtn.addEventListener("click", connect);
startBtn.addEventListener("click", startStreaming);
stopBtn.addEventListener("click", stopStreaming);
sendBtn.addEventListener("click", sendText);
textInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    sendText();
  }
});

logEnvironmentHints();
