#!/usr/bin/env bash
# 에뮬레이터 한 대(번호 i)의 묶음 중 한 부분을 띄웁니다. systemd가 부릅니다.
# usage: haebom-part.sh <xvfb|wm|emulator|postboot|vnc|web> <i>
set -euo pipefail
part="$1"; i="$2"
case "$i" in [0-9]) ;; *) echo "index must be 0-9" >&2; exit 2;; esac
export ANDROID_HOME="$HOME/android-sdk"
export ANDROID_AVD_HOME="$HOME/.android/avd"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
export DISPLAY=":1$i"
EMU_PORT=$((5554 + 2*i)); SERIAL="emulator-$EMU_PORT"
VNC_PORT=$((5900 + i)); WEB_PORT=$((6080 + i))
CONF="$HOME/.config/haebom"
GEOMETRY="${HAEBOM_GEOMETRY:-720x1500}"
[ -f "$CONF/env" ] && . "$CONF/env"

wait_x() { for _ in $(seq 60); do xdpyinfo >/dev/null 2>&1 && return 0; sleep 0.5; done; return 1; }
wait_boot() {
  adb -s "$SERIAL" wait-for-device
  for _ in $(seq 600); do
    [ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && return 0
    sleep 2
  done
  return 1
}

case "$part" in
  xvfb)
    rm -f "/tmp/.X1$i-lock"
    exec Xvfb "$DISPLAY" -screen 0 "${GEOMETRY}x24" -nolisten tcp -ac
    ;;
  wm)
    wait_x
    exec openbox --config-file "$CONF/openbox-rc.xml"
    ;;
  emulator)
    wait_x
    exec emulator -avd "haebom-$i" -port "$EMU_PORT" \
      -gpu swiftshader_indirect -no-audio -no-boot-anim -no-snapshot -no-metrics \
      -memory 4096 -cores 4 -change-locale ko-KR
    ;;
  postboot)
    wait_boot
    adb -s "$SERIAL" shell svc power stayon true
    adb -s "$SERIAL" shell locksettings set-disabled true || true
    adb -s "$SERIAL" shell cmd alarm set-timezone Asia/Seoul || adb -s "$SERIAL" shell setprop persist.sys.timezone Asia/Seoul
    adb -s "$SERIAL" shell settings put system screen_off_timeout 2147483647
    adb -s "$SERIAL" shell input keyevent KEYCODE_WAKEUP
    ;;
  vnc)
    wait_x
    wait_boot
    exec x11vnc -display "$DISPLAY" -rfbport "$VNC_PORT" -localhost -rfbauth "$CONF/vnc.pass" \
      -forever -shared -noxdamage -repeat -quiet
    ;;
  web)
    exec websockify --web /usr/share/novnc "0.0.0.0:$WEB_PORT" "127.0.0.1:$VNC_PORT"
    ;;
  *) echo "unknown part $part" >&2; exit 2;;
esac
