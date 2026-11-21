"""시연 API: 폰 여러 대를 방문자에게 한 대씩 내주고, 페이지의 버튼을 그 폰의 명령으로 바꾸고, 안내 진행을 알려 준다.

파이썬 표준 라이브러리와 adb만 쓴다. 컨테이너 안에서 돌고, 폰(Cuttlefish 컨테이너의 기기들)에는 네트워크의 adb로 붙는다.

    GET  /devices   폰 목록과 상태: 비어 있음 / 사용 중 / 켜지는 중, 그리고 내가 쓰는 폰
    POST /claim     {"device": "cvd_1-1-1"}  그 폰을 내 것으로. 폰은 처음 상태로 돌아간 뒤 열린다
    POST /release   폰을 반납한다
    GET  /state     내 폰의 준비 상태, 폰의 실제 값(글자 크기, 켜진 알람), 반납까지 남은 시간
    GET  /events    내 폰에서 진행되는 안내를 순서대로. ?after=<번호> 뒤의 것만
    POST /start     {"task": "글자 크기 키우기"}  안내를 시작한다
    POST /stop      안내를 멈춘다
    POST /reset     내 폰을 처음 상태로
    GET  /allow     (nginx만 부른다) 이 요청이 그 폰의 화면에 닿아도 되는지

폰을 쓰는 사람은 쿠키(haebom_lease)로 가린다. 한 브라우저가 한 번에 한 대를 쓴다.
폰은 이럴 때 회수된다: "사용 끝내기"를 눌렀을 때, 페이지가 닫혀 소식이 끊겼을 때(SEEN_S), 한동안 아무 조작이 없을 때(IDLE_S).

이 서버가 계속하는 일:
- 폰 찾기: Cuttlefish operator가 알려 주는 기기 목록을 읽는다.
- 폰 준비: 앱이 없거나 다른 빌드면 설치하고, 접근성 서비스를 켜고, 앱이 안내 서버와 TTS 서버를 보게 한다.
- 이어 주기: 폰 안의 127.0.0.1:<포트>는 adb reverse로 이 컨테이너의 같은 포트에 닿는다. 그 포트를 다른 컨테이너로 이어 준다.
- 기록 읽기: 앱이 로그(logcat의 ToolusGuide)에 남기는 줄을 "몇 단계, 무엇을 안내, 누가 답함, 걸린 시간"으로 바꾼다.

누르는 것은 페이지를 보는 사람이다. 이 서버도 앱도 폰 화면을 대신 누르지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("DEMO_PORT", "8790"))
ADB = os.environ.get("ADB", "adb")
DEVICE_HOST = os.environ.get("DEVICE_HOST", "device")
OPERATOR = os.environ.get("OPERATOR_URL", f"https://{DEVICE_HOST}:1443").rstrip("/")
EXPECT = int(os.environ.get("DEVICES", "4"))  # how many phones the page shows while they are still being found
APK = os.environ.get("APP_APK", "/app/haebom.apk")
FRONT = os.environ.get("FRONT_URL", "http://front:8770").rstrip("/")
TTS = os.environ.get("TTS_URL", "http://tts:8766").rstrip("/")
# phone port = host:port. The app on the phone talks to 127.0.0.1:<phone port>.
RELAYS = dict(kv.split("=", 1) for kv in os.environ.get("RELAYS", "8770=front:8770,8766=tts:8766").split(",") if "=" in kv)
# The speech server the app talks to, when it is not the one in this compose. The address can end in a secret path:
# it is given to the app and to nothing else (not logged, not sent to the page).
APP_TTS_BASE = os.environ.get("APP_TTS_BASE", "").strip().rstrip("/")
APP_TTS_STREAM = os.environ.get("APP_TTS_STREAM", "true").strip() or "true"
IDLE_S = int(os.environ.get("LEASE_IDLE_S", "180"))  # no touch, no key, no button for this long: the phone is taken back
SEEN_S = int(os.environ.get("LEASE_SEEN_S", "25"))   # the page has not asked anything for this long: it is gone
COOKIE = "haebom_lease"
PKG = "ai.toolus.mobileguide"
SERVICE = f"{PKG}/{PKG}.GuideAccessibilityService"
TAG = "ToolusGuide"
MAX_TASK = 60
STATUS_BUBBLES = {"화면을 살펴보고 있어요", "다음 안내를 준비하고 있어요", "확인하고 있어요", "잘하셨어요", "잠시 기다려 주세요"}
READY = "준비됨"


def quote(text: str) -> str:
    """One argument for the phone's shell."""
    return "'" + text.replace("'", "'\\''") + "'"


def apk_sha() -> str:
    try:
        with open(APK, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


APK_SHA = apk_sha()


# ---------------------------------------------------------------- relays (phone 127.0.0.1:<port> -> another container)

def relay(port: int, target: str) -> None:
    host, _, tport = target.rpartition(":")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(64)

    def pump(a: socket.socket, b: socket.socket) -> None:
        try:
            while True:
                data = a.recv(65536)
                if not data:
                    break
                b.sendall(data)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                s.close()

    while True:
        client, _ = srv.accept()
        try:
            upstream = socket.create_connection((host, int(tport)), timeout=5)
            upstream.settimeout(None)
        except OSError:
            client.close()
            continue
        threading.Thread(target=pump, args=(client, upstream), daemon=True).start()
        threading.Thread(target=pump, args=(upstream, client), daemon=True).start()


# ---------------------------------------------------------------- the guide's progress on one phone, read from the app's log

class Events:
    """What the app logged, as a list the page can draw. A new guide (plan event=start) starts a new list."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.run = 0
        self.items: list[dict] = []
        self.seq = 0
        self.task = ""
        self.started = 0.0
        self.state = "idle"  # idle | running | done | stopped

    def clear(self) -> None:
        with self.lock:
            self.run += 1
            self.items, self.state, self.task, self.started = [], "idle", "", 0.0

    def add(self, item: dict) -> None:
        self.seq += 1
        item["seq"] = self.seq
        item["t"] = round(time.time() - self.started, 1) if self.started else 0
        self.items.append(item)

    def step(self, n: int) -> dict | None:
        return next((i for i in reversed(self.items) if i.get("type") == "step" and i.get("step") == n), None)

    def touch(self, item: dict) -> None:
        """A changed item is sent again: it gets a new sequence number."""
        self.seq += 1
        item["seq"] = self.seq

    def feed(self, msg: str) -> None:
        with self.lock:
            m = re.match(r"plan event=(\S+) ", msg)
            if m and m.group(1) == "start":
                self.run += 1
                self.items, self.started, self.state = [], time.time(), "running"
                self.add({"type": "start", "task": self.task})
                return
            m = re.match(r"step=(\d+) action=(\S+) \{(.*)\} -> (\w+) \((\d+)ms\)", msg)
            if m:
                n, name, args, kind, ms = int(m.group(1)), m.group(2), m.group(3), m.group(4), int(m.group(5))
                target = re.search(r"target_text=([^,}]*)", args)
                item = {"type": "step", "step": n, "action": name, "kind": kind, "ms": ms, "source": "",
                        "target": target.group(1).strip() if target else "", "title": "", "outcome": ""}
                if kind == "Terminal":
                    item["title"] = "다 했어요" if "status=completed" in args else "여기서 멈출게요"
                    self.state = "done"
                elif kind == "Wait":
                    item["title"] = "잠시 기다리기"
                elif kind == "Unaimable":
                    item["title"] = "누를 곳을 찾지 못해 다시 확인"
                elif kind == "Ask":
                    item["title"] = "질문"
                self.add(item)
                return
            m = re.match(r"SOURCE step=(\d+) (\S+)", msg)
            if m:
                s = self.step(int(m.group(1)))
                if s is not None:
                    s["source"] = m.group(2)
                    self.touch(s)
                return
            m = re.match(r"ARM step=(\d+) verb=(\S+) src=\S+ title=(.*?)(?: text=| key=|$)", msg)
            if m:
                s = self.step(int(m.group(1)))
                if s is not None:
                    s["title"], s["verb"] = m.group(3).strip(), m.group(2)
                    self.touch(s)
                return
            m = re.match(r"BUBBLE '(.*)' from=", msg)
            if m and self.items:
                last = self.items[-1]
                # the sentence on the phone for the step that is up now (status bubbles between steps are not a step's words)
                if last.get("type") == "step" and last.get("kind") == "Guide" and not last.get("outcome") and m.group(1) not in STATUS_BUBBLES:
                    last["bubble"] = m.group(1)
                    self.touch(last)
                return
            m = re.match(r"outcome (\S+) :: (.*)", msg)
            if m:
                s = next((i for i in reversed(self.items) if i.get("type") == "step" and i.get("kind") == "Guide"), None)
                if s is not None and not s["outcome"]:
                    s["outcome"] = m.group(1)
                    self.touch(s)
                return

    def since(self, after: int, run: int) -> dict:
        with self.lock:
            items = self.items if run != self.run else [i for i in self.items if i["seq"] > after]
            return {"run": self.run, "state": self.state, "task": self.task, "next": self.seq,
                    "elapsed": round(time.time() - self.started, 1) if self.state == "running" else None,
                    "events": [dict(i) for i in items]}


# ---------------------------------------------------------------- one phone

class Phone:
    def __init__(self, device_id: str, adb_port: int) -> None:
        self.id = device_id                       # the name the Cuttlefish web client knows the device by
        self.serial = f"{DEVICE_HOST}:{adb_port}"
        self.n = adb_port - 6519                  # 폰 1, 폰 2, ...
        self.online = self.app = self.service = self.configured = False
        self.note = "켜지는 중"
        self.boot_id = ""
        self.model = ""
        self.events = Events()
        self.work = threading.Lock()              # one of: keeping ready, resetting, tidying
        # who has it (all under LEASES)
        self.holder = ""
        self.since = self.last_seen = self.last_active = 0.0
        self.preparing = False

    # ---- adb

    def adb(self, *args: str, timeout: int = 30) -> str:
        try:
            r = subprocess.run([ADB, "-s", self.serial, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            return (r.stdout or "") + (r.stderr or "")
        except (subprocess.TimeoutExpired, OSError) as exc:
            return f"adb failed: {exc}"

    def sh(self, command: str, timeout: int = 20) -> str:
        return self.adb("shell", command, timeout=timeout).strip()

    @property
    def ready(self) -> bool:
        return self.online and self.app and self.service and self.note == READY

    # ---- kept ready

    def enable_service(self, toggle: bool = False) -> bool:
        """The accessibility service on. [toggle]: off and on again, for after the app's process was stopped."""
        enabled = self.sh("settings get secure enabled_accessibility_services", 8)
        others = ":".join(s for s in enabled.split(":") if s and s != "null" and s != SERVICE)
        if toggle and SERVICE in enabled:
            self.sh(f"settings put secure enabled_accessibility_services {quote(others)}", 8)
            enabled = others
        if SERVICE not in enabled:
            value = SERVICE if not others else f"{others}:{SERVICE}"
            self.sh(f"settings put secure enabled_accessibility_services {quote(value)}; settings put secure accessibility_enabled 1", 8)
        # the setting alone is not the service running: wait until the system has bound it
        for _ in range(20):
            if re.search(r"Bound services:\{[^\n]*" + re.escape(PKG), self.adb("shell", "dumpsys accessibility", timeout=10)):
                return True
            time.sleep(0.5)
        return False

    def configure(self) -> None:
        """The app looks at this compose's guide server, and at the speech server it was told (or the one in this compose)."""
        guide = "http://127.0.0.1:8770" if "8770" in RELAYS else FRONT
        tts = APP_TTS_BASE or ("http://127.0.0.1:8766" if "8766" in RELAYS else TTS)
        self.sh(f"am broadcast -a {PKG}.DEBUG_CONFIG -p {PKG} --es guide_base {quote(guide)} --es tts_base {quote(tts)} --es stream {quote(APP_TTS_STREAM)}")

    def check(self) -> None:
        """Bring the phone to the state the demo needs, whatever state it is in. Called every few seconds."""
        # the answer must be exactly "device": an error message also has the word in it
        if self.adb("get-state", timeout=8).strip() != "device":
            subprocess.run([ADB, "connect", self.serial], capture_output=True, timeout=15)
            self.online = self.adb("get-state", timeout=8).strip() == "device"
            if not self.online:
                self.note, self.configured = "켜지는 중", False
                return
        self.online = True
        if self.sh("getprop sys.boot_completed", 8) != "1":
            self.note, self.configured = "부팅하는 중", False
            return
        boot = self.sh("cat /proc/sys/kernel/random/boot_id", 8)
        if boot != self.boot_id:
            self.boot_id, self.configured = boot, False
        path = self.sh(f"pm path {PKG}", 10)
        self.app = "package:" in path
        if self.app and not self.configured and APK_SHA:
            # the app on the phone must be the one that came with this server: an older one logs less than the page reads
            on_phone = self.sh("sha256sum " + quote(path.splitlines()[0].replace("package:", "").strip()), 15).split()
            self.app = bool(on_phone) and on_phone[0] == APK_SHA
        if not self.app:
            self.note = "앱을 설치하는 중"
            out = self.adb("install", "-r", "-g", APK, timeout=180)
            self.app = "Success" in out
            if not self.app:
                self.note = "앱을 설치하지 못했습니다: " + (out.strip().splitlines() or ["?"])[-1][:80]
                return
            self.configured = False
        if SERVICE not in self.sh("settings get secure enabled_accessibility_services", 8):
            self.configured = False
            self.service = self.enable_service()
        else:
            self.service = True
        if not self.service:
            self.note = "앱을 준비하는 중"  # the system has not bound the service yet: the next round looks again
            return
        # adb reverse does not survive a reconnect: put it back whenever it is missing
        have = self.adb("reverse", "--list", timeout=8)
        for port in RELAYS:
            if f"tcp:{port}" not in have:
                self.adb("reverse", f"tcp:{port}", f"tcp:{port}", timeout=8)
                self.configured = False
        if not self.configured:
            self.sh("svc power stayon true; settings put system screen_off_timeout 2147483647; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard")
            # the microphone and the notifications the app asks for at first run: a visitor should not meet those dialogs
            self.sh(f"pm grant {PKG} android.permission.RECORD_AUDIO; pm grant {PKG} android.permission.POST_NOTIFICATIONS", 10)
            self.configure()
            self.model = self.sh("getprop ro.product.model", 8)
            self.configured = True
        self.note = READY

    def keep(self) -> None:
        while True:
            if self.work.acquire(blocking=False):
                try:
                    self.check()
                except Exception as exc:  # noqa: BLE001 - the keeper must not die
                    self.note = f"확인 실패: {exc}"
                finally:
                    self.work.release()
            time.sleep(4 if self.note == READY else 2)

    def read_log(self) -> None:
        """Follow the phone's log for as long as the phone is there; start again when it goes away."""
        while True:
            if not self.online:
                time.sleep(2)
                continue
            try:
                p = subprocess.Popen([ADB, "-s", self.serial, "logcat", "-v", "raw", "-T", "1", "-s", f"{TAG}:I"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
                for line in p.stdout:  # type: ignore[union-attr]
                    line = line.strip()
                    if line and not line.startswith("DUMP") and not line.startswith("-----"):
                        try:
                            self.events.feed(line)
                        except Exception:  # noqa: BLE001 - one odd line must not stop the reader
                            pass
                p.wait()
            except OSError:
                pass
            time.sleep(2)

    # ---- what a visitor does with it

    def facts(self) -> dict:
        """What the page shows as "the phone now": read from the phone, not guessed from the guide."""
        scale = self.sh("settings get system font_scale", 6)
        alarms = self.sh("su 0 content query --uri content://com.android.deskclock/alarms --projection hour:minutes:enabled", 8)
        on = re.findall(r"hour=(\d+), minutes=(\d+), enabled=1", alarms)
        return {"font_scale": float(scale) if re.fullmatch(r"[0-9.]+", scale) else None,
                "alarms_on": [f"{int(h):02d}:{int(m):02d}" for h, m in on]}

    def start(self, task: str) -> bool:
        self.events.task = task
        return "Broadcast completed" in self.sh(f"am broadcast -a {PKG}.DEBUG_START -p {PKG} --es task {quote(task)}")

    def stop(self) -> None:
        self.sh(f"am broadcast -a {PKG}.DEBUG_STOP -p {PKG}")
        with self.events.lock:
            if self.events.state == "running":
                self.events.state = "stopped"

    def reset(self) -> None:
        """The phone as it was before anyone used it. Fixed commands only: nothing from a request reaches the shell."""
        with self.work:
            self.stop()
            home = self.sh("cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME").splitlines()
            home_pkg = home[-1].split("/")[0] if home and "/" in home[-1] else ""
            recents = set(re.findall(r"mActivityComponent=([A-Za-z0-9_.]+)/", self.adb("shell", "dumpsys activity recents", timeout=15)))
            for p in sorted(recents - {PKG, home_pkg, "com.android.systemui", ""}):
                self.sh(f"am force-stop {p}", 8)
            self.sh("settings put system font_scale 1.0")
            self.sh("pm clear com.android.deskclock", 15)
            # what the app remembers of the last visitor ("이어서 하기", "복습하기"). Its settings (the servers) are another file.
            self.sh(f"am force-stop {PKG}; su 0 rm -f /data/user/0/{PKG}/shared_prefs/haebom.xml", 10)
            self.service = self.enable_service(toggle=True)
            self.configure()
            self.sh("input keyevent KEYCODE_WAKEUP; input keyevent KEYCODE_HOME")
            self.events.clear()

    def tidy(self) -> None:
        """After a visitor: stop the guide and leave the home screen up. The full reset is done for the next visitor."""
        with self.work:
            self.stop()
            self.sh("input keyevent KEYCODE_HOME")
            self.events.clear()


# ---------------------------------------------------------------- the phones, and who has which

PHONES: dict[str, Phone] = {}
LEASES = threading.Lock()
ENDED: dict[str, tuple[str, float]] = {}   # token -> (why the phone was taken back, when), for the page that still holds it


def discover() -> None:
    """The operator in the device container knows which devices are up: [{"device_id", "adb_port", ...}]."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    while True:
        try:
            with urllib.request.urlopen(OPERATOR + "/devices", timeout=5, context=ctx) as r:
                found = json.loads(r.read().decode("utf-8"))
            for d in sorted(found, key=lambda d: d.get("adb_port", 0)):
                pid, port = d.get("device_id"), d.get("adb_port")
                if pid and port and pid not in PHONES:
                    phone = Phone(pid, int(port))
                    PHONES[pid] = phone
                    threading.Thread(target=phone.keep, daemon=True).start()
                    threading.Thread(target=phone.read_log, daemon=True).start()
                    print(f"[demo-api] phone {phone.n}: {pid} at {phone.serial}", flush=True)
        except Exception:  # noqa: BLE001 - the device container may still be starting
            pass
        time.sleep(5 if len(PHONES) >= EXPECT else 2)


def holder_of(token: str) -> Phone | None:
    return next((p for p in PHONES.values() if token and p.holder == token), None)


def take_back(phone: Phone, why: str) -> None:
    """LEASES is held. The phone is free again; the page that had it learns why at its next question."""
    ENDED[phone.holder] = (why, time.time())
    phone.holder, phone.preparing = "", False
    threading.Thread(target=phone.tidy, daemon=True).start()


def reaper() -> None:
    while True:
        time.sleep(2)
        now = time.time()
        with LEASES:
            for p in PHONES.values():
                if not p.holder:
                    continue
                if now - p.last_seen > SEEN_S:
                    take_back(p, "gone")
                elif not p.preparing and now - p.last_active > IDLE_S:
                    take_back(p, "idle")
            for t in [t for t, (_, at) in ENDED.items() if now - at > 600]:
                del ENDED[t]


def devices(token: str) -> dict:
    now = time.time()
    rows = []
    with LEASES:
        for p in sorted(PHONES.values(), key=lambda p: p.n):
            mine = bool(token) and p.holder == token
            state = "busy" if p.holder else ("idle" if p.ready else "offline")
            rows.append({"id": p.id, "n": p.n, "state": state, "mine": mine,
                         "minutes": int((now - p.since) // 60) if p.holder else 0,
                         "note": "" if p.ready else p.note})
    for n in range(len(rows) + 1, EXPECT + 1):  # not found yet: the device container is still starting them
        rows.append({"id": "", "n": n, "state": "offline", "mine": False, "minutes": 0, "note": "켜지는 중"})
    return {"devices": rows, "idle_limit": IDLE_S}


def claim(pid: str, token: str) -> tuple[int, dict, str]:
    with LEASES:
        phone = PHONES.get(pid)
        if phone is None:
            return 404, {"error": "그런 폰이 없어요."}, ""
        if phone.holder and phone.holder == token:
            return 200, {"ok": True, "device": phone.id, "n": phone.n}, token  # mine already: come back in
        if phone.holder:
            return 409, {"error": "방금 다른 분이 이 폰을 골랐어요. 다른 폰을 골라 주세요."}, ""
        if not phone.ready:
            return 503, {"error": "이 폰은 아직 켜지는 중이에요."}, ""
        other = holder_of(token)
        if other is not None:
            take_back(other, "moved")
        now = time.time()
        new = secrets.token_urlsafe(24)
        phone.holder, phone.preparing = new, True
        phone.since = phone.last_seen = phone.last_active = now

    def prepare() -> None:
        try:
            phone.reset()
        except Exception as exc:  # noqa: BLE001
            print(f"[demo-api] phone {phone.n}: reset failed: {exc}", flush=True)
        with LEASES:
            if phone.holder == new:
                phone.preparing = False
                phone.last_active = time.time()

    threading.Thread(target=prepare, daemon=True).start()
    return 200, {"ok": True, "device": phone.id, "n": phone.n}, new


def release(token: str) -> None:
    with LEASES:
        phone = holder_of(token)
        if phone is not None:
            take_back(phone, "released")
            ENDED.pop(token, None)  # the page asked for it: there is nothing to explain


def get_json(url: str, timeout: float = 3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def state(phone: Phone) -> dict:
    front = get_json(FRONT + "/health")
    tts = get_json((APP_TTS_BASE or TTS) + "/health", 4.0)
    # only the manuals made on this kind of device: a manual's rules are tied to the screens they were made on
    manuals = [{"id": m["id"], "task": m["task"], "aliases": m.get("aliases", []), "steps": m.get("steps", 0)}
               for m in (front or {}).get("manuals", [])
               if m.get("status") == "verified" and (not m.get("devices") or phone.model in m["devices"])]
    with LEASES:
        preparing = phone.preparing
        idle_left = max(0, int(IDLE_S - (time.time() - phone.last_active)))
    ready = phone.ready and not preparing
    return {
        "device": {"id": phone.id, "n": phone.n, "online": phone.online, "app": phone.app, "service": phone.service,
                   "ready": ready, "preparing": preparing, "note": "폰을 처음 상태로 돌리는 중" if preparing else phone.note},
        "lease": {"idle_left": idle_left, "idle_limit": IDLE_S},
        "front": {"ok": bool(front), "manuals": manuals},
        "tts": {"ok": bool(tts), "engines": (tts or {}).get("engines", [])},
        "phone": phone.facts() if ready else {},
        "guide": {"state": phone.events.state, "task": phone.events.task, "run": phone.events.run},
    }


def start(phone: Phone, body: dict) -> tuple[int, dict]:
    task = " ".join(str(body.get("task", "")).split())
    if not task or len(task) > MAX_TASK or any(ord(c) < 32 for c in task):
        return 400, {"error": f"요청은 1~{MAX_TASK}자로 적어 주세요."}
    if not phone.ready or phone.preparing:
        return 503, {"error": "폰이 아직 준비되지 않았어요."}
    return (200, {"ok": True, "task": task}) if phone.start(task) else (502, {"error": "폰에 요청을 보내지 못했어요."})


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, obj, cookie: str | None = None) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8") if obj is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            age = 86400 if cookie else 0
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; Max-Age={age}; HttpOnly; SameSite=Lax")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _token(self) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def _mine(self, active: bool) -> Phone | None:
        """The caller's phone, and a sign that the caller is still there. None: answers 410 with why it is not theirs."""
        token = self._token()
        with LEASES:
            phone = holder_of(token)
            if phone is not None:
                now = time.time()
                phone.last_seen = now
                if active:
                    phone.last_active = now
                return phone
            why = ENDED.get(token, ("none", 0))[0]
        self._send(410, {"error": "쓰고 있는 폰이 없어요.", "reason": why})
        return None

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv)
        path = path.rstrip("/")
        try:
            if path.endswith("/devices"):
                return self._send(200, devices(self._token()))
            if path.endswith("/allow"):
                # nginx asks before it passes a request for /devices/<id>/... on to the device container
                m = re.match(r"/devices/([^/?]+)/", self.headers.get("X-Original-URI") or "")
                with LEASES:
                    phone = holder_of(self._token())
                    ok = phone is not None and m is not None and phone.id == m.group(1)
                return self._send(204 if ok else 403, None)
            if path.endswith("/health"):
                return self._send(200, {"ok": True, "phones": len(PHONES)})
            if path.endswith("/state"):
                phone = self._mine(params.get("active") == "1")
                return self._send(200, state(phone)) if phone else None
            if path.endswith("/events"):
                phone = self._mine(False)
                return self._send(200, phone.events.since(int(params.get("after", "0") or 0), int(params.get("run", "-1") or -1))) if phone else None
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})
        self._send(404, {"error": "no such path"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except ValueError:
            return self._send(400, {"error": "the request body is not JSON"})
        body = body if isinstance(body, dict) else {}
        path = self.path.partition("?")[0].rstrip("/")
        try:
            if path.endswith("/claim"):
                code, out, cookie = claim(str(body.get("device", "")), self._token())
                return self._send(code, out, cookie if code == 200 else None)
            if path.endswith("/release"):
                release(self._token())
                return self._send(200, {"ok": True}, "")
            if path.endswith(("/start", "/stop", "/reset")):
                phone = self._mine(True)
                if phone is None:
                    return None
                if path.endswith("/start"):
                    return self._send(*start(phone, body))
                if path.endswith("/stop"):
                    phone.stop()
                else:
                    phone.reset()
                return self._send(200, {"ok": True})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})
        self._send(404, {"error": "no such path"})


def main() -> None:
    for port, target in RELAYS.items():
        threading.Thread(target=relay, args=(int(port), target), daemon=True).start()
    threading.Thread(target=discover, daemon=True).start()
    threading.Thread(target=reaper, daemon=True).start()
    print(f"[demo-api] :{PORT} operator {OPERATOR} front {FRONT} relays {RELAYS} "
          f"speech {'given by APP_TTS_BASE' if APP_TTS_BASE else TTS} idle {IDLE_S}s", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
