#!/usr/bin/env bash
# Startet den 3D-Container und bindet den aktuellen Projektordner als /work ein.
# Kann beliebig oft parallel laufen (kein fester Port). Für Jupyter: ./jupyter.sh
# --user:     Dateien, die im Container entstehen, gehören dir (nicht root)
# --shm-size: mehr gemeinsamer Speicher, sonst bricht MPI bei vielen Kernen ab
# --env-file: Zugangsdaten aus .env (liegt nicht in git)
docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  --shm-size=2g \
  --env-file .env \
  -e MPLCONFIGDIR=/tmp/matplotlib \
  -v "$PWD":/work \
  -w /work \
  ghcr.io/maltinho96/baltic-getm:v0.1 "$@"
