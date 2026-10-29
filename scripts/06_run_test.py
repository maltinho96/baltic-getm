"""
06_run_test.py
Erster Testlauf, Phase A: nur Physik, geschlossenes Becken (noch kein Rand, keine Flüsse).

Ziel ist nicht Qualität, sondern:
  - läuft das Modell überhaupt stabil durch?
  - bleiben Temperatur und Salz plausibel?
  - wie lange braucht es? (wird am Ende ausgegeben)

Aufruf im Projektordner (z. B. auf 4 Kernen):
    ./run.sh mpiexec -n 4 python scripts/06_run_test.py
    ./run.sh mpiexec -n 4 python scripts/06_run_test.py --stop 2015-01-08   # nur 1 Woche

Ergebnis:
    results/stufe1_test/test_2d.nc   Wasserstand, SST (alle 6 Stunden)
    results/stufe1_test/test_3d.nc   Temperatur, Salz, Strömung (täglich)
"""

import argparse
import datetime
import time
from pathlib import Path

import pygetm
import xarray as xr

ERA5_DIR = Path("data/raw/era5")


def era5_files(start: datetime.datetime, stop: datetime.datetime) -> list[Path]:
    """ERA5-Monatsdateien vom Monat vor dem Start bis zum Monat nach dem Ende."""
    files = []
    first = start.year * 12 + start.month - 2      # Monat vor dem Start (als fortlaufende Zahl)
    last = stop.year * 12 + stop.month              # Monat nach dem Ende
    for m in range(first, last + 1):
        year, month = divmod(m, 12)
        f = ERA5_DIR / f"era5_{year}_{month + 1:02d}.nc"
        if f.exists():
            files.append(f)
    if not files:
        raise SystemExit("Keine passenden ERA5-Dateien gefunden.")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Testlauf Phase A: nur Physik")
    parser.add_argument("--grid", type=Path, default=Path("setups/stufe1_10km/grid.nc"))
    parser.add_argument("--init", type=Path,
                        default=Path("data/interim/init_phy_2015-01-01_filled.nc"))
    parser.add_argument("--start", type=datetime.datetime.fromisoformat, default="2015-01-01")
    parser.add_argument("--stop", type=datetime.datetime.fromisoformat, default="2015-02-01")
    parser.add_argument("--nz", type=int, default=30, help="Anzahl Schichten")
    parser.add_argument("--timestep", type=float, default=45.0,
                        help="2D-Zeitschritt (s); muss unter dem Wert aus 04_build_grid liegen")
    parser.add_argument("--split", type=int, default=30,
                        help="2D-Schritte pro 3D-Schritt (3D-Schritt = timestep * split)")
    parser.add_argument("--out", type=Path, default=Path("results/stufe1_test"))
    args = parser.parse_args()

    # --- Gitter ---
    domain = pygetm.domain.from_xarray(xr.open_dataset(args.grid))

    # --- Physik ---
    airsea = pygetm.airsea.FluxesFromMeteo(
        humidity_measure=pygetm.HumidityMeasure.DEW_POINT_TEMPERATURE,
        shortwave_method=pygetm.DOWNWARD_FLUX,     # Sonnenstrahlung direkt aus ERA5
        calculate_evaporation=True,
    )
    sim = pygetm.Simulation(
        domain,
        runtype=pygetm.RunType.BAROCLINIC,
        airsea=airsea,
        advection_scheme=pygetm.AdvectionScheme.SUPERBEE,
        internal_pressure=pygetm.internal_pressure.ShchepetkinMcwilliams(),
        vertical_coordinates=pygetm.vertical_coordinates.GVC(
            args.nz, Dgamma=40.0, ddu=0.75, ddl=0.5
        ),
        Dcrit=0.2,
        Dmin=0.05,
    )
    # Trübes Küstenwasser: der trübste verfügbare Jerlov-Typ
    sim.radiation.set_jerlov_type(pygetm.Jerlov.Type_III)

    # --- Wetter aus ERA5 (Einheiten auf das umrechnen, was pygetm erwartet) ---
    files = era5_files(args.start, args.stop)
    sim.logger.info(f"ERA5: {len(files)} Dateien von {files[0].name} bis {files[-1].name}")
    sim.airsea.u10.set(pygetm.input.from_nc(files, "u10"))                   # m/s
    sim.airsea.v10.set(pygetm.input.from_nc(files, "v10"))                   # m/s
    sim.airsea.t2m.set(pygetm.input.from_nc(files, "t2m") - 273.15)          # K -> °C
    sim.airsea.d2m.set(pygetm.input.from_nc(files, "d2m") - 273.15)          # K -> °C
    sim.airsea.sp.set(pygetm.input.from_nc(files, "msl"))                    # Pa
    sim.airsea.tcc.set(pygetm.input.from_nc(files, "tcc"))                   # 0-1
    sim.airsea.tp.set(pygetm.input.from_nc(files, "tp") / 3600.0)            # m/h -> m/s
    sim.airsea.swr_downwards.set(pygetm.input.from_nc(files, "ssrd") / 3600.0)  # J/m² pro h -> W/m²

    # --- Startfeld (horizontal und vertikal interpoliert durch pygetm) ---
    sim.temp.set(pygetm.input.from_nc(args.init, "thetao"))
    sim.salt.set(pygetm.input.from_nc(args.init, "so"))
    # Reanalyse liefert potentielle Temperatur + praktischen Salzgehalt,
    # pygetm rechnet mit konservativer Temperatur + absolutem Salzgehalt (TEOS-10)
    sim.density.convert_ts(sim.salt, sim.temp)

    # --- Ausgabe ---
    args.out.mkdir(parents=True, exist_ok=True)
    out2d = sim.output_manager.add_netcdf_file(
        str(args.out / "test_2d.nc"), interval=datetime.timedelta(hours=6)
    )
    out2d.request("zt", "sst", "u1", "v1")
    out3d = sim.output_manager.add_netcdf_file(
        str(args.out / "test_3d.nc"), interval=datetime.timedelta(days=1)
    )
    out3d.request("temp", "salt", "uk", "vk", "NN")

    # --- Rechnen ---
    wall = time.perf_counter()
    sim.start(args.start, timestep=args.timestep, split_factor=args.split,
              report=datetime.timedelta(days=1))
    while sim.time < args.stop:
        sim.advance()
    sim.finish()

    # --- Rechenzeit ---
    hours = (time.perf_counter() - wall) / 3600.0
    days = (args.stop - args.start).days
    sim.logger.info(
        f"Fertig: {days} Modelltage in {hours:.2f} h Rechenzeit "
        f"= {days / hours:.0f} Modelltage pro Stunde; "
        f"1 Modelljahr dauert damit etwa {365 / (days / hours):.1f} h"
    )


if __name__ == "__main__":
    main()
