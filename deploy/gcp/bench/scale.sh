#!/usr/bin/env bash
# 기기를 1대부터 4대까지 늘려 가며 1번 기기의 속도를 잽니다(VM 안의 브라우저, 네트워크 제외).
cd ~/bench; A=~/cf/bin/adb; CF=~/haebom/bin/haebom-cf.sh
: > scale.jsonl
for N in 1 2 3 4; do
  while [ "$($CF list | grep -o webrtc_device_id | wc -l)" -lt "$N" ]; do $CF create >/dev/null 2>&1; done
  # 새 기기의 한국어 설정(프레임워크 재시작)이 끝날 때까지 기다림
  for _ in $(seq 60); do
    ok=0; for i in $(seq 0 $((N-1))); do [ "$($A -s 127.0.0.1:$((6520+i)) shell getprop persist.sys.timezone 2>/dev/null | tr -d '\r')" = "Asia/Seoul" ] && ok=$((ok+1)); done
    [ "$ok" = "$N" ] && break; sleep 3
  done
  sleep 25
  for i in $(seq 0 $((N-1))); do $A -s 127.0.0.1:$((6520+i)) shell "settings put system show_touches 1; input keyevent KEYCODE_HOME" >/dev/null 2>&1; done
  sleep 3
  others=""; for i in $(seq 1 $((N-1))); do others="$others,127.0.0.1:$((6520+i))"; done; others="${others#,}"
  load=$(cut -d' ' -f1 /proc/loadavg); mem=$(awk '/MemAvailable/{printf "%.1f",$2/1048576}' /proc/meminfo)
  idle=$(node bench.js cvd_1-1-1 127.0.0.1:6520 15 off 2>&1 | tail -1)
  if [ "$N" -gt 1 ]; then
    busy=$(node bench.js cvd_1-1-1 127.0.0.1:6520 15 off "$others" 2>&1 | tail -1); bl=$(cut -d' ' -f1 /proc/loadavg)
  else busy=null; bl=null; fi
  echo "{\"n\":$N,\"idle_load\":$load,\"mem_avail_gb\":$mem,\"others_idle\":$idle,\"others_busy\":$busy,\"busy_load\":$bl}" >> scale.jsonl
done
for i in 0 1 2 3; do $A -s 127.0.0.1:$((6520+i)) shell "settings put system show_touches 0; input keyevent KEYCODE_HOME" >/dev/null 2>&1; done
echo DONE >> scale.jsonl
