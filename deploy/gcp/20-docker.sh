#!/usr/bin/env bash
# Docker Engine과 compose 플러그인을 공식 apt 저장소에서 설치합니다. 다시 돌려도 됩니다.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if ! command -v docker >/dev/null; then
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y >/dev/null
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker
sudo docker version --format 'docker {{.Server.Version}}'; sudo docker compose version
