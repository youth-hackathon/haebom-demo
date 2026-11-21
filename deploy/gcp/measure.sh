#!/usr/bin/env bash
# 켜져 있는 Cuttlefish 기기 대수별 부하를 잽니다: 1분 평균 부하, 남은 메모리, 설정 앱 여는 시간.
set -euo pipefail
ADB="$HOME/cf/bin/adb"
n=$("$ADB" devices | grep -c "device$" || true)
sleep "${1:-60}"   # 부팅 직후의 부하가 가라앉게 기다림
times=""
for s in $("$ADB" devices | awk '/device$/{print $1}'); do
  "$ADB" -s "$s" shell input keyevent KEYCODE_HOME; sleep 2
  "$ADB" -s "$s" shell am force-stop com.android.settings
  t=$("$ADB" -s "$s" shell am start -W -n com.android.settings/.Settings | awk -F': ' '/TotalTime/{print $2}' | tr -d '\r')
  times="$times ${t}ms"
  "$ADB" -s "$s" shell input keyevent KEYCODE_HOME
done
echo "instances=$n nproc=$(nproc) load1=$(cut -d' ' -f1 /proc/loadavg) mem_available_gb=$(awk '/MemAvailable/{printf "%.1f",$2/1048576}' /proc/meminfo) settings_cold_start:$times"
