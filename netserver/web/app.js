const CANVAS_WIDTH = 400;
const CANVAS_HEIGHT = 240;
const WS_URL = 'ws://localhost:8000';

const canvas = document.getElementById('screenCanvas');
const ctx = canvas.getContext('2d');
const btnConnect = document.getElementById('connectBtn');
const btnCast = document.getElementById('castBtn');
const btnCopyToDev = document.getElementById('copyToDevBtn');
const btnPasteFromDev = document.getElementById('pasteFromDevBtn');
const statusDot = document.getElementById('status-indicator');
const statusText = document.getElementById('status-text');
const fpsDisplay = document.getElementById('fpsCounter');

// Image buffer (monochrome -> RGBA)
const imageData = ctx.createImageData(CANVAS_WIDTH, CANVAS_HEIGHT);
// 32-bit view for faster pixel manipulation (0xAABBGGRR in little-endian)
const buf32 = new Uint32Array(imageData.data.buffer);

let ws = null;
let isConnected = false;
let isCasting = false;
let frameCount = 0;
let lastTime = performance.now();
let requestAnimationFrameId = null;

// Colors
const COLOR_BLACK = 0xFF000000; // Opaque Black
const COLOR_WHITE = 0xFFFFFFFF; // Opaque White

function updateStatus(state, msg) {
    statusText.textContent = msg;
    statusDot.className = 'status-dot'; // reset
    if (state === 'connected') {
        statusDot.classList.add('connected');
        btnConnect.textContent = 'Disconnect';
        btnCast.disabled = false;
    } else if (state === 'error') {
        statusDot.classList.add('error');
        btnConnect.textContent = 'Connect';
        btnCast.disabled = true;
        resetCastState();
    } else {
        btnConnect.textContent = 'Connect';
        btnCast.disabled = true;
        resetCastState();
    }
}

function resetCastState() {
    isCasting = false;
    btnCast.textContent = "Start Cast";
    btnCast.classList.remove('primary');
    btnCast.classList.add('secondary');
}

function processFrame(data) {
    if (data.byteLength !== 12000) {
        console.warn(`Got weird size: ${data.byteLength}`);
        return; // Ignore invalid packets
    }

    const u8 = new Uint8Array(data);
    let pixelIndex = 0;

    for (let i = 0; i < u8.length; i++) {
        const byte = u8[i];
        // Unpack 8 bits from the byte
        for (let b = 0; b < 8; b++) {
            // Check bit (MSB first)
            const isWhite = (byte & (1 << (7 - b))) !== 0;
            buf32[pixelIndex++] = isWhite ? COLOR_WHITE : COLOR_BLACK;
        }
    }

    ctx.putImageData(imageData, 0, 0);

    frameCount++;
    const now = performance.now();
    if (now - lastTime >= 1000) {
        fpsDisplay.textContent = Math.round((frameCount * 1000) / (now - lastTime));
        frameCount = 0;
        lastTime = now;
    }
}

function requestFrame() {
    if (ws && ws.readyState === WebSocket.OPEN && isCasting) {
        ws.send("send_screen");
    }
}

function connect() {
    if (isConnected) {
        ws.close();
        return;
    }

    updateStatus('connecting', 'Connecting...');

    try {
        ws = new WebSocket(WS_URL);
        ws.binaryType = 'arraybuffer'; // Important!

        ws.onopen = () => {
            isConnected = true;
            updateStatus('connected', 'Connected');
            // Do NOT start casting automatically
        };

        ws.onmessage = (event) => {
            if (event.data instanceof ArrayBuffer) {
                processFrame(event.data);
                // Immediately request next frame for max FPS
                if (isCasting) requestFrame();
            } else {
                const msg = event.data;
                if (typeof msg === 'string' && msg.startsWith('clipboard_data:')) {
                    const content = msg.substring('clipboard_data:'.length);
                    // Copy to local clipboard
                    navigator.clipboard.writeText(content).then(() => {
                        console.log('Clipboard updated from device');
                        alert("Clipboard received from device: \n" + content);
                    }).catch(err => {
                        console.error('Failed to write clipboard', err);
                        alert("Failed to write to clipboard. See console.");
                    });
                } else {
                    console.log("Text message:", event.data);
                }
            }
        };

        ws.onclose = () => {
            isConnected = false;
            updateStatus('disconnected', 'Disconnected');
            ws = null;
        };

        ws.onerror = (err) => {
            console.error("WebSocket error", err);
            updateStatus('error', 'Connection Failed');
        };

    } catch (e) {
        console.error(e);
        updateStatus('error', 'Error');
    }
}

btnConnect.addEventListener('click', connect);

// Screensaver State
let screensaverId = null;
const particles = [];
const NUM_PARTICLES = 40;
const G_FORCE = 0.05;

class Particle {
    constructor() {
        this.reset();
    }

    reset() {
        this.x = Math.random() * CANVAS_WIDTH;
        this.y = Math.random() * CANVAS_HEIGHT;
        this.vx = (Math.random() - 0.5) * 1;
        this.vy = (Math.random() - 0.5) * 1;
        this.mass = Math.random() * 10 + 1;
        this.life = 0;
    }

    update(allParticles) {
        // N-body physics
        this.life++;
        for (const other of allParticles) {
            if (other === this) continue;

            const dx = other.x - this.x;
            const dy = other.y - this.y;
            const distSq = dx * dx + dy * dy;

            // Interaction range
            if (distSq > 1 && distSq < 15000) {
                const dist = Math.sqrt(distSq);
                let force = 0;

                if (dist < 30) {
                    let boost = 1;
                    if (this.life & 0x1000 != 0)
                        boost = 3;
                    this.vx += (Math.random() - 0.5) * 0.6 / dist * boost;
                    this.vy += (Math.random() - 0.5) * 0.6 / dist * boost;
                }
                // Attraction (Gravity)
                else {
                    force = (G_FORCE * this.mass * other.mass) / distSq;
                }

                const ax = (dx / dist) * force;
                const ay = (dy / dist) * force;

                this.vx += ax;
                this.vy += ay;
            }
        }

        this.x += this.vx;
        this.y += this.vy;

        // Wrap around edges (Toroidal space)
        if (this.x < 0) this.x = CANVAS_WIDTH;
        if (this.x > CANVAS_WIDTH) this.x = 0;
        if (this.y < 0) this.y = CANVAS_HEIGHT;
        if (this.y > CANVAS_HEIGHT) this.y = 0;

        // Drag/Friction to stabilize
        this.vx *= 0.99;
        this.vy *= 0.99;
    }

    draw(ctx) {
        // Draw as single white pixel
        // Round position to snap to pixel grid for 8-bit look
        const px = Math.floor(this.x);
        const py = Math.floor(this.y);
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(px, py, 1, 1);

        // Optional: Draw slightly larger for "heavier" stars
        if (this.mass > 7) {
            ctx.fillRect(px + 1, py, 1, 1);
            ctx.fillRect(px, py + 1, 1, 1);
            ctx.fillRect(px + 1, py + 1, 1, 1);
        }
    }
}

function initScreensaver() {
    particles.length = 0;
    for (let i = 0; i < NUM_PARTICLES; i++) {
        particles.push(new Particle());
    }
    animateScreensaver();
}

function animateScreensaver() {
    if (isCasting) return; // Stop if casting started

    // Clear hard black (no trails for crisp 1-bit look)
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

    // Update all
    particles.forEach(p => {
        p.update(particles);
    });

    // Draw all
    particles.forEach(p => {
        p.draw(ctx);
    });

    screensaverId = requestAnimationFrame(animateScreensaver);
}

function startScreensaver() {
    if (!screensaverId && !isCasting) {
        initScreensaver();
    }
}

function stopScreensaver() {
    if (screensaverId) {
        cancelAnimationFrame(screensaverId);
        screensaverId = null;
        // Clean clear for casting
        ctx.fillStyle = '#000000';
        ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    }
}


btnCast.addEventListener('click', () => {
    if (!ws || !isConnected) return;

    if (isCasting) {
        isCasting = false;
        btnCast.textContent = "Start Cast";
        btnCast.classList.remove('primary');
        btnCast.classList.add('secondary');
        startScreensaver();
    } else {
        stopScreensaver();
        isCasting = true;
        requestFrame();
        btnCast.textContent = "Stop Cast";
        btnCast.classList.remove('secondary');
        btnCast.classList.add('primary');
    }
});

// Start initially
startScreensaver();

btnCopyToDev.addEventListener('click', () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert("Not connected to device.");
        return;
    }

    navigator.clipboard.readText().then(text => {
        if (text) {
            ws.send("put_clipboard:" + text);
            console.log("Sent clipboard to device");
        } else {
            console.log("Clipboard is empty");
        }
    }).catch(err => {
        console.error('Failed to read clipboard', err);
        alert("Failed to read clipboard. Check permissions.");
    });
});

btnPasteFromDev.addEventListener('click', () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert("Not connected to device.");
        return;
    }
    ws.send("get_clipboard");
});
