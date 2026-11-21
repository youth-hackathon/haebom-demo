#!/usr/bin/env bash
# Cuttlefish를 부팅 때 저절로 뜨게 하는 서비스를 설치합니다. 다시 돌려도 됩니다.
set -euo pipefail
SRC="${1:-$HOME/haebom-src/vm}"
mkdir -p "$HOME/haebom/bin" "$HOME/.config/haebom"
install -m 755 "$SRC/bin/haebom-cf.sh" "$HOME/haebom/bin/"
mkdir -p "$HOME/ho"
[ -f "$HOME/.config/haebom/env" ] || printf "HAEBOM_WARM=1\nHAEBOM_MAX=3\n" > "$HOME/.config/haebom/env"
echo "kernel.apparmor_restrict_unprivileged_userns=0" | sudo tee /etc/sysctl.d/60-haebom-cuttlefish-userns.conf >/dev/null
sudo sysctl --system >/dev/null
sudo install -m 644 "$SRC/systemd/haebom-cuttlefish.service" "$SRC/systemd/haebom-orchestrator.service" "$SRC/systemd/haebom-watch.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable haebom-orchestrator.service haebom-cuttlefish.service haebom-watch.service
echo "service installed"
