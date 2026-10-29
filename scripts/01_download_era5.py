"""
01_download_era5.py
Lädt stündliche ERA5-Wetterdaten für die Ostsee (Stufe 1) herunter.

Aufruf im Projektordner:
    ./run.sh python scripts/01_download_era5.py --start 2018 --end 2018

Ergebnis pro Monat:
    data/raw/era5/era5_JJJJ_MM.zip        Original vom CDS (falls als ZIP geliefert)
    data/raw/era5/era5_JJJJ_MM.nc         eine zusammengeführte NetCDF-Datei
    data/raw/era5/era5_JJJJ_MM.nc.sha256  Prüfsumme dazu
    data/inventory.csv                    eine Zeile pro Monat

Hintergrund: Der CDS liefert ein ZIP mit zwei NetCDF-Dateien, wenn eine Anfrage
Momentanwerte (Wind, Temperatur, ...) und aufsummierte Werte (Strahlung,
Niederschlag) mischt. Das Skript erkennt das und führt beide Teile zusammen.
Bereits geladene Monate, die noch als ZIP mit .nc-Endung vorliegen, werden
beim nächsten Start automatisch repariert.
"""

import argparse
import calendar
import csv
import datetime
import hashlib
import tempfile
import zipfile
from pathlib import Path

import cdsapi
import xarray as xr

# --- Einstellungen -----------------------------------------------------------

DATASET = "reanalysis-era5-single-levels"

# Gebiet: Ostsee + Kattegat, Reihenfolge [Nord, West, Süd, Ost] in Grad
AREA = [66, 9, 53, 31]

# Variablen für den Antrieb an der Meeresoberfläche
VARIABLES = [
    "10m_u_component_of_wind",           # Wind Ost-West
    "10m_v_component_of_wind",           # Wind Nord-Süd
    "2m_temperature",                    # Lufttemperatur
    "2m_dewpoint_temperature",           # Taupunkt (-> Luftfeuchte)
    "mean_sea_level_pressure",           # Luftdruck
    "total_cloud_cover",                 # Bewölkung
    "surface_solar_radiation_downwards", # Sonnenstrahlung (aufsummiert)
    "total_precipitation",               # Niederschlag (aufsummiert)
]

OUT_DIR = Path("data/raw/era5")
INVENTORY = Path("data/inventory.csv")

# --- Hilfsfunktionen ---------------------------------------------------------


def sha256(path: Path) -> str:
    """Prüfsumme einer Datei berechnen (zeigt später, ob sie unverändert ist)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def add_to_inventory(path: Path, year: int, month: int) -> None:
    """Eine Zeile ins Daten-Inventar schreiben (legt die Datei bei Bedarf an)."""
    new_file = not INVENTORY.exists()
    with open(INVENTORY, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["id", "quelle", "url_oder_doi", "abgerufen",
                             "variablen", "zeitraum", "datei", "sha256", "skript"])
        writer.writerow([
            f"era5_{year}_{month:02d}",
            "ERA5 hourly single levels (Copernicus CDS)",
            "https://doi.org/10.24381/cds.adbb2d47",
            datetime.date.today().isoformat(),
            " ".join(VARIABLES),
            f"{year}-{month:02d}",
            str(path),
            sha256(path),
            "scripts/01_download_era5.py",
        ])


def merge_zip(zip_path: Path, nc_path: Path) -> None:
    """ZIP vom CDS entpacken und alle enthaltenen NetCDF-Dateien zu einer zusammenführen."""
    with tempfile.TemporaryDirectory(dir=OUT_DIR) as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        parts = sorted(Path(tmp).glob("*.nc"))
        if not parts:
            raise RuntimeError(f"Keine NetCDF-Datei in {zip_path} gefunden")
        datasets = [xr.open_dataset(p) for p in parts]
        merged = xr.merge(datasets, compat="override")
        merged.load()                       # alles in den Speicher, dann Dateien schließen
        for ds in datasets:
            ds.close()
    tmp_nc = nc_path.with_suffix(".nc.part")
    merged.to_netcdf(tmp_nc)
    tmp_nc.rename(nc_path)


# --- Hauptprogramm -----------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="ERA5 für die Ostsee herunterladen")
    parser.add_argument("--start", type=int, required=True, help="erstes Jahr")
    parser.add_argument("--end", type=int, required=True, help="letztes Jahr")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = None  # erst verbinden, wenn wirklich etwas geladen werden muss

    for year in range(args.start, args.end + 1):
        for month in range(1, 13):
            target = OUT_DIR / f"era5_{year}_{month:02d}.nc"
            zip_path = OUT_DIR / f"era5_{year}_{month:02d}.zip"

            # Alte Downloads reparieren: ZIP, das fälschlich .nc heißt
            if target.exists() and zipfile.is_zipfile(target):
                print(f"repariere {target.name} (war ein ZIP)")
                target.rename(zip_path)

            # Fertige NetCDF vorhanden? Dann überspringen
            if target.exists():
                print(f"vorhanden, übersprungen: {target}")
                continue

            # Noch nichts da: beim CDS anfragen und herunterladen
            if not zip_path.exists():
                if client is None:
                    client = cdsapi.Client()
                days = calendar.monthrange(year, month)[1]
                request = {
                    "product_type": ["reanalysis"],
                    "variable": VARIABLES,
                    "year": [str(year)],
                    "month": [f"{month:02d}"],
                    "day": [f"{d:02d}" for d in range(1, days + 1)],
                    "time": [f"{h:02d}:00" for h in range(24)],
                    "area": AREA,
                    "data_format": "netcdf",
                    "download_format": "unarchived",
                }
                print(f"lade {year}-{month:02d} ...")
                # Erst in eine .part-Datei laden, damit ein Abbruch keine halbe Datei hinterlässt
                part = OUT_DIR / f"era5_{year}_{month:02d}.part"
                client.retrieve(DATASET, request, str(part))
                part.rename(zip_path if zipfile.is_zipfile(part) else target)

            # ZIP zu einer NetCDF zusammenführen
            if zip_path.exists() and not target.exists():
                print(f"führe zusammen: {zip_path.name} -> {target.name}")
                merge_zip(zip_path, target)

            # Prüfsumme neben die Datei legen und Inventar ergänzen
            Path(f"{target}.sha256").write_text(f"{sha256(target)}  {target.name}\n")
            add_to_inventory(target, year, month)
            print(f"fertig: {target}")


if __name__ == "__main__":
    main()
