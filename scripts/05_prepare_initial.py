"""
05_prepare_initial.py
Bereitet das Startfeld (Temperatur, Salzgehalt) aus der Copernicus-Reanalyse vor.

Problem: Die Reanalyse hat NaN über Land und unter dem Meeresboden. Weil unser
Gitter gröber ist, liegen manche Modellzellen an der Küste oder in der Tiefe
genau dort. Deshalb werden die Lücken aufgefüllt:
  1. senkrecht: unterster gültiger Wert wird nach unten fortgesetzt
  2. waagerecht: Landpunkte bekommen den Wert des nächsten Wasserpunkts
Die Werte im Wasser selbst bleiben unverändert.

Aufruf im Projektordner:
    ./run.sh python scripts/05_prepare_initial.py

Ergebnis:
    data/interim/init_phy_2015-01-01_filled.nc   (thetao, so)
"""

import argparse
from pathlib import Path

import numpy as np
import xarray as xr
from scipy import ndimage

VARIABLES = ["thetao", "so"]   # potentielle Temperatur (°C), praktischer Salzgehalt


def fill_gaps(da: xr.DataArray, zdim: str, ydim: str, xdim: str) -> xr.DataArray:
    """NaN senkrecht nach unten und dann waagerecht mit nächstem Nachbarn füllen."""
    da = da.transpose(zdim, ydim, xdim)
    filled = da.values.astype(float).copy()

    # 1. senkrecht: Schicht für Schicht nach unten, Lücken mit der Schicht darüber füllen
    for k in range(1, filled.shape[0]):
        gap = np.isnan(filled[k])
        filled[k][gap] = filled[k - 1][gap]

    # 2. waagerecht: Indizes des nächsten gültigen Punkts, je Schicht
    for k in range(filled.shape[0]):
        layer = filled[k]
        missing = np.isnan(layer)
        if missing.all():                               # ganz leere Schicht: von oben übernehmen
            filled[k] = filled[k - 1]
            continue
        if missing.any():
            idx = ndimage.distance_transform_edt(missing, return_distances=False,
                                                 return_indices=True)
            filled[k] = layer[tuple(idx)]
    return da.copy(data=filled)


def main() -> None:
    parser = argparse.ArgumentParser(description="Startfeld T/S aus der Reanalyse vorbereiten")
    parser.add_argument("--date", default="2015-01-01")
    args = parser.parse_args()

    src = Path(f"data/raw/cmems/phy/init_{args.date}.nc")
    out = Path(f"data/interim/init_phy_{args.date}_filled.nc")
    if not src.exists():
        raise SystemExit(f"{src} fehlt. Wurde scripts/02_download_cmems.py ausgeführt?")

    ds = xr.open_dataset(src)
    missing = [v for v in VARIABLES if v not in ds]
    if missing:
        raise SystemExit(f"Variablen {missing} fehlen. Vorhanden: {list(ds.data_vars)}")

    # Einzigen Zeitpunkt herausnehmen (Startfeld ist zeitlos)
    if "time" in ds.dims:
        ds = ds.isel(time=0, drop=True)

    sample = ds[VARIABLES[0]]
    zdim = next(d for d in sample.dims if d.lower().startswith("depth"))
    ydim = next(d for d in sample.dims if d.lower().startswith("lat"))
    xdim = next(d for d in sample.dims if d.lower().startswith("lon"))

    result = xr.Dataset()
    for name in VARIABLES:
        print(f"fülle Lücken in {name} ...")
        before = int(ds[name].isnull().sum())
        result[name] = fill_gaps(ds[name], zdim, ydim, xdim).astype("float32")
        print(f"  {before} fehlende Werte aufgefüllt, Bereich "
              f"{float(result[name].min()):.2f} bis {float(result[name].max()):.2f}")

    result.attrs.update(
        title=f"Startfeld T/S {args.date}, Lücken aufgefüllt",
        source=str(src),
        script="scripts/05_prepare_initial.py",
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".nc.part")
    encoding = {v: {"zlib": True, "complevel": 4} for v in VARIABLES}
    result.to_netcdf(tmp, encoding=encoding)
    tmp.rename(out)
    print(f"gespeichert: {out}")


if __name__ == "__main__":
    main()
