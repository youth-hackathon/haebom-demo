#!/usr/bin/env bash
# usage: exp.sh <label> <N> <cpus> <xres> <yres> <dpi> <gpu_mode> [jb]
# 설정을 바꿔 기기를 다시 만들고(데이터 지워짐) 1번 기기에서 측정합니다.
set -uo pipefail
label="$1"; N="$2"; C="$3"; X="$4"; Y="$5"; D="$6"; G="$7"; JB="${8:-off}"
cat > "$HOME/.config/haebom/env" <<EOF
HAEBOM_INSTANCES=$N
HAEBOM_CPUS=$C
HAEBOM_XRES=$X
HAEBOM_YRES=$Y
HAEBOM_DPI=$D
HAEBOM_GPU_MODE=$G
EOF
if ! sudo systemctl restart haebom-cuttlefish; then echo "{\"label\":\"$label\",\"error\":\"start failed\"}"; exit 0; fi
A="$HOME/cf/bin/adb"
for s in $($A devices | awk '/device$/{print $1}'); do $A -s "$s" shell "settings put system show_touches 1; input keyevent KEYCODE_HOME" >/dev/null 2>&1; done
sleep 30
load=$(cut -d' ' -f1 /proc/loadavg)
out=$(cd "$HOME/bench" && node bench.js cvd_1-1-1 127.0.0.1:6520 15 "$JB" 2>&1 | tail -1)
echo "{\"label\":\"$label\",\"n\":$N,\"cpus\":$C,\"gpu\":\"$G\",\"idle_load\":$load,\"r\":$out}"
