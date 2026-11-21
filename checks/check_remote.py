"""띄운 곳이 밖에서 제대로 되는지 브라우저로 확인한다. adb도 서버 접속도 쓰지 않고, 방문자가 하는 일만 한다.

    pip install playwright && playwright install chromium
    python checks/check_remote.py https://34-64-0-1.sslip.io            # 비밀번호가 없을 때
    DEMO_AUTH=haebom:<비밀번호> python checks/check_remote.py https://34-64-0-1.sslip.io

하는 일과 보는 값:
 1. 첫 화면: 폰이 몇 대이고 몇 대가 비어 있는지
 2. 맨 뒤의 빈 폰을 고른다: 누른 때부터 폰 화면의 영상이 올 때까지의 시간, 영상의 크기
 3. WebRTC가 어느 주소로 붙었는지(브라우저의 통계). 참고값이다: 브라우저가 주소를 비워서 줄 때가 있다. 붙었는지는 2의 영상으로 본다
 4. 소리 켜기: 폰 화면 안의 audio 요소가 재생 상태가 되는지
 5. 마이크 켜기(가짜 마이크 장치): 브라우저에서 폰으로 소리 패킷이 나가는지. https나 localhost가 아니면 버튼이 꺼져 있다
 6. 다른 방문자가 같은 폰을 고르면 409, 그 폰의 화면 주소를 열면 403인지
 7. 사용 끝내기: 폰이 "정리하는 중"을 거쳐 다시 "비어 있어요"가 되는지

끝에 JSON 하나를 찍는다. "problems"가 비어 있으면 된 것이다.
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

base = sys.argv[1].rstrip("/")
cred = os.environ.get("DEMO_AUTH", "")
auth = {"username": cred.split(":")[0], "password": cred.split(":", 1)[1]} if ":" in cred else None
R, problems = {}, []

STATS = """async () => {
    const out = {video: null, audioOut: 0, pair: null, state: []};
    for (const pc of window.__pcs || []) {
        out.state.push(pc.connectionState);
        const st = await pc.getStats(); const byId = {}; st.forEach(r => byId[r.id] = r);
        st.forEach(r => {
            if (r.type === 'inbound-rtp' && r.kind === 'video') out.video = {frames: r.framesDecoded, w: r.frameWidth, h: r.frameHeight, fps: r.framesPerSecond};
            if (r.type === 'outbound-rtp' && r.kind === 'audio') out.audioOut += r.packetsSent || 0;
            if (r.type === 'candidate-pair' && r.nominated && r.state === 'succeeded') {
                const m = byId[r.remoteCandidateId] || {};
                out.pair = (m.address || m.ip) + ':' + m.port + ' ' + m.protocol + ' ' + m.candidateType;
            }
        });
    }
    out.audio = [...document.querySelectorAll('audio.device-audio')].map(a => !a.paused && !a.muted);
    const m = document.getElementById('mic_btn'); out.mic = m ? m.textContent.trim() : null;
    return out;
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--ignore-certificate-errors"])
    new = lambda: browser.new_context(viewport={"width": 1280, "height": 900}, ignore_https_errors=True, permissions=["microphone"], http_credentials=auth)
    page = new().new_page()
    page.goto(base + "/haebom/")
    page.wait_for_selector("#rack .slot", timeout=30000)
    page.wait_for_timeout(1500)
    rack = page.evaluate("[...document.querySelectorAll('#rack .slot')].map(li => li.className.replace('slot ', ''))")
    R["1 phones"] = rack
    R["1 secure context"] = page.evaluate("window.isSecureContext")
    if "idle" not in rack:
        problems.append("no free phone to test with")
        print(json.dumps({"result": R, "problems": problems}, ensure_ascii=False, indent=1)); sys.exit(1)
    n = len(rack) - rack[::-1].index("idle")                       # the last free phone
    t = time.time()
    page.evaluate("i => document.querySelectorAll('#rack .slot button')[i].click()", n - 1)
    page.wait_for_selector("#session:not([hidden])", timeout=20000)
    frame = None
    while time.time() - t < 60 and frame is None:
        frame = next((f for f in page.frames if "client.html" in f.url), None)
        page.wait_for_timeout(100)
    s = {}
    if frame is None:
        problems.append("the phone screen did not load: " + page.inner_text("#device-note"))
    else:
        while time.time() - t < 60:
            s = frame.evaluate(STATS)
            if s["video"] and (s["video"]["frames"] or 0) > 0:
                break
            page.wait_for_timeout(250)
        R["2 phone"] = n
        R["2 video after s"] = round(time.time() - t, 1)
        R["2 video"] = s.get("video")
        R["3 connected to"] = s.get("pair")
        if not s.get("video") or not s["video"].get("frames"):
            problems.append("no video from the phone: WebRTC did not connect (ports 15550-15599 tcp/udp open? WEBRTC_BIND=0.0.0.0?)")

        page.wait_for_function("!document.getElementById('btn-sound').disabled", timeout=20000)
        page.wait_for_timeout(1200)
        if page.inner_text("#btn-sound") == "소리 켜기":
            page.click("#btn-sound")
            page.wait_for_timeout(1200)
        R["4 sound playing"] = frame.evaluate(STATS)["audio"]
        if not all(R["4 sound playing"]) or not R["4 sound playing"]:
            problems.append("the sound did not start")

        if page.evaluate("document.getElementById('btn-mic').disabled"):
            R["5 microphone"] = "button is off (not https, or the phone has no microphone)"
            if R["1 secure context"]:
                problems.append("the microphone button is off on a secure page")
        else:
            page.click("#btn-mic")
            page.wait_for_timeout(3000)
            a = frame.evaluate(STATS)
            page.wait_for_timeout(2000)
            b = frame.evaluate(STATS)
            R["5 microphone"] = {"button": b["mic"], "packets sent": [a["audioOut"], b["audioOut"]]}
            if b["mic"] != "mic" or b["audioOut"] <= a["audioOut"]:
                problems.append("the microphone did not reach the phone")

    other = new().new_page()
    other.goto(base + "/haebom/")
    other.wait_for_selector("#rack .slot", timeout=30000)
    pid = f"cvd_1-{n}-{n}"
    claim = other.evaluate("""id => fetch('/haebom/api/claim', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({device: id})}).then(r => r.status)""", pid)
    screen = other.evaluate("u => fetch(u).then(r => r.status)", f"/devices/{pid}/files/client.html")
    R["6 another visitor"] = {"claim": claim, "its screen": screen}
    if claim != 409 or screen != 403:
        problems.append("the lock did not refuse another visitor")

    t = time.time()
    page.click("#btn-leave")
    page.wait_for_selector("#lobby:not([hidden])", timeout=20000)
    seen = []
    while time.time() - t < 120:
        st = other.evaluate("n => { const li = document.querySelectorAll('#rack .slot')[n - 1]; return li ? li.className.replace('slot ', '') : ''; }", n)
        if not seen or seen[-1][1] != st:
            seen.append([round(time.time() - t, 1), st])
        if st == "idle" and len(seen) > 1:
            break
        other.wait_for_timeout(300)
    R["7 after ending"] = seen
    if not seen or seen[-1][1] != "idle":
        problems.append("the phone was not offered again after it was given back")
    print(json.dumps({"result": R, "problems": problems}, ensure_ascii=False, indent=1))
    browser.close()
    sys.exit(1 if problems else 0)
