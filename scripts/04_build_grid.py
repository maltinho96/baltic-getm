"""
04_build_grid.py
Baut das Modellgitter für Stufe 1 aus der Bathymetrie der Copernicus-Reanalyse.

Vorgehen:
  1. Bathymetrie (deptho, ~2 km) aus data/raw/cmems/static/ lesen
  2. auf ein gröberes Gitter (Standard 10 km) mitteln:
     Zelle = Wasser, wenn mindestens die Hälfte der Ursprungspunkte Wasser ist
  3. Mindesttiefe setzen, winzige isolierte Becken entfernen
  4. Bathymetrie glätten (nötig für stabile Druckgradienten)
  5. Gitter speichern + Karte als PNG

Aufruf im Projektordner:
    ./run.sh python scripts/04_build_grid.py
    ./run.sh python scripts/04_build_grid.py --resolution 5000 --out setups/stufe2_5km

Ergebnis:
    setups/stufe1_10km/grid.nc    Gitter für pygetm
    setups/stufe1_10km/grid.png   Karte zur Kontrolle
"""

import argparse
from pathlib import Path

import numpy as np
import xarray as xr
from scipy import ndimage

STATIC_DIR = Path("data/raw/cmems/static")
R_EARTH = 6378815.0          # Erdradius wie in pygetm (m)
DEG2RAD = np.pi / 180.0


def load_bathymetry(static_dir: Path) -> xr.DataArray:
    """Bathymetrie 'deptho' aus den statischen Copernicus-Dateien suchen."""
    for f in sorted(static_dir.glob("*.nc")):
        ds = xr.open_dataset(f)
        if "deptho" in ds:
            print(f"Bathymetrie gefunden in {f.name}")
            return ds["deptho"].load()
        ds.close()
    raise SystemExit(f"Keine Variable 'deptho' in {static_dir}/*.nc gefunden. "
                     "Wurde scripts/03_download_bathymetry.py ausgeführt?")


def coord(da: xr.DataArray, prefix: str) -> np.ndarray:
    """1D-Koordinate finden, deren Name mit 'lon' bzw. 'lat' beginnt."""
    for name in da.coords:
        if name.lower().startswith(prefix):
            return da[name].values
    raise SystemExit(f"Keine Koordinate '{prefix}...' in der Bathymetrie gefunden.")


def target_edges(lon: np.ndarray, lat: np.ndarray, resolution: float):
    """Zellgrenzen des Zielgitters, wie pygetm.domain.create_spherical_at_resolution."""
    dlat = resolution / (DEG2RAD * R_EARTH)
    minabslat = min(abs(lat.min()), abs(lat.max()))
    dlon = dlat / np.cos(DEG2RAD * minabslat)
    nx = int(np.ceil((lon.max() - lon.min()) / dlon)) + 1
    ny = int(np.ceil((lat.max() - lat.min()) / dlat)) + 1
    return np.linspace(lon.min(), lon.max(), nx), np.linspace(lat.min(), lat.max(), ny)


def block_average(depth: np.ndarray, lon: np.ndarray, lat: np.ndarray,
                  lon_edges: np.ndarray, lat_edges: np.ndarray):
    """Ursprungspunkte den Zielzellen zuordnen; Wasseranteil und mittlere Tiefe je Zelle."""
    ncx, ncy = len(lon_edges) - 1, len(lat_edges) - 1
    # np.digitize: Index der Zelle, in die ein Punkt fällt (Randpunkte in die letzte Zelle)
    ix = np.clip(np.digitize(lon, lon_edges) - 1, 0, ncx - 1)
    iy = np.clip(np.digitize(lat, lat_edges) - 1, 0, ncy - 1)
    IX, IY = np.meshgrid(ix, iy)                       # Form wie depth: (lat, lon)
    flat = (IY * ncx + IX).ravel()

    water = np.isfinite(depth) & (depth > 0.0)
    total = np.bincount(flat, minlength=ncx * ncy)
    nwet = np.bincount(flat, weights=water.ravel(), minlength=ncx * ncy)
    dsum = np.bincount(flat, weights=np.where(water, depth, 0.0).ravel(),
                       minlength=ncx * ncy)

    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(total > 0, nwet / total, 0.0)
        H = np.where(nwet > 0, dsum / nwet, np.nan)
    return frac.reshape(ncy, ncx), H.reshape(ncy, ncx)


def remove_small_basins(wet: np.ndarray, min_cells: int):
    """Isolierte Wasserflächen mit weniger als min_cells Zellen entfernen."""
    labels, n = ndimage.label(wet)                     # 4er-Nachbarschaft
    if n == 0:
        raise SystemExit("Keine einzige Wasserzelle. Stimmt die Bathymetrie?")
    sizes = np.asarray(ndimage.sum(wet, labels, index=np.arange(1, n + 1)))
    keep = np.arange(1, n + 1)[sizes >= min_cells]
    order = np.argsort(sizes)[::-1]
    print(f"Zusammenhängende Wasserflächen: {n}")
    for rank, i in enumerate(order[:5], start=1):
        print(f"  Becken {rank}: {int(sizes[i])} Zellen")
    removed = int(sizes[sizes < min_cells].sum())
    if removed:
        print(f"  entfernt: {int((sizes < min_cells).sum())} kleine Flächen "
              f"mit zusammen {removed} Zellen")
    if (sizes >= min_cells).sum() > 1:
        print("  HINWEIS: Mehr als ein großes Becken. Wahrscheinlich sind die dänischen"
              " Meerengen bei dieser Auflösung geschlossen. Für den ersten Testlauf ok,"
              " für Stufe 1 mit Rand müssen sie geöffnet werden (siehe grid.png).")
    return np.isin(labels, keep)


def main() -> None:
    parser = argparse.ArgumentParser(description="Modellgitter aus der Reanalyse-Bathymetrie bauen")
    parser.add_argument("--resolution", type=float, default=10000.0, help="Gitterweite (m)")
    parser.add_argument("--hmin", type=float, default=5.0, help="Mindesttiefe (m)")
    parser.add_argument("--min-cells", type=int, default=5,
                        help="kleinere isolierte Wasserflächen werden zu Land")
    parser.add_argument("--rx0", type=float, default=0.2,
                        help="max. Steigungsfaktor beim Glätten (0 = nicht glätten)")
    parser.add_argument("--out", type=Path, default=Path("setups/stufe1_10km"))
    args = parser.parse_args()

    import pygetm  # erst hier laden, damit --help auch ohne pygetm schnell geht

    dep = load_bathymetry(STATIC_DIR)
    lon, lat = coord(dep, "lon"), coord(dep, "lat")
    depth = np.squeeze(dep.values)
    print(f"Ursprungsgitter: {depth.shape[1]} x {depth.shape[0]} Punkte, "
          f"größte Tiefe {np.nanmax(depth):.0f} m")

    lon_edges, lat_edges = target_edges(lon, lat, args.resolution)
    frac, H = block_average(depth, lon, lat, lon_edges, lat_edges)

    wet = frac >= 0.5
    wet = remove_small_basins(wet, args.min_cells)
    H = np.where(wet, np.maximum(H, args.hmin), np.nan)

    domain = pygetm.domain.create_spherical(
        lon_edges, lat_edges, interfaces=True, H=H, z0=0.001
    )
    if args.rx0 > 0:
        print(f"Glätte Bathymetrie auf rx0 <= {args.rx0} ...")
        Hcor = domain.smooth(rx0=args.rx0)
        print(f"  größte Korrektur: {np.abs(Hcor).max():.1f} m")

    maxdt, i, j, Hdt = domain.cfl_check(return_location=True)
    nwet = int(np.isfinite(H).sum())
    print(f"\nZielgitter: {H.shape[1]} x {H.shape[0]} Zellen, davon {nwet} Wasser")
    print(f"größte Tiefe nach Mittelung: {np.nanmax(domain.H[1::2, 1::2]):.0f} m")
    print(f"max. Zeitschritt (2D, CFL): {maxdt:.0f} s  (bestimmt bei {Hdt:.0f} m Tiefe)")

    args.out.mkdir(parents=True, exist_ok=True)
    ds = domain.to_xarray()
    ds.attrs.update(
        title="Modellgitter Ostsee, Stufe 1",
        resolution_m=args.resolution,
        hmin_m=args.hmin,
        rx0=args.rx0,
        source="Copernicus Marine BALTICSEA_MULTIYEAR_PHY_003_011, cmems_mod_bal_phy_my_static",
        script="scripts/04_build_grid.py",
    )
    tmp = args.out / "grid.nc.part"
    ds.to_netcdf(tmp)
    tmp.rename(args.out / "grid.nc")
    print(f"gespeichert: {args.out / 'grid.nc'}")

    plot_grid(domain, args.out / "grid.png", args.resolution)
    print(f"Karte:       {args.out / 'grid.png'}")


def plot_grid(domain, path: Path, resolution: float) -> None:
    """Bathymetrie als Karte speichern (ohne Zusatzpakete wie cmocean)."""
    import matplotlib
    matplotlib.use("Agg")                              # ohne Bildschirm zeichnen
    import matplotlib.pyplot as plt

    lon = domain.lon[::2, ::2]                         # Zellecken
    lat = domain.lat[::2, ::2]
    H = np.ma.masked_where(domain.mask[1::2, 1::2] == 0, domain.H[1::2, 1::2])

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_facecolor("0.85")                           # Land grau
    pc = ax.pcolormesh(lon, lat, H, cmap="viridis_r", shading="flat")
    fig.colorbar(pc, ax=ax, label="Tiefe (m)", shrink=0.8)
    ax.set_aspect(1.0 / np.cos(np.deg2rad(lat.mean())))
    ax.set_xlabel("Länge (°O)")
    ax.set_ylabel("Breite (°N)")
    ax.set_title(f"Modellgitter {resolution / 1000:.0f} km, "
                 f"{int((domain.mask[1::2, 1::2] > 0).sum())} Wasserzellen")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
