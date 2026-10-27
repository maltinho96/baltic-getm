#!/usr/bin/env bash
# Startet den 3D-Container und bindet den aktuellen Projektordner als /work ein.
# --user:     Dateien, die im Container entstehen, gehören dir (nicht root)
# --shm-size: mehr gemeinsamer Speicher, sonst bricht MPI bei vielen Kernen ab
# -p 8888:    Port für JupyterLab
docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  --shm-size=2g \
  -v "$PWD":/work \
  -w /work \
  -p 8888:8888 \
  ghcr.io/maltinho96/baltic-getm:v0.1 "$@"
