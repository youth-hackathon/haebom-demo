"""시연 API: 시연 페이지의 버튼을 기기 명령으로 바꾸고, 기기에서 안내가 진행되는 것을 페이지에 알려 준다.

파이썬 표준 라이브러리와 adb만 쓴다. 컨테이너 안에서 돌고, 기기(Cuttlefish 컨테이너)에는 네트워크의 adb로 붙는다.

    GET  /state     기기, 앱, 서버가 준비됐는지와 지금 기기의 상태(글자 크기, 다음 알람)
    GET  /events    기기에서 진행되는 안내를 순서대로. ?after=<번호> 뒤의 것만
    POST /start     {"task": "글자 크기 키우기"}  안내를 시작한다
    POST /stop      안내를 멈춘다
    POST /reset     기기를 처음 상태로 (글자 크기 1.0, 알람 지우기, 쓰던 앱 끄기, 홈 화면)

이 서버는 세 가지 일을 계속한다.
- 기기 준비: 앱이 없으면 설치하고, 접근성 서비스를 켜고, 앱이 안내 서버와 TTS 서버를 보게 한다. 기기가 다시 켜지면 다시 한다.
- 이어 주기: 기기 안의 127.0.0.1:<포트>는 adb reverse로 이 컨테이너의 같은 포트에 닿는다. 그 포트를 다른 컨테이너
  (매뉴얼 앞단, TTS)로 이어 준다. 그래서 기기의 앱은 어디서나 같은 주소(127.0.0.1)를 쓴다.
- 기록 읽기: 앱이 로그(logcat의 ToolusGuide)에 남기는 줄을 읽어 "몇 단계, 무엇을 안내, 누가 답함, 걸린 시간"으로 바꾼다.

누르는 것은 페이지를 보는 사람이다. 이 서버도 앱도 기기 화면을 대신 누르지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("DEMO_PORT", "8790"))
ADB = os.environ.get("ADB", "adb")
SERIAL = os.environ.get("DEVICE_SERIAL", "device:6520")
DEVICE_ID = os.environ.get("DEVICE_ID", "cvd_1-1-1")  # the name the Cuttlefish web client knows the device by
APK = os.environ.get("APP_APK", "/app/haebom.apk")
FRONT = os.environ.get("FRONT_URL", "http://front:8770").rstrip("/")
TTS = os.environ.get("TTS_URL", "http://tts:8766").rstrip("/")
# device port = host:port. The app on the device talks to 127.0.0.1:<device port>.
RELAYS = dict(kv.split("=", 1) for kv in os.environ.get("RELAYS", "8770=front:8770,8766=tts:8766").split(",") if "=" in kv)
# the engine the app asks the TTS server for; empty leaves the choice to the TTS server (its TTS_ENGINE)
TTS_ENGINE = os.environ.get("APP_TTS_ENGINE", "")
PKG = "ai.toolus.mobileguide"
SERVICE = f"{PKG}/{PKG}.GuideAccessibilityService"
TAG = "ToolusGuide"
MAX_TASK = 60
STATUS_BUBBLES = {"화면을 살펴보고 있어요", "다음 안내를 준비하고 있어요", "확인하고 있어요", "잘하셨어요", "잠시 기다려 주세요"}


def adb(*args: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"adb failed: {exc}"


def sh(command: str, timeout: int = 20) -> str:
    return adb("shell", command, timeout=timeout).strip()


def apk_sha() -> str:
    try:
        with open(APK, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def quote(text: str) -> str:
    """One argument for the device's shell."""
    return "'" + text.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------- relays (device 127.0.0.1:<port> -> another container)

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


# ---------------------------------------------------------------- the device, kept ready

class Device:
    def __init__(self) -> None:
        self.online = False
        self.app = False
        self.service = False
        self.configured = False
        self.note = "기기를 기다리는 중"
        self.boot_id = ""
        self.model = ""

    def check(self) -> None:
        """Bring the device to the state the demo needs, whatever state it is in. Called every few seconds."""
        # the answer must be exactly "device": an error message also has the word in it
        if adb("get-state", timeout=8).strip() != "device":
            subprocess.run([ADB, "connect", SERIAL], capture_output=True, timeout=15)
            self.online = adb("get-state", timeout=8).strip() == "device"
            if not self.online:
                self.note = "기기가 켜지는 중"
                self.configured = False
                return
        self.online = True
        if sh("getprop sys.boot_completed", 8) != "1":
            self.note = "기기가 부팅하는 중"
            self.configured = False
            return
        boot = sh("cat /proc/sys/kernel/random/boot_id", 8)
        if boot != self.boot_id:
            self.boot_id, self.configured = boot, False
        path = sh(f"pm path {PKG}", 10)
        self.app = "package:" in path
        if self.app and not self.configured and APK_SHA:
            # the app on the device must be the one that came with this server: an older one logs less than the page reads
            on_device = sh("sha256sum " + quote(path.splitlines()[0].replace("package:", "").strip()), 15).split()
            self.app = bool(on_device) and on_device[0] == APK_SHA
        if not self.app:
            self.note = "앱을 설치하는 중"
            out = adb("install", "-r", APK, timeout=180)
            self.app = "Success" in out
            if not self.app:
                self.note = "앱을 설치하지 못했습니다: " + out.strip().splitlines()[-1][:80]
                return
            self.configured = False
        enabled = sh("settings get secure enabled_accessibility_services", 8)
        if SERVICE not in enabled:
            value = SERVICE if enabled in ("", "null") else f"{enabled}:{SERVICE}"
            sh(f"settings put secure enabled_accessibility_services {value}; settings put secure accessibility_enabled 1")
            time.sleep(2)
            enabled = sh("settings get secure enabled_accessibility_services", 8)
            self.configured = False
        self.service = SERVICE in enabled
        if not self.service:
            self.note = "접근성 서비스를 켜지 못했습니다"
            return
        # adb reverse does not survive a reconnect: put it back whenever it is missing
        have = adb("reverse", "--list", timeout=8)
        for port in RELAYS:
            if f"tcp:{port}" not in have:
                adb("reverse", f"tcp:{port}", f"tcp:{port}", timeout=8)
                self.configured = False
        if not self.configured:
            sh("svc power stayon true; settings put system screen_off_timeout 2147483647; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard")
            guide = "http://127.0.0.1:8770" if "8770" in RELAYS else FRONT
            tts = "http://127.0.0.1:8766" if "8766" in RELAYS else TTS
            sh(f"am broadcast -a {PKG}.DEBUG_CONFIG -p {PKG} --es guide_base {quote(guide)} --es tts_base {quote(tts)} --es engine {quote(TTS_ENGINE)}")
            self.model = sh("getprop ro.product.model", 8)
            self.configured = True
        self.note = "준비됨"

    def keep(self) -> None:
        while True:
            try:
                self.check()
            except Exception as exc:  # noqa: BLE001 - the keeper must not die
                self.note = f"기기 확인 실패: {exc}"
            time.sleep(4 if self.note == "준비됨" else 2)

    def facts(self) -> dict:
        """What the page shows as "the phone now": read from the device, not guessed from the guide."""
        scale = sh("settings get system font_scale", 6)
        alarms = sh("su 0 content query --uri content://com.android.deskclock/alarms --projection hour:minutes:enabled", 8)
        on = re.findall(r"hour=(\d+), minutes=(\d+), enabled=1", alarms)
        return {"font_scale": float(scale) if re.fullmatch(r"[0-9.]+", scale) else None,
                "alarms_on": [f"{int(h):02d}:{int(m):02d}" for h, m in on]}


APK_SHA = apk_sha()
DEVICE = Device()


# ---------------------------------------------------------------- the guide's progress, read from the app's log

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

    def add(self, item: dict) -> None:
        self.seq += 1
        item["seq"] = self.seq
        item["t"] = round(time.time() - self.started, 1) if self.started else 0
        self.items.append(item)

    def step(self, n: int) -> dict | None:
        return next((i for i in reversed(self.items) if i.get("type") == "step" and i.get("step") == n), None)

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

    def touch(self, item: dict) -> None:
        """A changed item is sent again: it gets a new sequence number."""
        self.seq += 1
        item["seq"] = self.seq

    def since(self, after: int, run: int) -> dict:
        with self.lock:
            items = self.items if run != self.run else [i for i in self.items if i["seq"] > after]
            return {"run": self.run, "state": self.state, "task": self.task, "next": self.seq,
                    "elapsed": round(time.time() - self.started, 1) if self.state == "running" else None,
                    "events": [dict(i) for i in items]}

    def read(self) -> None:
        """Follow the device's log for as long as the device is there; start again when it goes away."""
        while True:
            if not DEVICE.online:
                time.sleep(2)
                continue
            try:
                p = subprocess.Popen([ADB, "-s", SERIAL, "logcat", "-v", "raw", "-T", "1", "-s", f"{TAG}:I"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
                for line in p.stdout:  # type: ignore[union-attr]
                    line = line.strip()
                    if line and not line.startswith("DUMP") and not line.startswith("-----"):
                        try:
                            self.feed(line)
                        except Exception:  # noqa: BLE001 - one odd line must not stop the reader
                            pass
                p.wait()
            except OSError:
                pass
            time.sleep(2)


EVENTS = Events()


# ---------------------------------------------------------------- what the page asks for

def get_json(url: str, timeout: float = 3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def state() -> dict:
    front = get_json(FRONT + "/health")
    tts = get_json(TTS + "/health")
    # only the manuals made on this kind of device: a manual's rules are tied to the screens they were made on
    manuals = [{"id": m["id"], "task": m["task"], "aliases": m.get("aliases", []), "steps": m.get("steps", 0)}
               for m in (front or {}).get("manuals", [])
               if m.get("status") == "verified" and (not m.get("devices") or DEVICE.model in m["devices"])]
    ready = DEVICE.online and DEVICE.app and DEVICE.service and DEVICE.note == "준비됨"
    return {
        "device": {"id": DEVICE_ID, "online": DEVICE.online, "app": DEVICE.app, "service": DEVICE.service, "ready": ready, "note": DEVICE.note, "model": DEVICE.model},
        "front": {"ok": bool(front), "manuals": manuals},
        "tts": {"ok": bool(tts), "engine": (tts or {}).get("default_engine")},
        "phone": DEVICE.facts() if ready else {},
        "guide": {"state": EVENTS.state, "task": EVENTS.task, "run": EVENTS.run},
    }


def start(body: dict) -> tuple[int, dict]:
    task = " ".join(str(body.get("task", "")).split())
    if not task or len(task) > MAX_TASK or any(ord(c) < 32 for c in task):
        return 400, {"error": f"요청은 1~{MAX_TASK}자로 적어 주세요."}
    if DEVICE.note != "준비됨":
        return 503, {"error": "기기가 아직 준비되지 않았습니다: " + DEVICE.note}
    EVENTS.task = task
    out = sh(f"am broadcast -a {PKG}.DEBUG_START -p {PKG} --es task {quote(task)}")
    return (200, {"ok": True, "task": task}) if "Broadcast completed" in out else (502, {"error": "기기에 요청을 보내지 못했습니다."})


def stop() -> tuple[int, dict]:
    sh(f"am broadcast -a {PKG}.DEBUG_STOP -p {PKG}")
    with EVENTS.lock:
        if EVENTS.state == "running":
            EVENTS.state = "stopped"
    return 200, {"ok": True}


def reset() -> tuple[int, dict]:
    """The phone as it was before anyone followed a guide. Fixed commands only: nothing from the request reaches the shell."""
    stop()
    home = sh("cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME").splitlines()
    home_pkg = home[-1].split("/")[0] if home and "/" in home[-1] else ""
    recents = set(re.findall(r"mActivityComponent=([A-Za-z0-9_.]+)/", adb("shell", "dumpsys activity recents", timeout=15)))
    for p in sorted(recents - {PKG, home_pkg, "com.android.systemui", ""}):
        sh(f"am force-stop {p}", 8)
    sh("settings put system font_scale 1.0")
    sh("pm clear com.android.deskclock", 15)
    sh("input keyevent KEYCODE_HOME")
    with EVENTS.lock:
        EVENTS.run += 1
        EVENTS.items, EVENTS.state, EVENTS.task, EVENTS.started = [], "idle", "", 0.0
    return 200, {"ok": True}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, obj) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv)
        path = path.rstrip("/")
        try:
            if path.endswith("/state"):
                return self._send(200, state())
            if path.endswith("/events"):
                return self._send(200, EVENTS.since(int(params.get("after", "0") or 0), int(params.get("run", "-1") or -1)))
            if path.endswith("/health"):
                return self._send(200, {"ok": True})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})
        self._send(404, {"error": "no such path"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except ValueError:
            return self._send(400, {"error": "the request body is not JSON"})
        path = self.path.partition("?")[0].rstrip("/")
        try:
            if path.endswith("/start"):
                return self._send(*start(body if isinstance(body, dict) else {}))
            if path.endswith("/stop"):
                return self._send(*stop())
            if path.endswith("/reset"):
                return self._send(*reset())
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})
        self._send(404, {"error": "no such path"})


def main() -> None:
    for port, target in RELAYS.items():
        threading.Thread(target=relay, args=(int(port), target), daemon=True).start()
    threading.Thread(target=DEVICE.keep, daemon=True).start()
    threading.Thread(target=EVENTS.read, daemon=True).start()
    print(f"[demo-api] :{PORT} device {SERIAL} ({DEVICE_ID}) front {FRONT} relays {RELAYS}", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
