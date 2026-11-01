"""
11_download_station.py
Lädt die Ostsee-Reanalyse (Physik + Biogeochemie) für EINE Station als tägliche Profile.
Gebraucht für das 1D-Modell (GOTM + ERGOM): Startprofile, Tiefenwasser-Nachführung, Vergleich.

Aufruf im Projektordner:
    ./run.sh python scripts/11_download_station.py                 # BY15 (Gotlandtief)
    ./run.sh python scripts/11_download_station.py --station BY5   # Bornholmtief

Ergebnis (wenige MB):
    data/raw/cmems/station/<STATION>_<phy|bgc>_<start>_<end>.nc  (+ .sha256, Zeile in data/inventory.csv)

Zugangsdaten kommen aus der .env (wie bei Skript 02).
"""

import argparse
import importlib
from pathlib import Path

# Hilfsfunktionen aus Skript 02 wiederverwenden (Download, Prüfsumme, Inventar)
cm02 = importlib.import_module("02_download_cmems")

# Bekannte Messstationen (HELCOM-Monitoring): Länge, Breite
STATIONS = {
    "BY15": (20.05, 57.32),   # Gotlandtief, ca. 240 m, oft sauerstofffrei
    "BY5": (15.98, 55.25),    # Bornholmtief, ca. 90 m
    "BY2": (14.08, 55.00),    # Arkonasee, ca. 47 m
}

OUT_DIR = Path("data/raw/cmems/station")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reanalyse-Profile für eine Station laden")
    parser.add_argument("--station", choices=STATIONS, default="BY15")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2020-12-31")
    args = parser.parse_args()

    lon, lat = STATIONS[args.station]
    # Kleiner Kasten um die Station (ca. 5 x 5 km), das nächste Wasser-Gitterfeld wählt Skript 12
    box = dict(
        minimum_longitude=lon - 0.05, maximum_longitude=lon + 0.05,
        minimum_latitude=lat - 0.03, maximum_latitude=lat + 0.03,
    )

    for key, product in cm02.PRODUCTS.items():
        ids = cm02.find_dataset_ids(product)
        daily = cm02.pick_dataset(ids, "P1D")
        target = OUT_DIR / f"{args.station}_{key}_{args.start}_{args.end}.nc"
        if target.exists():
            print(f"vorhanden, übersprungen: {target}")
            continue
        # Ohne Variablenliste: alle Variablen laden (bei einem Punkt ist das trotzdem klein)
        print(f"lade {key} ({daily}) für {args.station} {args.start} bis {args.end} ...")
        cm02.download(daily, target, args.start, args.end, box=box)
        cm02.finish(target, f"cmems_{key}_{args.station}", product, daily, f"{args.start}/{args.end}")


if __name__ == "__main__":
    main()
