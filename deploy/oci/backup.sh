#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
destination=${1:?Pass an absolute backup directory on separate storage}
[[ "$destination" = /* ]] || { echo 'Use absolute destination'; exit 1; }
install -d -m 0700 "$destination"
docker compose stop vivi
trap 'docker compose start vivi' EXIT
docker compose run --rm --no-deps --user 0 -v "$destination:/backup" vivi python -c 'import tarfile,time; p="/backup/vivi-"+time.strftime("%Y%m%d-%H%M%S")+".tar.gz"; t=tarfile.open(p,"w:gz"); t.add("/data",arcname="data"); t.close()'
