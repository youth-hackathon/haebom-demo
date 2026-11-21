#!/usr/bin/env bash
# Android SDK, 에뮬레이터, 시스템 이미지를 받습니다. 다시 돌려도 됩니다.
set -euo pipefail
export ANDROID_HOME="$HOME/android-sdk"
IMAGE="${HAEBOM_IMAGE:-system-images;android-36;google_apis_playstore;x86_64}"
CLT_URL="${CLT_URL:-https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip}"
if [ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]; then
  mkdir -p "$ANDROID_HOME/cmdline-tools"
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/clt.zip" "$CLT_URL"
  unzip -q "$tmp/clt.zip" -d "$tmp"
  rm -rf "$ANDROID_HOME/cmdline-tools/latest"
  mv "$tmp/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
  rm -rf "$tmp"
fi
if ! grep -q 'haebom android env' "$HOME/.profile"; then
  cat >> "$HOME/.profile" <<'P'
# haebom android env
export ANDROID_HOME="$HOME/android-sdk"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
P
fi
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
yes | sdkmanager --licenses >/dev/null || true
sdkmanager "platform-tools" "emulator" "$IMAGE" > /dev/null
sdkmanager --list_installed
