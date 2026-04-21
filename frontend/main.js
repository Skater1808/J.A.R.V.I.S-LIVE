// Jarvis V3 — Gemini Live Frontend
// Pure audio pipeline: mic PCM16 → WebSocket → server → Gemini Live → PCM24 → speaker

const orb      = document.getElementById('orb');
const statusEl = document.getElementById('status');
const transcEl = document.getElementById('transcript');

// ── State ──────────────────────────────────────────────────────────────
let ws;
let micActive    = false;
let audioCtxIn   = null;   // 16 kHz  — for mic capture
let audioCtxOut  = null;   // 24 kHz  — for playback
let workletNode  = null;
let micStream    = null;
let nextPlayTime = 0;      // Scheduled playback cursor
let jarvisTalking = false;

// ── AudioWorklet (inline blob) ─────────────────────────────────────────
// Runs in the audio thread; converts float32 → int16 and posts chunks.
const WORKLET_CODE = `
class CaptureProcessor extends AudioWorkletProcessor {
  constructor () {
    super();
    this._buf = [];
    this._chunkSize = 2048; // samples per chunk  (~128 ms at 16 kHz)
  }
  process (inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) this._buf.push(ch[i]);
    while (this._buf.length >= this._chunkSize) {
      const slice = this._buf.splice(0, this._chunkSize);
      const pcm   = new Int16Array(slice.length);
      for (let i = 0; i < slice.length; i++) {
        const clamped = Math.max(-1, Math.min(1, slice[i]));
        pcm[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor('capture-processor', CaptureProcessor);
`;

// ── Helpers ─────────────────────────────────────────────────────────────
function b64ToInt16(b64) {
    const bin   = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Int16Array(bytes.buffer);
}

function int16ToFloat32(buf) {
    const out = new Float32Array(buf.length);
    for (let i = 0; i < buf.length; i++) out[i] = buf[i] / 32768;
    return out;
}

function ab2b64(ab) {
    const bytes  = new Uint8Array(ab);
    let   binary = '';
    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
}

// ── Playback ─────────────────────────────────────────────────────────────
function scheduleChunk(b64Data) {
    if (!audioCtxOut) return;

    const int16  = b64ToInt16(b64Data);
    if (int16.length === 0) return;

    const float32 = int16ToFloat32(int16);
    const buf     = audioCtxOut.createBuffer(1, float32.length, 24000);
    buf.getChannelData(0).set(float32);

    const src   = audioCtxOut.createBufferSource();
    src.buffer  = buf;
    src.connect(audioCtxOut.destination);

    // Schedule gaplessly
    const now   = audioCtxOut.currentTime;
    const start = Math.max(now + 0.04, nextPlayTime);
    src.start(start);
    nextPlayTime = start + buf.duration;

    jarvisTalking = true;
    setOrb('speaking');
}

// ── Mic capture ───────────────────────────────────────────────────────────
async function startMic() {
    if (micActive) return;

    // Resume / create playback context (requires user gesture)
    if (!audioCtxOut) {
        audioCtxOut = new AudioContext({ sampleRate: 24000 });
    }
    if (audioCtxOut.state === 'suspended') await audioCtxOut.resume();

    // Capture context at 16 kHz
    audioCtxIn  = new AudioContext({ sampleRate: 16000 });

    // Build inline worklet
    const blob  = new Blob([WORKLET_CODE], { type: 'application/javascript' });
    const burl  = URL.createObjectURL(blob);
    await audioCtxIn.audioWorklet.addModule(burl);
    URL.revokeObjectURL(burl);

    micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount:     1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl:  true,
        }
    });

    const src    = audioCtxIn.createMediaStreamSource(micStream);
    workletNode  = new AudioWorkletNode(audioCtxIn, 'capture-processor');

    workletNode.port.onmessage = (e) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        // Don't send mic audio while Jarvis is still outputting to avoid echo
        if (jarvisTalking && nextPlayTime > audioCtxOut.currentTime + 0.2) return;
        ws.send(JSON.stringify({ type: 'audio', data: ab2b64(e.data) }));
    };

    src.connect(workletNode);
    // Don't connect to destination — no mic feedback
    micActive = true;
    setOrb('listening');
    status('Ich hoere zu...');
}

function stopMic() {
    if (!micActive) return;
    workletNode?.disconnect();
    workletNode = null;
    if (micStream) {
        micStream.getTracks().forEach(t => t.stop());
        micStream = null;
    }
    audioCtxIn?.close();
    audioCtxIn = null;
    micActive  = false;
}

// ── WebSocket ─────────────────────────────────────────────────────────────
function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);

    ws.onopen = () => {
        console.log('[jarvis] WS verbunden');
        status('Klicke den Orb um Jarvis zu aktivieren');
        setOrb('idle');
    };

    ws.onmessage = (evt) => {
        const msg = JSON.parse(evt.data);

        switch (msg.type) {
            case 'audio':
                scheduleChunk(msg.data);
                break;

            case 'transcript':
                addLine('jarvis', msg.text);
                break;

            case 'turn_complete':
                // Jarvis finished speaking — small grace period then clear flag
                setTimeout(() => {
                    if (nextPlayTime <= (audioCtxOut?.currentTime ?? 0) + 0.15) {
                        jarvisTalking = false;
                        if (micActive) setOrb('listening');
                    }
                }, 400);
                break;

            case 'interrupted':
                // User interrupted Jarvis — stop queued audio immediately
                nextPlayTime  = audioCtxOut?.currentTime ?? 0;
                jarvisTalking = false;
                break;

            case 'status':
                status(msg.text);
                break;

            case 'error':
                status('Fehler: ' + msg.text);
                setOrb('idle');
                break;
        }
    };

    ws.onclose = () => {
        status('Verbindung getrennt – reconnect...');
        setOrb('idle');
        stopMic();
        setTimeout(connect, 3000);
    };

    ws.onerror = (e) => console.error('[jarvis] WS Fehler', e);
}

// ── Orb click — toggle mic ────────────────────────────────────────────────
orb.addEventListener('click', async () => {
    if (!micActive) {
        try {
            status('Mikrofon wird gestartet...');
            await startMic();
        } catch (err) {
            status('Mikrofon-Zugriff verweigert: ' + err.message);
            console.error(err);
        }
    } else {
        stopMic();
        setOrb('idle');
        status('Pausiert – klicke zum Fortsetzen');
    }
});

// ── UI helpers ────────────────────────────────────────────────────────────
function setOrb(state)  { orb.className = state; }
function status(txt)    { statusEl.textContent = txt; }

function addLine(role, text) {
    const d = document.createElement('div');
    d.className   = role;
    d.textContent = role === 'user' ? `Du: ${text}` : `Jarvis: ${text}`;
    transcEl.appendChild(d);
    transcEl.scrollTop = transcEl.scrollHeight;
    // Keep at most 40 lines
    while (transcEl.children.length > 40) transcEl.removeChild(transcEl.firstChild);
}

// ── Boot ──────────────────────────────────────────────────────────────────
connect();