"""
13_run_gotm.py
Startet einen 1D-Lauf (GOTM + ERGOM). Jeder Lauf bekommt einen eigenen Ordner unter results/,
in den das Setup kopiert wird. So bleibt nachvollziehbar, mit welchen Einstellungen er lief.

Aufruf im Projektordner:
    ./run.sh python scripts/13_run_gotm.py                    # mit bio-optischer Rückkopplung
    ./run.sh python scripts/13_run_gotm.py --no-shade         # ohne (Vergleichslauf)
    ./run.sh python scripts/13_run_gotm.py --kc 0.06          # stärkere Lichtdämpfung durch Algen

Ergebnis: results/gotm_<STATION>_<was>/  mit gotm_out.nc, gotm.yaml, fabm.yaml, log.txt
"""

import argparse
import re
import shutil
import subprocess
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="1D-Lauf GOTM + ERGOM starten")
    parser.add_argument("--station", default="BY15")
    parser.add_argument("--no-shade", action="store_true", help="bio-optische Rückkopplung aus")
    parser.add_argument("--kc", type=float, help="Lichtdämpfung pro Algenbiomasse (Standard 0.03)")
    parser.add_argument("--name", help="eigener Name für den Ergebnisordner")
    args = parser.parse_args()

    setup = Path(f"setups/gotm_{args.station}")
    if not (setup / "gotm.yaml").exists():
        raise SystemExit(f"{setup}/gotm.yaml fehlt. Erst Skript 12 ausführen.")

    # Name des Laufs aus den Einstellungen
    tag = args.name or "_".join(
        ["noshade" if args.no_shade else "shade"] + ([f"kc{args.kc:g}"] if args.kc else [])
    )
    run = Path(f"results/gotm_{args.station}_{tag}")
    if run.exists():
        raise SystemExit(f"{run} gibt es schon. Anderen --name wählen oder alten Ordner umbenennen.")
    shutil.copytree(setup, run)

    # Einstellungen in der Kopie ändern (das Setup selbst bleibt unverändert)
    gotm_yaml = run / "gotm.yaml"
    if args.no_shade:
        text = gotm_yaml.read_text()
        text = re.sub(r"(shade:\s*)true", r"\1false", text, count=1)
        gotm_yaml.write_text(text)
    if args.kc is not None:
        fabm_yaml = run / "fabm.yaml"
        text = re.sub(r"(kc:\s*)[0-9.eE+-]+", rf"\g<1>{args.kc}", fabm_yaml.read_text(), count=1)
        fabm_yaml.write_text(text)

    print(f"Lauf in {run} ...")
    wall = time.perf_counter()
    with (run / "log.txt").open("w") as log:
        res = subprocess.run(["gotm"], cwd=run, stdout=log, stderr=subprocess.STDOUT)
    minutes = (time.perf_counter() - wall) / 60
    if res.returncode != 0:
        print((run / "log.txt").read_text()[-3000:])
        raise SystemExit(f"GOTM ist abgebrochen (siehe {run}/log.txt)")
    print(f"fertig nach {minutes:.1f} min: {run}/gotm_out.nc")
    print(f"Bilder: ./run.sh python scripts/14_plot_gotm.py {run}")


if __name__ == "__main__":
    main()
