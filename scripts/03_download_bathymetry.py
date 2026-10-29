"""
03_download_bathymetry.py
Lädt die statischen Felder der Ostsee-Reanalyse (Bathymetrie, Land-See-Maske,
Schichtdicken). Damit passen Gitter, Startfeld und Rand exakt zusammen.

Aufruf im Projektordner:
    ./run.sh python scripts/03_download_bathymetry.py

Ergebnis:
    data/raw/cmems/static/<originaldateien>.nc   (+ .sha256 je Datei)
    data/inventory.csv                           eine Zeile pro Datei
"""

import csv
import datetime
import hashlib
import shutil
import tempfile
from pathlib import Path

import copernicusmarine
import xarray as xr

PRODUCT = "BALTICSEA_MULTIYEAR_PHY_003_011"
DATASET = "cmems_mod_bal_phy_my_static"

OUT_DIR = Path("data/raw/cmems/static")
INVENTORY = Path("data/inventory.csv")


def sha256(path: Path) -> str:
    """Prüfsumme einer Datei berechnen."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def add_to_inventory(path: Path) -> None:
    """Eine Zeile ins Daten-Inventar schreiben."""
    new_file = not INVENTORY.exists()
    with open(INVENTORY, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["id", "quelle", "url_oder_doi", "abgerufen",
                             "variablen", "zeitraum", "datei", "sha256", "skript"])
        writer.writerow([
            f"cmems_static_{path.stem}",
            f"Copernicus Marine {PRODUCT} / {DATASET}",
            f"https://data.marine.copernicus.eu/product/{PRODUCT}/description",
            datetime.date.today().isoformat(),
            "statische Felder (Bathymetrie, Maske, Schichten)",
            "zeitunabhängig",
            str(path),
            sha256(path),
            "scripts/03_download_bathymetry.py",
        ])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if any(OUT_DIR.glob("*.nc")):
        print(f"vorhanden, übersprungen: {OUT_DIR}")
    else:
        # In einen temporären Ordner laden, erst danach verschieben
        # (ein Abbruch hinterlässt so keine halben Dateien)
        with tempfile.TemporaryDirectory(dir=OUT_DIR.parent) as tmp:
            print(f"lade {DATASET} ...")
            copernicusmarine.get(
                dataset_id=DATASET,
                output_directory=tmp,
                no_directories=True,        # Dateien direkt in den Ordner, ohne Unterordner
            )
            files = sorted(Path(tmp).rglob("*.nc"))
            if not files:
                raise RuntimeError("Keine NetCDF-Datei geladen. Bitte Ausgabe oben prüfen.")
            for f in files:
                target = OUT_DIR / f.name
                shutil.move(str(f), target)
                Path(f"{target}.sha256").write_text(f"{sha256(target)}  {target.name}\n")
                add_to_inventory(target)
                print(f"fertig: {target}")

    # Kurzer Überblick, was in den Dateien steckt
    for f in sorted(OUT_DIR.glob("*.nc")):
        with xr.open_dataset(f) as ds:
            print(f"\n{f.name}")
            print(f"  Dimensionen: {dict(ds.sizes)}")
            print(f"  Variablen:   {list(ds.data_vars)}")
            if "deptho" in ds:
                print(f"  größte Tiefe: {float(ds['deptho'].max()):.0f} m")


if __name__ == "__main__":
    main()
