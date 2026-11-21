// VM 안에서 도는 측정기. 네트워크를 빼고 서버 쪽 성능만 잽니다.
// usage: node bench.js <deviceId> <adbSerial> [taps] [jb]
const { spawn } = require('child_process');
const fs = require('fs');
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const puppeteer = (await import('puppeteer-core')).default;
  const dev = process.argv[2], serial = process.argv[3], taps = Number(process.argv[4] || 15), jb = process.argv[5] || 'off';
  // 다른 기기들도 동시에 쓰이는 상황: 측정하는 동안 그 기기들의 화면을 계속 넘깁니다.
  const others = (process.argv[6] || '').split(',').filter(Boolean);
  const busy = others.map(o => spawn('bash', ['-c', `while true; do ${process.env.HOME}/cf/bin/adb -s ${o} shell "input swipe 600 800 100 800 300; input swipe 100 800 600 800 300"; done`]));
  const pass = fs.readFileSync(process.env.HOME + '/.config/haebom/web-password.txt', 'utf8').trim();
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome', headless: 'new',
    args: ['--autoplay-policy=no-user-gesture-required', '--window-size=600,1000', '--disable-background-timer-throttling', '--disable-renderer-backgrounding'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 600, height: 1000 });
  await page.authenticate({ username: 'haebom', password: pass });
  await page.goto('http://127.0.0.1:6080/devices/' + dev + '/files/client.html?jb=' + jb);
  for (let i = 0; i < 60; i++) { if (await page.evaluate(() => { const v = document.querySelector('video'); return !!v && v.videoWidth > 0 && v.readyState >= 2; })) break; await sleep(500); }
  await sleep(3000);
  const info = await page.evaluate(() => {
    const v = document.querySelector('video'); const r = v.getBoundingClientRect();
    const fx = 0.5, fy = 0.5; const ar = v.videoWidth / v.videoHeight; let w = r.width, h = r.height; if (w / h > ar) { w = h * ar; } else { h = w / ar; }
    const left = r.left + (r.width - w) / 2, top = r.top + (r.height - h) / 2;
    const S = 48; const c = document.createElement('canvas'); c.width = S; c.height = S; const ctx = c.getContext('2d', { willReadFrequently: true });
    const sx = Math.round(v.videoWidth * fx - S / 2), sy = Math.round(v.videoHeight * fy - S / 2);
    const W = window; W.__f = []; W.__down = []; W.__n = 0;
    const sig = () => { ctx.drawImage(v, sx, sy, S, S, 0, 0, S, S); const d = ctx.getImageData(0, 0, S, S).data; const o = new Uint8Array(S * S); for (let i = 0; i < S * S; i++) o[i] = (d[i * 4] + d[i * 4 + 1] + d[i * 4 + 2]) / 3; return o; };
    const cb = (now, md) => { W.__n++; W.__f.push({ t: md.expectedDisplayTime || now, s: sig() }); if (W.__f.length > 600) W.__f.shift(); v.requestVideoFrameCallback(cb); };
    v.requestVideoFrameCallback(cb);
    document.addEventListener('mousedown', () => W.__down.push(performance.now()), true);
    return { x: left + w * fx, y: top + h * fy, vw: v.videoWidth, vh: v.videoHeight };
  });
  const res = [];
  for (let k = 0; k < taps; k++) {
    await sleep(700 + Math.random() * 300);
    await page.evaluate(() => { window.__f.length = 0; });
    await sleep(250);
    await page.mouse.move(info.x, info.y); await page.mouse.down(); await sleep(260); await page.mouse.up();
    await sleep(800);
    const l = await page.evaluate(() => {
      const W = window; const t0 = W.__down[W.__down.length - 1]; const fr = W.__f; if (!fr.length) return null;
      const diff = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]); return s / a.length; };
      const before = fr.filter(f => f.t <= t0); const base = before.length ? before[before.length - 1].s : fr[0].s;
      let noise = 0; for (let i = 1; i < before.length; i++) noise = Math.max(noise, diff(before[i].s, before[i - 1].s));
      for (const f of fr) { if (f.t > t0 && diff(f.s, base) > Math.max(6, noise * 3)) return f.t - t0; }
      return null;
    });
    res.push(l == null ? null : Math.round(l));
  }
  // 움직이는 화면에서의 fps: 기기 화면을 계속 좌우로 넘기면서 10초 동안 받은 프레임 수
  const W = info.vw, H = info.vh;
  const sw = spawn('bash', ['-c', `for i in $(seq 9); do ${process.env.HOME}/cf/bin/adb -s ${serial} shell "input swipe ${Math.round(W*0.85)} ${Math.round(H*0.5)} ${Math.round(W*0.15)} ${Math.round(H*0.5)} 350; input swipe ${Math.round(W*0.15)} ${Math.round(H*0.5)} ${Math.round(W*0.85)} ${Math.round(H*0.5)} 350"; done`]);
  await sleep(1500);
  const n0 = await page.evaluate(() => window.__n); await sleep(10000); const n1 = await page.evaluate(() => window.__n);
  sw.kill();
  const st = await page.evaluate(async () => {
    const p = (window.__pcs || [])[0]; if (!p) return {}; const s = await p.getStats(); const o = {};
    s.forEach(r => { if (r.type === 'inbound-rtp' && r.kind === 'video') { o.jbMs = Math.round(1000 * r.jitterBufferDelay / r.jitterBufferEmittedCount); o.decMs = +(1000 * r.totalDecodeTime / r.framesDecoded).toFixed(1); o.kbps = null; o.codecId = r.codecId; } });
    s.forEach(r => { if (r.id === o.codecId) o.codec = r.mimeType; }); delete o.codecId; delete o.kbps; return o;
  });
  const ok = res.filter(x => x != null).sort((a, b) => a - b);
  console.log(JSON.stringify({ others_busy: others.length, video: info.vw + 'x' + info.vh, latency_median_ms: ok[Math.floor(ok.length / 2)], latency_min: ok[0], latency_p90: ok[Math.floor(ok.length * 0.9)], misses: res.length - ok.length, fps_animating: +((n1 - n0) / 10).toFixed(1), ...st }));
  busy.forEach(b => b.kill());
  await browser.close();
})().catch(e => { console.error('bench error', e); process.exit(1); });
