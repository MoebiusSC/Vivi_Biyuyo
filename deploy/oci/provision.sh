#!/usr/bin/env bash
# Ubuntu 24.04, ARM64 or AMD64. Run with sudo on the intended VM.
set -euo pipefail
test "$(id -u)" -eq 0 || { echo 'Run with sudo'; exit 1; }
. /etc/os-release
test "$ID" = ubuntu || { echo 'Requires Ubuntu'; exit 1; }
apt-get update
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' "$(dpkg --print-architecture)" "$VERSION_CODENAME" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
install -d -m 0750 /opt/vivi-biyuyo
echo 'Docker installed. Clone an approved release into /opt/vivi-biyuyo; follow docs/OCI.md.'
