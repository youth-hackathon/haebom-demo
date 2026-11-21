#!/usr/bin/env bash
# Cuttlefish 기기를 요청이 올 때 만들고 지웁니다. 만들고 지우는 일은 Cuttlefish에 들어 있는
# Host Orchestrator(127.0.0.1:2080)의 API로 합니다.
#   boot      부팅 때: 지난 기기를 정리하고 HAEBOM_WARM 대를 미리 만듭니다.
#   create    한 대 만들기        delete <group>   한 대 지우기       list   목록
#   watch     새 기기에 한국어·시간대·잠금 해제를 적용하고, HAEBOM_MAX를 넘으면 가장 새것을 지웁니다.
set -uo pipefail
CF="$HOME/cf"; CONF="$HOME/.config/haebom"; ADB="$CF/bin/adb"; HO="http://127.0.0.1:2080"
HAEBOM_WARM=1; HAEBOM_MAX=3
HAEBOM_REVERSE_PORTS="8765 8766"
[ -f "$CONF/env" ] && . "$CONF/env"

wait_ho() { for _ in $(seq 60); do curl -fs -m 2 "$HO/cvds" >/dev/null && return 0; sleep 1; done; return 1; }
create() {
  local r op
  r=$(curl -fs -m 20 -X POST -H 'Content-Type: application/json' -d @"$CONF/create.json" "$HO/cvds") || return 1
  op=$(printf '%s' "$r" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p')
  curl -s -m 600 -X POST "$HO/operations/$op/:wait"; echo
}
serials() { curl -fs -m 5 "$HO/cvds" | grep -o '"status":"Running"[^}]*"adb_serial":"[^"]*"' | sed 's/.*"adb_serial":"\([^"]*\)"/\1/'; }
groups_() { curl -fs -m 5 "$HO/cvds" | grep -o '"group":"[^"]*"' | cut -d'"' -f4 | awk '!s[$0]++'; }

setup_device() {
  local s="$1"
  "$ADB" connect "$s" >/dev/null 2>&1 || true
  timeout 60 "$ADB" -s "$s" wait-for-device || return 1
  for _ in $(seq 90); do [ "$("$ADB" -s "$s" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] && break; sleep 2; done
  "$ADB" -s "$s" root >/dev/null 2>&1 || true; sleep 2; timeout 60 "$ADB" -s "$s" wait-for-device || return 1
  "$ADB" -s "$s" shell 'svc power stayon true; locksettings set-disabled true; settings put system screen_off_timeout 2147483647; settings put global auto_time_zone 0' >/dev/null 2>&1
  if [ "$("$ADB" -s "$s" shell getprop persist.sys.locale | tr -d '\r')" != "ko-KR" ]; then
    "$ADB" -s "$s" shell 'setprop persist.sys.locale ko-KR; stop; start'
    sleep 5; timeout 60 "$ADB" -s "$s" wait-for-device || return 1
    for _ in $(seq 90); do [ "$("$ADB" -s "$s" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] && break; sleep 2; done
    "$ADB" -s "$s" shell svc power stayon true
  fi
  # 시간대는 프레임워크가 다시 뜬 뒤에 넣어야 남습니다. 들어갈 때까지 다시 시도합니다.
  for _ in $(seq 20); do
    "$ADB" -s "$s" shell cmd alarm set-timezone Asia/Seoul >/dev/null 2>&1
    [ "$("$ADB" -s "$s" shell getprop persist.sys.timezone | tr -d '\r')" = "Asia/Seoul" ] && break; sleep 2
  done
  "$ADB" -s "$s" shell 'input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard' >/dev/null 2>&1
  # 기기 안의 127.0.0.1:<포트>가 VM의 같은 포트(artemis 8765, TTS 8766)에 닿게 합니다.
  for port in $HAEBOM_REVERSE_PORTS; do "$ADB" -s "$s" reverse "tcp:$port" "tcp:$port" >/dev/null 2>&1 || echo "reverse $port failed on $s"; done
}

case "${1:-}" in
  boot)
    cvd reset -y >/dev/null 2>&1 || true
    wait_ho || { echo "host orchestrator not reachable" >&2; exit 1; }
    for _ in $(seq 1 "$HAEBOM_WARM"); do create; done
    ;;
  stop) cvd reset -y >/dev/null 2>&1 || true ;;
  create) create ;;
  delete) curl -s -m 120 -X DELETE "$HO/cvds/$2"; echo ;;
  list) curl -s -m 5 "$HO/cvds"; echo ;;
  watch)
    mkdir -p /tmp/haebom-seen
    while true; do
      n=0
      for g in $(groups_); do
        n=$((n+1))
        if [ "$n" -gt "$HAEBOM_MAX" ]; then echo "over HAEBOM_MAX=$HAEBOM_MAX, deleting $g"; curl -s -m 120 -X DELETE "$HO/cvds/$g" >/dev/null; fi
      done
      for s in $(serials); do
        f="/tmp/haebom-seen/${s//[:.]/_}"
        up=$("$ADB" -s "$s" shell 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null | tr -d '\r')
        [ -n "$up" ] || { "$ADB" connect "$s" >/dev/null 2>&1; continue; }
        if [ "$(cat "$f" 2>/dev/null)" != "$up" ]; then
          echo "setting up $s"; setup_device "$s" && echo "$up" > "$f"
        fi
      done
      sleep 5
    done
    ;;
  *) echo "usage: $0 boot|stop|create|delete <group>|list|watch" >&2; exit 2 ;;
esac
