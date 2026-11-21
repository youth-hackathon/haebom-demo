#!/usr/bin/env bash
# usage: 03-avd.sh <i>   AVD haebom-<i>를 만듭니다(이미 있으면 그대로 둡니다).
set -euo pipefail
i="${1:?index}"
export ANDROID_HOME="$HOME/android-sdk"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
IMAGE="${HAEBOM_IMAGE:-system-images;android-36;google_apis_playstore;x86_64}"
AVD="haebom-$i"; DIR="$HOME/.android/avd/$AVD.avd"
if [ ! -d "$DIR" ]; then
  echo no | avdmanager create avd -n "$AVD" -k "$IMAGE" -d pixel_8
fi
set_kv() { if grep -q "^$1=" "$DIR/config.ini"; then sed -i "s|^$1=.*|$1=$2|" "$DIR/config.ini"; else echo "$1=$2" >> "$DIR/config.ini"; fi; }
set_kv hw.ramSize 4096
set_kv hw.cpu.ncore 4
set_kv hw.keyboard yes
set_kv hw.lcd.width 1080
set_kv hw.lcd.height 2400
set_kv hw.lcd.density 420
set_kv showDeviceFrame no
grep -E '^(hw.lcd|hw.ramSize|hw.cpu.ncore|image.sysdir)' "$DIR/config.ini"
