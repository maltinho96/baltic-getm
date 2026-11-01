"""
14_plot_gotm.py
Bilder zu 1D-Läufen (GOTM + ERGOM).

Aufruf im Projektordner:
    ./run.sh python scripts/14_plot_gotm.py results/gotm_BY15_shade
    ./run.sh python scripts/14_plot_gotm.py results/gotm_BY15_shade results/gotm_BY15_noshade   # Vergleich

Bilder (ein Lauf -> <lauf>/figures, zwei Läufe -> figures/<a>_vs_<b>/):
    hovmoeller.png   Zeit-Tiefe-Bilder: Temperatur, Salz, Sauerstoff, Nitrat, Phosphat, Algen
    surface.png      Oberfläche: Temperatur, Algengruppen, Nährstoffe
    vs_reanalysis.png  Modell gegen Copernicus-Reanalyse (wenn Stationsdaten vorhanden)
    difference.png   nur bei zwei Läufen: Unterschied a - b (z. B. Wirkung der bio-optischen Rückkopplung)
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

STATION_DIR = Path("data/raw/cmems/station")


def load(run: Path) -> xr.Dataset:
    """GOTM-Ausgabe laden, Lage-Dimensionen entfernen, Algen aufsummieren."""
    ds = xr.open_dataset(run / "gotm_out.nc").isel(lat=0, lon=0)
    ds["phyto"] = ds.ergom_dia + ds.ergom_fla + ds.ergom_cya
    ds["phyto"].attrs = {"long_name": "Algen gesamt", "units": "mmol N/m3"}
    ds.attrs["run"] = run.name
    return ds


def hovmoeller(ax, ds, var, title, cmap, vmin=None, vmax=None, zmax=None, zero=False):
    """Zeit-Tiefe-Bild einer Variable."""
    depth = -ds.z.values                      # z ist negativ (unter der Oberfläche)
    time = np.broadcast_to(ds.time.values[:, None], depth.shape)
    pc = ax.pcolormesh(time, depth, ds[var].values, cmap=cmap, vmin=vmin, vmax=vmax, shading="nearest")
    if zero:                                  # Sauerstoff: Linie bei 0 = Grenze zu Schwefelwasserstoff
        ax.contour(time, depth, ds[var].values, levels=[0], colors="k", linewidths=0.8)
    ax.set_ylim(zmax or depth.max(), 0)
    ax.set_ylabel("Tiefe (m)")
    ax.set_title(title, fontsize=10)
    plt.colorbar(pc, ax=ax, pad=0.01)


def plot_hovmoeller(ds, out: Path):
    fig, axs = plt.subplots(6, 1, figsize=(11, 15), sharex=True)
    hovmoeller(axs[0], ds, "temp", "Temperatur (°C)", "RdYlBu_r")
    hovmoeller(axs[1], ds, "salt", "Salzgehalt (g/kg)", "viridis")
    lim = float(np.nanmax(np.abs(ds.ergom_oxy)))
    hovmoeller(axs[2], ds, "ergom_oxy", "Sauerstoff (mmol/m³), negativ = Schwefelwasserstoff",
               "RdBu", -lim, lim, zero=True)
    hovmoeller(axs[3], ds, "ergom_nit", "Nitrat (mmol N/m³)", "YlGnBu")
    hovmoeller(axs[4], ds, "ergom_pho", "Phosphat (mmol P/m³)", "PuRd")
    hovmoeller(axs[5], ds, "phyto", "Algen gesamt (mmol N/m³), obere 50 m", "Greens", zmax=50)
    fig.suptitle(ds.attrs["run"])
    fig.tight_layout()
    fig.savefig(out / "hovmoeller.png", dpi=130)
    plt.close(fig)


def plot_surface(ds, out: Path):
    s = ds.isel(z=-1)                          # oberste Schicht
    fig, axs = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    axs[0].plot(s.time, s.temp, "k")
    axs[0].set_ylabel("Temperatur (°C)")
    for var, label, color in (("ergom_dia", "Diatomeen", "tab:blue"),
                              ("ergom_fla", "Flagellaten", "tab:orange"),
                              ("ergom_cya", "Cyanobakterien", "tab:green")):
        axs[1].plot(s.time, s[var], color=color, label=label)
    axs[1].set_ylabel("Algen (mmol N/m³)")
    axs[1].legend(fontsize=8)
    axs[2].plot(s.time, s.ergom_nit + s.ergom_amm, label="DIN (Nitrat + Ammonium)")
    axs[2].plot(s.time, s.ergom_pho * 16, label="Phosphat x 16 (Redfield)")
    axs[2].set_ylabel("mmol N/m³")
    axs[2].legend(fontsize=8)
    for ax in axs:
        ax.grid(alpha=0.3)
    fig.suptitle(f"{ds.attrs['run']}: Oberfläche")
    fig.tight_layout()
    fig.savefig(out / "surface.png", dpi=130)
    plt.close(fig)


def plot_vs_reanalysis(ds, station: str, out: Path):
    """Modell gegen Reanalyse an Oberfläche und Boden."""
    phy = sorted(STATION_DIR.glob(f"{station}_phy_*.nc"))
    bgc = sorted(STATION_DIR.glob(f"{station}_bgc_*.nc"))
    if not phy or not bgc:
        print("  keine Stationsdaten, vs_reanalysis.png übersprungen")
        return
    lon, lat = float(ds.lon), float(ds.lat)
    ref = xr.merge([xr.open_dataset(phy[0]), xr.open_dataset(bgc[0])], compat="override", join="left")
    ref = ref.sel(longitude=lon, latitude=lat, method="nearest").sel(time=slice(ds.time[0], ds.time[-1]))
    deepest = int(ref.so.isel(time=0).notnull().sum()) - 1

    rows = [("temp", "thetao", "Temperatur (°C)"), ("salt", "so", "Salzgehalt"),
            ("ergom_oxy", "o2", "Sauerstoff (mmol/m³)"), ("ergom_nit", "no3", "Nitrat (mmol/m³)"),
            ("ergom_pho", "po4", "Phosphat (mmol/m³)")]
    rows = [r for r in rows if r[1] in ref]
    fig, axs = plt.subplots(len(rows), 2, figsize=(12, 2.4 * len(rows)), sharex=True)
    for i, (mvar, rvar, label) in enumerate(rows):
        for j, (zi, ri, where) in enumerate(((-1, 0, "Oberfläche"), (0, deepest, "Boden"))):
            ax = axs[i, j]
            ax.plot(ds.time, ds[mvar].isel(z=zi), "k", label="Modell (GOTM + ERGOM)")
            ax.plot(ref.time, ref[rvar].isel(depth=ri), "tab:red", alpha=0.8, label="Reanalyse")
            ax.set_title(f"{label}, {where}", fontsize=9)
            ax.grid(alpha=0.3)
    axs[0, 0].legend(fontsize=8)
    fig.suptitle(f"{ds.attrs['run']} gegen Copernicus-Reanalyse ({station})")
    fig.tight_layout()
    fig.savefig(out / "vs_reanalysis.png", dpi=130)
    plt.close(fig)


def plot_difference(a, b, out: Path):
    """Unterschied zweier Läufe, z. B. mit minus ohne bio-optische Rückkopplung."""
    fig, axs = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
    diff = a.temp - b.temp
    lim = float(np.nanmax(np.abs(diff.values))) or 0.1
    depth = -a.z.values
    time = np.broadcast_to(a.time.values[:, None], depth.shape)
    pc = axs[0].pcolormesh(time, depth, diff.values, cmap="RdBu_r", vmin=-lim, vmax=lim, shading="nearest")
    axs[0].set_ylim(60, 0)
    axs[0].set_ylabel("Tiefe (m)")
    axs[0].set_title(f"Temperatur {a.attrs['run']} minus {b.attrs['run']} (°C), obere 60 m", fontsize=10)
    plt.colorbar(pc, ax=axs[0], pad=0.01)
    axs[1].plot(a.time, a.temp.isel(z=-1) - b.temp.isel(z=-1), "k")
    axs[1].axhline(0, color="grey", lw=0.5)
    axs[1].set_ylabel("Δ Oberflächentemp. (°C)")
    axs[2].plot(a.time, a.phyto.isel(z=-1), label=a.attrs["run"])
    axs[2].plot(b.time, b.phyto.isel(z=-1), label=b.attrs["run"])
    axs[2].set_ylabel("Algen oben (mmol N/m³)")
    axs[2].legend(fontsize=8)
    for ax in axs[1:]:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "difference.png", dpi=130)
    plt.close(fig)
    d = (a.temp.isel(z=-1) - b.temp.isel(z=-1))
    summer = d.where(d.time.dt.month.isin([6, 7, 8]), drop=True)
    print(f"  Oberflächentemperatur a - b: Mittel {float(d.mean()):+.3f} °C, "
          f"Sommer (JJA) {float(summer.mean()):+.3f} °C, max {float(d.max()):+.3f} °C")


def main() -> None:
    runs = [Path(p.rstrip("/")) for p in sys.argv[1:]]
    if len(runs) not in (1, 2):
        raise SystemExit(__doc__)
    data = [load(r) for r in runs]
    station = runs[0].name.split("_")[1]          # results/gotm_<STATION>_<was>
    if len(runs) == 1:
        out = runs[0] / "figures"
    else:
        out = Path("figures") / f"{runs[0].name}_vs_{runs[1].name}"
    out.mkdir(parents=True, exist_ok=True)

    plot_hovmoeller(data[0], out)
    plot_surface(data[0], out)
    plot_vs_reanalysis(data[0], station, out)
    if len(runs) == 2:
        plot_difference(data[0], data[1], out)
    print(f"Bilder in {out}/")


if __name__ == "__main__":
    main()
