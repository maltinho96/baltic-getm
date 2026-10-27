# baltic-getm: 3D-Umgebung mit pygetm (GETM + FABM + ERGOM) und Aufbereitungs-Tools
# Bauen:   docker build -t ghcr.io/maltinho96/baltic-getm:v0.1 .
# Starten: ./run.sh

# Basis: schlankes Linux mit micromamba (Paketmanager für conda-forge)
# FAIR: nach dem ersten erfolgreichen Build "latest" durch die feste Version ersetzen
FROM mambaorg/micromamba@sha256:e1476182cd40eb1f7c0cfae4adec9bfd78f3d7f05c61368306abfdc8939c1198

# Verknüpft das Image mit dem GitHub-Repo
LABEL org.opencontainers.image.source=https://github.com/maltinho96/baltic-getm

# Paketliste ins Image kopieren und alles aus conda-forge installieren
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml \
    && micromamba clean --all --yes

# Arbeitsordner (hier wird der Projektordner eingebunden)
WORKDIR /work
