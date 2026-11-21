#!/usr/bin/env bash
# VM 안에서 일반 사용자로 실행. 다시 돌려도 됩니다.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
  openjdk-17-jdk-headless unzip curl ca-certificates cpu-checker qemu-kvm \
  xvfb openbox x11vnc novnc websockify xdotool imagemagick x11-utils netcat-openbsd \
  libpulse0 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libxrandr2 libxdamage1 \
  libasound2t64 libgl1 libegl1 libxkbfile1 libx11-xcb1 libxcb-cursor0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-shape0 \
  libxkbcommon-x11-0 libdbus-1-3 libfontconfig1 libsm6 libice6 fonts-noto-cjk
sudo usermod -aG kvm "$USER"
echo "packages ok"
