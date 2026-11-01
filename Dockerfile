# baltic-getm: ein Image für 1D und 3D
#   1D: GOTM + FABM (inkl. ERGOM)          -> Befehl: gotm
#   3D: pygetm (GETM) + FABM (inkl. ERGOM)  -> Befehl: python ... (import pygetm)
# Bauen:   docker build -t ghcr.io/maltinho96/baltic-getm:v0.2 .
# Starten: ./run.sh

# Basis: micromamba (conda-forge), feste Version
FROM mambaorg/micromamba@sha256:e1476182cd40eb1f7c0cfae4adec9bfd78f3d7f05c61368306abfdc8939c1198

LABEL org.opencontainers.image.source=https://github.com/maltinho96/baltic-getm

# Feste GOTM-Version (derselbe Stand wie im alten 1D-Image ostsee-gotm)
ARG GOTM_REF=771b3b5a

# Alle folgenden RUN-Befehle laufen in der aktivierten conda-Umgebung
ARG MAMBA_DOCKERFILE_ACTIVATE=1

# 1) Pakete: pygetm, Compiler, NetCDF, Python-Werkzeuge
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml \
    && micromamba clean --all --yes

# 2) GOTM (1D) mit FABM aus dem Quellcode bauen und in die Umgebung installieren
RUN git clone https://github.com/gotm-model/code.git /tmp/gotm-src \
    && cd /tmp/gotm-src \
    && git checkout ${GOTM_REF} \
    && git submodule update --init --recursive \
    && cmake -S /tmp/gotm-src -B /tmp/gotm-build \
         -DGOTM_USE_FABM=ON \
         -DCMAKE_BUILD_TYPE=Release \
         -DCMAKE_Fortran_COMPILER=gfortran \
         -DCMAKE_AR="$(command -v ${AR:-ar})" \
         -DCMAKE_RANLIB="$(command -v ${RANLIB:-ranlib})" \
         -DCMAKE_INSTALL_PREFIX=$CONDA_PREFIX \
    && cmake --build /tmp/gotm-build -j"$(nproc)" \
    && cmake --install /tmp/gotm-build \
    && git -C /tmp/gotm-src rev-parse HEAD > $CONDA_PREFIX/share/GOTM_COMMIT.txt \
    && rm -rf /tmp/gotm-src /tmp/gotm-build

# Arbeitsordner (hier wird der Projektordner eingebunden)
WORKDIR /work
