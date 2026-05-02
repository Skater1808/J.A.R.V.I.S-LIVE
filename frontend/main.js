// Jarvis V3 — Gemini Live Frontend
// Pure audio pipeline: mic PCM16 → WebSocket → server → Gemini Live → PCM24 → speaker

const orb      = document.getElementById('orb');
const statusEl = document.getElementById('status');
const transcEl = document.getElementById('transcript');

// ── Click Simulation ────────────────────────────────────────────────────
function simuliereKlickAnPosition(x, y) {
    const el = document.elementFromPoint(x, y);
    if (el) {
        el.click();
    }
}

// ── State ──────────────────────────────────────────────────────────────
let ws;
let micActive    = false;
let audioCtxIn   = null;   // 16 kHz  — for mic capture
let audioCtxOut  = null;   // 24 kHz  — for playback
let workletNode  = null;
let micStream    = null;
let nextPlayTime = 0;      // Scheduled playback cursor
let jarvisTalking = false;

// ── Voice Activity Detection ────────────────────────────────────────────
let lastVoiceTime = 0;
let silenceTimer  = null;
const SILENCE_THRESHOLD = 0.001;  // Energy threshold for voice detection (lower = more sensitive)
const SILENCE_DURATION  = 3000;   // 3 seconds of silence triggers response
let hasSpokenInTurn = false;        // Track if user spoke in current turn

// ── AudioWorklet (inline blob) ─────────────────────────────────────────
// Runs in the audio thread; converts float32 → int16 and posts chunks + energy.
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
    
    // Calculate energy for VAD
    let energy = 0;
    for (let i = 0; i < ch.length; i++) {
      energy += ch[i] * ch[i];
      this._buf.push(ch[i]);
    }
    energy = energy / ch.length;
    
    while (this._buf.length >= this._chunkSize) {
      const slice = this._buf.splice(0, this._chunkSize);
      const pcm   = new Int16Array(slice.length);
      for (let i = 0; i < slice.length; i++) {
        const clamped = Math.max(-1, Math.min(1, slice[i]));
        pcm[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
      }
      // Send both PCM data and energy
      this.port.postMessage({pcm: pcm.buffer, energy: energy}, [pcm.buffer]);
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
    // Create audio context on first chunk if needed (requires user gesture)
    if (!audioCtxOut) {
        console.error('[audio] Cannot play audio - no audio context! User must tap orb first to enable audio.');
        status('🔊 Tippe den Orb zuerst, um Audio zu aktivieren');
        return;
    }
    if (audioCtxOut.state === 'suspended') {
        console.log('[audio] Resuming suspended context...');
        audioCtxOut.resume().catch(e => console.error('[audio] Could not resume:', e));
    }

    const int16  = b64ToInt16(b64Data);
    if (int16.length === 0) {
        console.warn('[audio] Empty audio chunk received');
        return;
    }
    console.log(`[audio] Playing chunk: ${int16.length} samples`);

    const float32 = int16ToFloat32(int16);
    const buf     = audioCtxOut.createBuffer(1, float32.length, 24000);
    buf.getChannelData(0).set(float32);

    const src   = audioCtxOut.createBufferSource();
    src.buffer  = buf;
    src.connect(audioCtxOut.destination);

    // Schedule gaplessly
    const now   = audioCtxOut.currentTime;
    const start = Math.max(now + 0.04, nextPlayTime);
    try {
        src.start(start);
        nextPlayTime = start + buf.duration;
    } catch (e) {
        console.error('[audio] Error starting audio:', e);
    }

    jarvisTalking = true;
    setOrb('speaking');

    // Simulate click at position 160, 160 when Jarvis starts speaking
    simuliereKlickAnPosition(160, 160);
    console.log('[click] Simulated click at 160, 160');

    // Stop microphone when Jarvis speaks to prevent echo
    if (micActive) {
        stopMic();
        console.log('[mic] Auto-stopped because Jarvis is speaking');
    }
}

// ── Mic capture ───────────────────────────────────────────────────────────
async function startMic() {
    if (micActive) return;

    // iOS: AudioContext mit webkit prefix für ältere iOS Versionen
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    
    // Resume / create playback context (requires user gesture on iOS)
    if (!audioCtxOut) {
        audioCtxOut = new AudioContextClass({ sampleRate: 24000 });
    }
    
    // iOS: AudioContext muss explizit resumed werden nach User-Interaktion
    if (audioCtxOut.state === 'suspended') {
        await audioCtxOut.resume();
    }

    // Capture context at 16 kHz
    audioCtxIn  = new AudioContextClass({ sampleRate: 16000 });

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
        
        const { pcm, energy } = e.data;
        
        // Voice Activity Detection
        const hasVoice = energy > SILENCE_THRESHOLD;
        if (hasVoice) {
            lastVoiceTime = Date.now();
            if (!hasSpokenInTurn) {
                console.log('[vad] Voice detected');
                hasSpokenInTurn = true;
            }
            // Clear any pending silence timer
            if (silenceTimer) {
                clearTimeout(silenceTimer);
                silenceTimer = null;
            }
        }
        
        // Check if we should trigger turn complete after silence
        if (hasSpokenInTurn && !silenceTimer && !jarvisTalking) {
            const timeSinceVoice = Date.now() - lastVoiceTime;
            if (timeSinceVoice >= SILENCE_DURATION) {
                // 3s silence detected - stop mic like clicking orb
                console.log('[vad] 3s silence - stopping mic');
                status('⏱️ 3s Stille – Mikrofon pausiert');
                stopMic();
                setOrb('idle');
                hasSpokenInTurn = false;
            } else {
                // Set timer for remaining time
                const remaining = SILENCE_DURATION - timeSinceVoice;
                silenceTimer = setTimeout(() => {
                    if (ws && ws.readyState === WebSocket.OPEN && !jarvisTalking && hasSpokenInTurn) {
                        console.log('[vad] Timer fired - stopping mic');
                        status('⏱️ 3s Stille – Mikrofon pausiert');
                        stopMic();
                        setOrb('idle');
                        hasSpokenInTurn = false;
                    }
                    silenceTimer = null;
                }, remaining);
            }
        }
        
        // Don't send mic audio while Jarvis is still outputting to avoid echo
        if (jarvisTalking && nextPlayTime > audioCtxOut.currentTime + 0.2) return;
        ws.send(JSON.stringify({ type: 'audio', data: ab2b64(pcm) }));
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
    // Clear silence detection timer
    if (silenceTimer) {
        clearTimeout(silenceTimer);
        silenceTimer = null;
    }
    hasSpokenInTurn = false;
}

// ── WebSocket ─────────────────────────────────────────────────────────────
function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);

    ws.onopen = () => {
        console.log('[jarvis] WS verbunden');
        status('Klicke den Orb um Jarvis zu aktivieren (Audio erfordert Klick)');
        setOrb('idle');
    };

    ws.onmessage = (evt) => {
        const msg = JSON.parse(evt.data);

        switch (msg.type) {
            case 'audio':
                console.log(`[ws] Received audio chunk: ${msg.data?.length} chars`);
                scheduleChunk(msg.data);
                break;

            case 'turn_complete':
                // Jarvis finished speaking — small grace period then clear flag
                setTimeout(() => {
                    if (nextPlayTime <= (audioCtxOut?.currentTime ?? 0) + 0.15) {
                        jarvisTalking = false;
                        hasSpokenInTurn = false;  // Reset VAD for next turn
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
// iOS: Touch-Events sind schneller als Click
async function handleOrbInteraction(e) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
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
        status('Pausiert – tippe zum Fortsetzen');
    }
}

// Click für Desktop
orb.addEventListener('click', handleOrbInteraction);

// Touch-Events für iOS (schneller + prevent double-tap zoom)
orb.addEventListener('touchstart', handleOrbInteraction, { passive: false });

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
