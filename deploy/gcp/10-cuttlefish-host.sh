#!/usr/bin/env bash
# Cuttlefish 호스트 패키지를 설치합니다(공식 apt 저장소). 다시 돌려도 됩니다.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo curl -fsSL https://us-apt.pkg.dev/doc/repo-signing-key.gpg -o /etc/apt/trusted.gpg.d/artifact-registry.asc
sudo chmod a+r /etc/apt/trusted.gpg.d/artifact-registry.asc
echo "deb https://us-apt.pkg.dev/projects/android-cuttlefish-artifacts android-cuttlefish main" \
  | sudo tee /etc/apt/sources.list.d/artifact-registry.list >/dev/null
sudo apt-get update -y
sudo apt-get install -y cuttlefish-base cuttlefish-user
sudo usermod -aG kvm,cvdnetwork,render "$USER"
dpkg -l | grep cuttlefish
