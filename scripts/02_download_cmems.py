"""
02_download_cmems.py
Lädt die Ostsee-Reanalyse von Copernicus Marine (Physik + Biogeochemie) für Stufe 1.

Zwei Teile:
  init      Startfeld: ganze Ostsee in 3D, ein einziger Tag (Tagesmittel)
  boundary  Randgebiet Kattegat/Skagerrak: Monatsmittel, eine Datei pro Jahr

Aufruf im Projektordner:
    ./run.sh python scripts/02_download_cmems.py --what all
    ./run.sh python scripts/02_download_cmems.py --what init
    ./run.sh python scripts/02_download_cmems.py --what boundary --start 2015 --end 2021
    ./run.sh python scripts/02_download_cmems.py --list     # nur anzeigen, welche Datensätze es gibt

Ergebnis:
    data/raw/cmems/<phy|bgc>/init_2015-01-01.nc
    data/raw/cmems/<phy|bgc>/boundary_monthly_JJJJ.nc
    jeweils mit .sha256 daneben, plus Zeilen in data/inventory.csv

Zugangsdaten kommen aus der .env (COPERNICUSMARINE_SERVICE_USERNAME / _PASSWORD).
Bereits vorhandene Dateien werden übersprungen, ein Abbruch hinterlässt keine halben Dateien.
"""

import argparse
import csv
import datetime
import hashlib
from pathlib import Path

import copernicusmarine

# --- Einstellungen -----------------------------------------------------------

# Copernicus-Marine-Produkte (Ostsee-Reanalyse)
PRODUCTS = {
    "phy": "BALTICSEA_MULTIYEAR_PHY_003_011",   # Temperatur, Salz, Strömung, Wasserstand
    "bgc": "BALTICSEA_MULTIYEAR_BGC_003_012",   # Nährstoffe, Sauerstoff, Chlorophyll
}

# Startdatum des Modells
INIT_DATE = "2015-01-01"

# Randgebiet Kattegat/Skagerrak (Grad). Großzügig gewählt; wird angepasst,
# sobald das Modellgitter und die genaue Randlinie feststehen.
BOUNDARY_BOX = dict(
    minimum_longitude=9.5,
    maximum_longitude=12.0,
    minimum_latitude=57.0,
    maximum_latitude=58.5,
)

OUT_DIR = Path("data/raw/cmems")
INVENTORY = Path("data/inventory.csv")

# --- Hilfsfunktionen ---------------------------------------------------------


def sha256(path: Path) -> str:
    """Prüfsumme einer Datei berechnen."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def add_to_inventory(path: Path, entry_id: str, product: str, dataset: str, period: str) -> None:
    """Eine Zeile ins Daten-Inventar schreiben (legt die Datei bei Bedarf an)."""
    new_file = not INVENTORY.exists()
    with open(INVENTORY, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["id", "quelle", "url_oder_doi", "abgerufen",
                             "variablen", "zeitraum", "datei", "sha256", "skript"])
        writer.writerow([
            entry_id,
            f"Copernicus Marine {product} / {dataset}",
            f"https://data.marine.copernicus.eu/product/{product}/description",
            datetime.date.today().isoformat(),
            "alle Variablen des Datensatzes",
            period,
            str(path),
            sha256(path),
            "scripts/02_download_cmems.py",
        ])


def find_dataset_ids(product_id: str) -> list[str]:
    """Alle Datensatz-IDs eines Produkts aus dem Copernicus-Katalog holen."""
    catalogue = copernicusmarine.describe(product_id=product_id)
    data = catalogue.model_dump() if hasattr(catalogue, "model_dump") else catalogue

    ids = []

    def walk(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get("dataset_id"), str):
                ids.append(obj["dataset_id"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    return sorted(set(ids))


def pick_dataset(ids: list[str], freq: str) -> str:
    """Datensatz mit gewünschter Zeitauflösung wählen (P1D = täglich, P1M = monatlich).
    Bevorzugt die eigentliche Reanalyse ('_my_') vor der Verlängerung ('_myint_')."""
    matches = [i for i in ids if f"_{freq}" in i]
    if not matches:
        raise RuntimeError(f"Kein Datensatz mit {freq} gefunden. Vorhanden: {ids}")
    preferred = [i for i in matches if "_my_" in i]
    return (preferred or matches)[0]


def download(dataset_id: str, target: Path, start: str, end: str, box: dict | None) -> None:
    """Ausschnitt laden. Erst unter tmp_-Namen speichern, dann umbenennen."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"tmp_{target.name}")
    if tmp.exists():
        tmp.unlink()                        # Rest eines früheren Abbruchs entfernen
    copernicusmarine.subset(
        dataset_id=dataset_id,
        start_datetime=f"{start}T00:00:00",
        end_datetime=f"{end}T23:59:59",
        output_directory=str(tmp.parent),
        output_filename=tmp.name,
        **(box or {}),                      # ohne Box: ganzes Gebiet des Datensatzes
    )
    tmp.rename(target)


def finish(target: Path, entry_id: str, product: str, dataset: str, period: str) -> None:
    """Prüfsumme schreiben und Inventar ergänzen."""
    Path(f"{target}.sha256").write_text(f"{sha256(target)}  {target.name}\n")
    add_to_inventory(target, entry_id, product, dataset, period)
    print(f"fertig: {target}")


# --- Hauptprogramm -----------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Copernicus-Marine-Reanalyse für die Ostsee laden")
    parser.add_argument("--what", choices=["init", "boundary", "all"], default="all")
    parser.add_argument("--start", type=int, default=2015, help="erstes Jahr für den Rand")
    parser.add_argument("--end", type=int, default=2021, help="letztes Jahr für den Rand")
    parser.add_argument("--list", action="store_true", help="nur verfügbare Datensätze anzeigen")
    args = parser.parse_args()

    for key, product in PRODUCTS.items():
        ids = find_dataset_ids(product)

        if args.list:
            print(f"\n{product}:")
            for i in ids:
                print(f"  {i}")
            continue

        # --- Startfeld: ganze Ostsee, ein Tag, Tagesmittel ---
        if args.what in ("init", "all"):
            daily = pick_dataset(ids, "P1D")
            target = OUT_DIR / key / f"init_{INIT_DATE}.nc"
            if target.exists():
                print(f"vorhanden, übersprungen: {target}")
            else:
                print(f"lade Startfeld {key} ({daily}) für {INIT_DATE} ...")
                download(daily, target, INIT_DATE, INIT_DATE, box=None)
                finish(target, f"cmems_{key}_init_{INIT_DATE}", product, daily, INIT_DATE)

        # --- Rand: Kattegat/Skagerrak, Monatsmittel, eine Datei pro Jahr ---
        if args.what in ("boundary", "all"):
            monthly = pick_dataset(ids, "P1M")
            for year in range(args.start, args.end + 1):
                target = OUT_DIR / key / f"boundary_monthly_{year}.nc"
                if target.exists():
                    print(f"vorhanden, übersprungen: {target}")
                    continue
                print(f"lade Rand {key} ({monthly}) für {year} ...")
                download(monthly, target, f"{year}-01-01", f"{year}-12-31", box=BOUNDARY_BOX)
                finish(target, f"cmems_{key}_boundary_{year}", product, monthly, str(year))


if __name__ == "__main__":
    main()
