const CANVAS_WIDTH = 400;
const CANVAS_HEIGHT = 240;
const WS_URL = 'ws://localhost:8000';

// Element references
const canvas = document.getElementById('screenCanvas');
const ctx = canvas.getContext('2d');
const btnConnect = document.getElementById('connectBtn');
const btnCast = document.getElementById('castBtn');
const btnCopyToDev = document.getElementById('copyToDevBtn');
const btnPasteFromDev = document.getElementById('pasteFromDevBtn');
const btnRefreshFiles = document.getElementById('refreshFilesBtn');
const uploadInput = document.getElementById('uploadInput');
const uploadPathInput = document.getElementById('uploadPath');
const fileList = document.getElementById('fileList');
const statusDot = document.getElementById('status-indicator');
const statusText = document.getElementById('status-text');
const fpsDisplay = document.getElementById('fpsCounter');
const netPassword = document.getElementById('netPassword');
const deviceIpInput = document.getElementById('deviceIp');

// Global State
let ws = null;
let isConnected = false;
let isCasting = false;
let frameCount = 0;
let lastTime = performance.now();
let pendingFileDownload = null;
let downloadSize = 0;
let receivedBytes = 0;
let downloadChunks = [];

// Image buffer (monochrome -> RGBA)
const imageData = ctx.createImageData(CANVAS_WIDTH, CANVAS_HEIGHT);
const buf32 = new Uint32Array(imageData.data.buffer);
const COLOR_BLACK = 0xFF000000;
const COLOR_WHITE = 0xFFFFFFFF;

/**
 * Update the UI status indicator and buttons based on connection state
 */
function updateStatus(state, msg) {
    statusText.textContent = msg;
    statusDot.className = 'status-dot w-2.5 h-2.5 rounded-full transition-all duration-300';

    if (state === 'connected') {
        statusDot.classList.add('bg-success');
        btnConnect.innerHTML = '<span class="font-headline font-bold text-[17px]">Disconnect Engine</span>';
        btnCast.disabled = false;
        isConnected = true;
    } else if (state === 'error') {
        statusDot.classList.add('bg-error');
        btnConnect.innerHTML = '<span class="font-headline font-bold text-[17px]">Connect Device</span>';
        btnCast.disabled = true;
        isConnected = false;
        resetCastState();
    } else if (state === 'connecting') {
        statusDot.classList.add('bg-outline', 'animate-pulse');
        btnConnect.innerHTML = '<span class="font-headline font-bold text-[17px]">Connecting...</span>';
        isConnected = false;
    } else {
        statusDot.classList.add('bg-outline');
        btnConnect.innerHTML = '<span class="font-headline font-bold text-[17px]">Connect Device</span>';
        btnCast.disabled = true;
        isConnected = false;
        resetCastState();
    }
}

function resetCastState() {
    isCasting = false;
    btnCast.innerHTML = '<span class="font-headline font-semibold text-[17px]">Enter Stream</span><span class="material-symbols-outlined text-[20px]">input</span>';
    btnCast.className = 'bg-surface-container-high text-on-surface h-[50px] rounded-full flex items-center justify-center gap-2 transition-active active:opacity-70 disabled:opacity-30';
}

function processFrame(data) {
    if (data.byteLength !== 12000) return;
    const u8 = new Uint8Array(data);
    let pixelIndex = 0;
    for (let i = 0; i < u8.length; i++) {
        const byte = u8[i];
        for (let b = 0; b < 8; b++) {
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

function updateFileList(listStr) {
    fileList.innerHTML = '';
    if (!listStr) {
        fileList.innerHTML = '<div class="p-8 text-center opacity-30"><p class="font-label text-[10px] uppercase tracking-widest">No Active Manuscripts</p></div>';
        return;
    }
    const files = listStr.split(',').reverse();
    files.forEach(file => {
        if (!file.trim()) return;
        const fullpath = file.trim();
        const filename = fullpath.split('/').pop();
        const item = document.createElement('div');
        item.className = 'ios-list-item p-4 flex justify-between items-center active:bg-black/5 cursor-pointer group';
        item.onclick = () => { if (isConnected) ws.send(`get_file:${fullpath}`); };
        item.innerHTML = `<div class="flex items-center gap-3"><span class="font-headline italic text-[17px] filename-label">${filename}</span></div><span class="material-symbols-outlined text-outline text-[16px]">download</span>`;
        fileList.appendChild(item);
    });
}

function saveDownloadedFile() {
    if (!pendingFileDownload) return;
    const blob = new Blob(downloadChunks);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = pendingFileDownload.split('/').pop();
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    pendingFileDownload = null;
    downloadChunks = [];
}

// Initialization: Load saved credentials
const savedIp = localStorage.getItem('deck_ip');
const savedPass = localStorage.getItem('deck_pass');
if (savedIp) deviceIpInput.value = savedIp;
if (savedPass) netPassword.value = savedPass;

function connect() {
    if (ws) {
        ws.close();
        ws = null;
        updateStatus('disconnected', 'Engine Idle');
        return;
    }

    const ip = deviceIpInput.value.trim();
    const pass = netPassword.value.trim();
    if (!ip) { alert("Please enter a device IP address."); return; }

    // Save for next session
    localStorage.setItem('deck_ip', ip);
    localStorage.setItem('deck_pass', pass);

    updateStatus('connecting', 'Locating Engine...');
    try {
        ws = new WebSocket(WS_URL);
        ws.binaryType = 'arraybuffer';
        ws.onopen = () => ws.send(`target_ip:${ip}`);
        ws.onmessage = (event) => {
            if (event.data instanceof ArrayBuffer) {
                if (pendingFileDownload) {
                    downloadChunks.push(new Uint8Array(event.data));
                    receivedBytes += event.data.byteLength;
                    if (receivedBytes >= downloadSize) saveDownloadedFile();
                } else {
                    processFrame(event.data);
                    if (isCasting) requestFrame();
                }
            } else {
                const msg = event.data;
                if (msg === "connect_success") {
                    ws.send(`auth:${pass || "password"}`);
                } else if (msg.startsWith("connect_failed:")) {
                    alert("Connection failed: " + msg.substring(15));
                    ws.close();
                } else if (msg === "auth_success") {
                    updateStatus('connected', 'Engine Synchronized');
                    ws.send("get_file_list");
                } else if (msg.startsWith("auth_failed:")) {
                    alert("Authorization failed.");
                    ws.close();
                } else if (msg === "file_put_success") {
                    alert("File successfully injected onto the device!");
                    ws.send("get_file_list");
                } else if (msg.startsWith("file_list:")) {
                    updateFileList(msg.substring(10));
                } else if (msg.startsWith("clipboard_data:")) {
                    navigator.clipboard.writeText(msg.substring(15));
                    alert("Clipboard synchronized:" + msg.substring(15));
                } else if (msg.startsWith("file_start:")) {
                    const parts = msg.split(':');
                    pendingFileDownload = parts[1];
                    downloadSize = parseInt(parts[2]);
                    receivedBytes = 0;
                    downloadChunks = [];
                    if (downloadSize === 0) saveDownloadedFile();
                } else if (msg.startsWith("ERROR:")) {
                    console.error("Proxy error:", msg);
                }
            }
        };
        ws.onclose = () => { isConnected = false; updateStatus('disconnected', 'Engine Idle'); ws = null; };
        ws.onerror = () => updateStatus('error', 'Synchronization Failed');
    } catch (e) { updateStatus('error', 'Critical Error'); }
}

btnConnect.addEventListener('click', connect);

btnCast.addEventListener('click', () => {
    if (!isConnected) return;
    if (isCasting) {
        isCasting = false;
        resetCastState();
        startScreensaver();
    } else {
        stopScreensaver();
        isCasting = true;
        requestFrame();
        btnCast.innerHTML = '<span class="font-headline font-semibold text-[17px]">Terminate Stream</span>';
        btnCast.className = 'bg-primary text-on-primary h-[50px] rounded-full flex items-center justify-center gap-2 transition-active active:opacity-70';
    }
});

btnCopyToDev.addEventListener('click', () => {
    if (isConnected) navigator.clipboard.readText().then(t => { if (t) ws.send("put_clipboard:" + t); });
});

btnPasteFromDev.addEventListener('click', () => {
    if (isConnected) ws.send("get_clipboard");
});

btnRefreshFiles.addEventListener('click', () => {
    if (isConnected) ws.send("get_file_list");
});

uploadInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file || !isConnected) return;
    const reader = new FileReader();
    reader.onload = (event) => {
        const destPath = uploadPathInput.value.trim() || "/tmp/";
        const fullpath = destPath.endsWith('/') ? destPath + file.name : destPath + "/" + file.name;
        const prefix = new TextEncoder().encode("put_file:" + fullpath + "\0");
        const combined = new Uint8Array(prefix.length + event.target.result.byteLength);
        combined.set(prefix);
        combined.set(new Uint8Array(event.target.result), prefix.length);
        ws.send(combined);
    };
    reader.readAsArrayBuffer(file);
});

// Retro Screensaver logic
let screensaverId = null;
const particles = [];
const NUM_PARTICLES = 40;
const G_FORCE = 0.05;

class Particle {
    constructor() { this.reset(); }
    reset() {
        this.x = Math.random() * CANVAS_WIDTH;
        this.y = Math.random() * CANVAS_HEIGHT;
        this.vx = (Math.random() - 0.5) * 1;
        this.vy = (Math.random() - 0.5) * 1;
        this.mass = Math.random() * 10 + 1;
        this.life = 0;
    }
    update(allParticles) {
        this.life++;
        for (const other of allParticles) {
            if (other === this) continue;
            const dx = other.x - this.x;
            const dy = other.y - this.y;
            const distSq = dx * dx + dy * dy;
            if (distSq > 1 && distSq < 15000) {
                const dist = Math.sqrt(distSq);
                let force = (dist < 30) ? 0 : (G_FORCE * this.mass * other.mass) / distSq;
                if (dist < 30) {
                    let boost = (this.life & 0x100) ? 3 : 1;
                    this.vx += (Math.random() - 0.5) * 0.6 / dist * boost;
                    this.vy += (Math.random() - 0.5) * 0.6 / dist * boost;
                }
                const ax = (dx / dist) * force;
                const ay = (dy / dist) * force;
                this.vx += ax; this.vy += ay;
            }
        }
        this.x += this.vx; this.y += this.vy;
        if (this.x < 0) this.x = CANVAS_WIDTH; if (this.x > CANVAS_WIDTH) this.x = 0;
        if (this.y < 0) this.y = CANVAS_HEIGHT; if (this.y > CANVAS_HEIGHT) this.y = 0;
        this.vx *= 0.99; this.vy *= 0.99;
    }
    draw(ctx) {
        const px = Math.floor(this.x);
        const py = Math.floor(this.y);
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(px, py, 1, 1);
        if (this.mass > 7) {
            ctx.fillRect(px + 1, py, 1, 1);
            ctx.fillRect(px, py + 1, 1, 1);
            ctx.fillRect(px + 1, py + 1, 1, 1);
        }
    }
}

function animateScreensaver() {
    if (isCasting) return;
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    particles.forEach(p => { p.update(particles); p.draw(ctx); });
    screensaverId = requestAnimationFrame(animateScreensaver);
}

function startScreensaver() {
    if (!screensaverId && !isCasting) {
        particles.length = 0;
        for (let i = 0; i < NUM_PARTICLES; i++) particles.push(new Particle());
        animateScreensaver();
    }
}

function stopScreensaver() {
    if (screensaverId) {
        cancelAnimationFrame(screensaverId);
        screensaverId = null;
        ctx.fillStyle = '#000000';
        ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    }
}

// Initialization
startScreensaver();
