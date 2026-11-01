"""
12_prepare_gotm_station.py
Baut ein 1D-Setup (GOTM + FABM/ERGOM) für eine Station aus ERA5 und der Copernicus-Reanalyse.

Voraussetzung:
    data/raw/era5/era5_JJJJ_MM.nc              (Skript 01)
    data/raw/cmems/station/<STATION>_*.nc      (Skript 11)

Aufruf im Projektordner:
    ./run.sh python scripts/12_prepare_gotm_station.py
    ./run.sh python scripts/12_prepare_gotm_station.py --station BY15 --start 2015-01-01 --stop 2021-01-01

Ergebnis: setups/gotm_<STATION>/
    gotm.yaml          GOTM-Einstellungen (Ort, Zeit, Gitter, Antrieb, Ausgabe)
    fabm.yaml          ERGOM-Parameter (Vorlage FABM-Testfall gotm/ergom, Ostseewerte)
    meteo.dat          ERA5 stündlich: Wind, Luftdruck, Lufttemperatur, Taupunkt, Wolken
    fluxes.dat         ERA5 stündlich: Sonnenstrahlung, Niederschlag (Stundenmittel)
    ts_profiles.dat    Reanalyse täglich: Temperatur, Salz (Start + Nachführung im Tiefenwasser)
    bgc_profiles.dat   Reanalyse am Starttag: Nitrat, Ammonium, Phosphat, Sauerstoff (nur Start)

Warum Nachführung im Tiefenwasser? Ein 1D-Modell kennt keine seitlichen Einströme aus der Nordsee.
Das Salz und die Temperatur unter der Halokline werden deshalb sanft (Zeitskala --relax-days) an die
Reanalyse angeglichen. Die Biologie (ERGOM) läuft dagegen frei.
"""

import argparse
import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ERA5_DIR = Path("data/raw/era5")
STATION_DIR = Path("data/raw/cmems/station")

STATIONS = {  # Länge, Breite (wie Skript 11)
    "BY15": (20.05, 57.32),
    "BY5": (15.98, 55.25),
    "BY2": (14.08, 55.00),
}

# Mögliche Variablennamen in der Reanalyse -> ERGOM-Variable
BGC_NAMES = {
    "nit": ["no3", "nitrate"],
    "amm": ["nh4", "ammonium"],
    "pho": ["po4", "phosphate"],
    "oxy": ["o2", "oxygen"],
}
BGC_FALLBACK = {"nit": 5.0, "amm": 0.1, "pho": 0.6, "oxy": 300.0}  # falls eine Variable fehlt


# --- Hilfsfunktionen ---------------------------------------------------------


def find_var(ds: xr.Dataset, candidates: list[str]) -> str | None:
    """Ersten passenden Variablennamen finden (Groß-/Kleinschreibung egal)."""
    lower = {v.lower(): v for v in ds.data_vars}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def nearest_water_column(ds: xr.Dataset, var: str, lon: float, lat: float) -> xr.Dataset:
    """Nächste Gitterzelle mit den meisten gültigen Tiefenstufen nehmen."""
    first = ds[var].isel(time=0)
    nvalid = first.notnull().sum("depth")
    dist = np.hypot((ds.longitude - lon) * np.cos(np.radians(lat)), ds.latitude - lat)
    # Wasserzellen bevorzugen, dann die tiefste, dann die nächste
    score = xr.where(nvalid > 0, nvalid * 1000.0 - dist * 1e4, -np.inf)
    idx = np.unravel_index(int(np.argmax(score.values)), score.shape)
    point = ds.isel({score.dims[0]: idx[0], score.dims[1]: idx[1]})
    print(f"  Gitterzelle: {float(point.longitude):.3f} E, {float(point.latitude):.3f} N, "
          f"{int(nvalid.values[idx])} Tiefenstufen")
    return point


def write_profiles(path: Path, times, depths: np.ndarray, columns: list[np.ndarray]) -> None:
    """GOTM-Profildatei: Kopfzeile 'Datum Zeit Anzahl 2', dann 'Tiefe(negativ) Wert1 Wert2 ...'
    von oben nach unten. columns: Liste von Arrays (Zeit x Tiefe)."""
    with path.open("w") as f:
        for it, t in enumerate(times):
            values = np.stack([c[it] for c in columns], axis=1)
            ok = np.all(np.isfinite(values), axis=1)
            if ok.sum() < 2:
                continue
            f.write(f"{pd.Timestamp(t):%Y-%m-%d %H:%M:%S}  {int(ok.sum())}  2\n")
            for z, row in zip(depths[ok], values[ok]):
                f.write(f"{-z:9.2f} " + " ".join(f"{v:10.4f}" for v in row) + "\n")


def era5_point(lon: float, lat: float, start: datetime.datetime, stop: datetime.datetime) -> pd.DataFrame:
    """ERA5 an der Station (nächster Gitterpunkt) als Tabelle, Einheiten für GOTM umgerechnet."""
    files = sorted(ERA5_DIR.glob("era5_*.nc"))
    if not files:
        raise SystemExit(f"Keine ERA5-Dateien in {ERA5_DIR}")
    frames = []
    for f in files:
        with xr.open_dataset(f) as ds:
            if "valid_time" in ds.dims:
                ds = ds.rename({"valid_time": "time"})
            p = ds.sel(longitude=lon, latitude=lat, method="nearest")
            # Zusatzdimensionen (z. B. expver bei ganz neuen Daten) entfernen
            for d in list(p.dims):
                if d != "time":
                    p = p.isel({d: 0})
            frames.append(p[["u10", "v10", "msl", "t2m", "d2m", "tcc", "ssrd", "tp"]]
                          .to_dataframe()[["u10", "v10", "msl", "t2m", "d2m", "tcc", "ssrd", "tp"]])
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated()]
    df = df.loc[(df.index >= start - datetime.timedelta(hours=2)) & (df.index <= stop + datetime.timedelta(hours=2))]
    if df.empty:
        raise SystemExit("Keine ERA5-Daten im gewünschten Zeitraum.")
    gaps = df.index.to_series().diff().dt.total_seconds().div(3600).fillna(1)
    if gaps.max() > 1.5:
        where = gaps.idxmax()
        raise SystemExit(f"Lücke in ERA5 vor {where} ({gaps.max():.0f} h). Fehlende Monate nachladen (Skript 01).")
    if df.index[0] > start or df.index[-1] < stop - datetime.timedelta(hours=1):
        raise SystemExit(f"ERA5 reicht nur von {df.index[0]} bis {df.index[-1]}. --start/--stop anpassen.")
    print(f"  ERA5: {df.index[0]} bis {df.index[-1]}, {len(df)} Stunden")
    return df


# --- Hauptprogramm -----------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="1D-Setup GOTM + ERGOM für eine Station bauen")
    parser.add_argument("--station", choices=STATIONS, default="BY15")
    parser.add_argument("--start", type=datetime.datetime.fromisoformat, default="2015-01-01")
    parser.add_argument("--stop", type=datetime.datetime.fromisoformat, default="2021-01-01")
    parser.add_argument("--nlev", type=int, default=120, help="Anzahl Schichten")
    parser.add_argument("--dt", type=float, default=600.0, help="Zeitschritt in s")
    parser.add_argument("--relax-days", type=float, default=10.0,
                        help="Nachführung von T/S im Tiefenwasser (Tage)")
    parser.add_argument("--relax-below", type=float, default=70.0,
                        help="Nachführung erst unterhalb dieser Tiefe (m), etwa die Halokline")
    args = parser.parse_args()

    lon, lat = STATIONS[args.station]
    out = Path(f"setups/gotm_{args.station}")
    out.mkdir(parents=True, exist_ok=True)
    print(f"Station {args.station} ({lon} E, {lat} N) -> {out}")

    # --- 1) Wetter aus ERA5 ---
    met = era5_point(lon, lat, args.start, args.stop)
    t = met.index
    meteo = pd.DataFrame({
        "u10": met.u10, "v10": met.v10,              # m/s
        "airp": met.msl,                             # Pa
        "airt": met.t2m - 273.15,                    # K -> °C
        "dew": met.d2m - 273.15,                     # K -> °C (Taupunkt)
        "cloud": met.tcc.clip(0, 1),                 # 0-1
    }, index=t)
    # Strahlung und Niederschlag sind in ERA5 Summen über die Stunde VOR dem Zeitstempel.
    # Als Mittelwert gehören sie zur Mitte dieser Stunde -> 30 min früher.
    fluxes = pd.DataFrame({
        "swr": (met.ssrd / 3600.0).clip(lower=0).to_numpy(),    # J/m² pro h -> W/m² (abwärts)
        "precip": (met.tp / 3600.0).clip(lower=0).to_numpy(),   # m pro h -> m/s
    }, index=t - pd.Timedelta(minutes=30))
    for name, df in (("meteo.dat", meteo), ("fluxes.dat", fluxes)):
        with (out / name).open("w") as f:
            for ti, row in zip(df.index, df.to_numpy()):
                f.write(f"{ti:%Y-%m-%d %H:%M:%S} " + " ".join(f"{v:12.6g}" for v in row) + "\n")
    print("  meteo.dat, fluxes.dat geschrieben")

    # --- 2) Temperatur und Salz aus der Reanalyse ---
    phy_file = sorted(STATION_DIR.glob(f"{args.station}_phy_*.nc"))
    bgc_file = sorted(STATION_DIR.glob(f"{args.station}_bgc_*.nc"))
    if not phy_file or not bgc_file:
        raise SystemExit(f"Stationsdaten fehlen. Erst: ./run.sh python scripts/11_download_station.py --station {args.station}")
    phy = nearest_water_column(xr.open_dataset(phy_file[0]), "so", lon, lat)
    phy = phy.sel(time=slice(args.start - datetime.timedelta(days=1), args.stop + datetime.timedelta(days=1)))
    # GOTM braucht ein Profil NACH dem Ende des Laufs. Fehlt es (Reanalyse endet am 31.12.),
    # wird das letzte Profil einen Tag später wiederholt.
    last = pd.Timestamp(phy.time.values[-1]).to_pydatetime()
    if last < args.stop:
        extra = phy.isel(time=[-1]).assign_coords(time=[np.datetime64(args.stop + datetime.timedelta(days=1))])
        phy = xr.concat([phy, extra], dim="time")
        print(f"  Hinweis: Reanalyse endet {last:%Y-%m-%d}, letztes Profil bis {args.stop:%Y-%m-%d} fortgeschrieben")
    depths = phy.depth.values
    write_profiles(out / "ts_profiles.dat", phy.time.values, depths,
                   [phy.thetao.values, phy.so.values])
    valid = depths[np.isfinite(phy.so.isel(time=0).values)]
    water_depth = float(np.ceil(valid.max() + 2.0))     # unterste Stufe ist Zellmitte -> etwas tiefer
    print(f"  ts_profiles.dat geschrieben, Wassertiefe {water_depth:.0f} m")

    # --- 3) Nährstoffe und Sauerstoff am Starttag ---
    bgc_all = xr.open_dataset(bgc_file[0])
    ref = find_var(bgc_all, BGC_NAMES["oxy"]) or list(bgc_all.data_vars)[0]
    bgc = nearest_water_column(bgc_all, ref, lon, lat).sel(time=args.start, method="nearest")
    cols, used = [], {}
    for ergom_var, names in BGC_NAMES.items():
        name = find_var(bgc, names)
        if name is None:
            print(f"  Hinweis: {ergom_var} nicht in der Reanalyse, nehme konstant {BGC_FALLBACK[ergom_var]}")
            cols.append(np.full((1, bgc.depth.size), BGC_FALLBACK[ergom_var]))
        else:
            cols.append(bgc[name].values[np.newaxis, :])
            used[ergom_var] = name
    write_profiles(out / "bgc_profiles.dat", [bgc.time.values], bgc.depth.values, cols)
    print(f"  bgc_profiles.dat geschrieben ({used})")

    # --- 4) ERGOM-Einstellungen ---
    (out / "fabm.yaml").write_text(FABM_YAML)

    # --- 5) GOTM-Einstellungen ---
    relax_s = args.relax_days * 86400.0
    h_b = max(water_depth - args.relax_below, 0.0)
    (out / "gotm.yaml").write_text(GOTM_YAML.format(
        station=args.station, lat=lat, lon=lon, depth=water_depth,
        start=f"{args.start:%Y-%m-%d %H:%M:%S}", stop=f"{args.stop:%Y-%m-%d %H:%M:%S}",
        dt=args.dt, nlev=args.nlev, h_b=h_b, tau_b=relax_s, relax_below=args.relax_below,
        relax_days=args.relax_days,
    ))
    print(f"fertig: {out}/gotm.yaml  ->  weiter mit Skript 13 (Lauf starten)")


# --- Vorlagen ------------------------------------------------------------------
# Nur die Einstellungen, die vom GOTM-Standard abweichen. Alle Möglichkeiten zeigt:
#   ./run.sh gotm --write_yaml alles.yaml --detail full

GOTM_YAML = """\
version: 7
title: GOTM + ERGOM {station}
location:
   name: {station}
   latitude: {lat}
   longitude: {lon}
   depth: {depth}                     # Wassertiefe [m] aus der Reanalyse
time:
   start: {start}
   stop: {stop}
   dt: {dt}                           # Zeitschritt [s]
grid:
   nlev: {nlev}                       # Schichten
   method: analytical
   ddu: 1.0                           # oben feinere Schichten
   ddl: 0.5                           # unten etwas feinere Schichten
temperature:                          # Start + Nachführung im Tiefenwasser
   method: file
   file: ts_profiles.dat
   column: 1
   type: potential                    # Reanalyse liefert potentielle Temperatur (thetao)
   relax:
      tau: 1.0e15                     # oben: keine Nachführung
      h_b: {h_b}                      # Dicke der Bodenschicht mit Nachführung [m] (unterhalb {relax_below} m)
      tau_b: {tau_b}                  # Zeitskala [s] = {relax_days} Tage
salinity:
   method: file
   file: ts_profiles.dat
   column: 2
   type: practical
   relax:
      tau: 1.0e15
      h_b: {h_b}
      tau_b: {tau_b}
surface:
   fluxes:
      method: kondo                   # Wärme- und Impulsfluss aus dem Wetter berechnen
   u10:
      method: file
      file: meteo.dat
      column: 1
   v10:
      method: file
      file: meteo.dat
      column: 2
   airp:
      method: file
      file: meteo.dat
      column: 3
   airt:
      method: file
      file: meteo.dat
      column: 4
   hum:
      method: file
      file: meteo.dat
      column: 5
      type: dew_point
   cloud:
      method: file
      file: meteo.dat
      column: 6
   swr:
      method: file
      file: fluxes.dat
      column: 1
      type: 2                         # abwärts gerichtete Strahlung (Albedo rechnet GOTM)
   precip:
      method: file
      file: fluxes.dat
      column: 2
   calc_evaporation: true
   longwave_radiation:
      method: clark
light_extinction:
   method: jerlov-iii                 # Hintergrundtrübung küstennahes Wasser; Algen kommen über FABM dazu
fabm:
   use: true
   freshwater_impact: true
   feedbacks:
      shade: true                     # bio-optische Rückkopplung: Algen dämpfen Licht -> Erwärmung oben
   repair_state: true
   input:                             # Startprofile (ohne relax_tau = nur Startwert, keine Nachführung)
      ergom/nit:
         method: file
         file: bgc_profiles.dat
         column: 1
      ergom/amm:
         method: file
         file: bgc_profiles.dat
         column: 2
      ergom/pho:
         method: file
         file: bgc_profiles.dat
         column: 3
      ergom/oxy:
         method: file
         file: bgc_profiles.dat
         column: 4
output:
   gotm_out:                          # -> gotm_out.nc
      time_unit: day
      time_step: 1
      time_method: mean               # Tagesmittel
      variables:
         - source: /*                 # alles aus GOTM und FABM
"""

FABM_YAML = """\
# ERGOM (gotm/ergom), Werte aus dem FABM-Testfall testcases/fabm-gotm-ergom.yaml
# Startwerte von nit, amm, pho, oxy kommen aus bgc_profiles.dat (siehe gotm.yaml, fabm/input)
instances:
  ergom:
    model: gotm/ergom
    parameters:
      sfl_po: 0.055       # Phosphat-Eintrag aus der Luft (mmol P/m2/d)
      sfl_ni: 0.45        # Nitrat-Eintrag aus der Luft (mmol N/m2/d)
      sfl_am: 0.36        # Ammonium-Eintrag aus der Luft (mmol N/m2/d)
      fluff: true         # Sediment-Oberschicht (Fluff) mitrechnen
      p10: 0.0045         # Hintergrund Diatomeen (mmol N/m3)
      p20: 0.0045         # Hintergrund Flagellaten (mmol N/m3)
      p30: 0.0045         # Hintergrund Cyanobakterien (mmol N/m3)
      zo0: 0.0045         # Hintergrund Zooplankton (mmol N/m3)
      kc: 0.03            # Lichtdämpfung pro Algenbiomasse (m2/mmol N) -> Stärke der bio-optischen Rückkopplung
      i_min: 25.0         # minimales optimales Licht (W/m2)
      r1max: 2.0          # max. Wachstum Diatomeen (1/d)
      r2max: 0.7          # max. Wachstum Flagellaten (1/d)
      r3max: 0.5          # max. Wachstum Cyanobakterien (1/d)
      alpha1: 1.35        # Halbsättigung Nährstoff Diatomeen (mmol N/m3)
      alpha2: 0.675       # Halbsättigung Nährstoff Flagellaten (mmol N/m3)
      alpha3: 0.5         # Halbsättigung Nährstoff Cyanobakterien (mmol N/m3)
      lpa: 0.01           # Ausscheidung Phytoplankton (1/d)
      lpd: 0.02           # Sterblichkeit Phytoplankton (1/d)
      tf: 10.0            # Halbsättigungstemperatur Flagellaten (°C)
      tbg: 14.0           # Referenztemperatur Cyanobakterien (°C)
      beta_bg: 1.0        # Temperaturempfindlichkeit Cyanobakterien (1/°C)
      g1max: 0.5          # max. Fraß an Diatomeen (1/d)
      g2max: 0.5          # max. Fraß an Flagellaten (1/d)
      g3max: 0.25         # max. Fraß an Cyanobakterien (1/d)
      lza: 0.0666666666   # Zooplankton-Verlust zu gelöstem Material (m3/mmol N/d)
      lzd: 0.1333333333   # Zooplankton-Verlust zu Detritus (m3/mmol N/d)
      iv: 0.24444444      # Ivlev-Konstante Fraß (m3/mmol N)
      topt: 20.0          # optimale Temperatur Fraß (°C)
      lan: 0.1            # max. Nitrifikation (1/d)
      oan: 0.01           # Halbsättigung Sauerstoff Nitrifikation (mmol O2/m3)
      beta_an: 0.11       # Temperaturempfindlichkeit Nitrifikation (1/°C)
      lda: 0.003          # Remineralisierung (1/d)
      tda: 13.0           # Halbsättigungstemperatur Remineralisierung (°C)
      beta_da: 20.0       # Temperaturempfindlichkeit Remineralisierung (-)
      pvel: 5.0           # Gasaustausch (m/d)
      sr: 0.0625          # P:N-Verhältnis (mol P/mol N)
      s1: 5.3             # Nitrat : Detritus bei Denitrifikation (-)
      s2: 6.625           # O2:N bei Ammonium-Aufnahme und Remineralisierung
      s3: 8.625           # O2:N bei Nitrat-Aufnahme
      s4: 2.0             # O2:N bei Nitrifikation
      a0: 31.25           # mmol O2 pro Gramm
      a1: 14.603          # O2-Sättigung bei 0 °C (g/m3)
      a2: 0.4025          # Abnahme der O2-Sättigung pro °C (g/m3/°C)
      lds: 3.5            # Sedimentation Detritus (m/d)
      lsd: 25.0           # Resuspension Fluff (1/d)
      tau_crit: 0.07      # kritische Bodenschubspannung (N/m2)
      lsa: 0.001          # Mineralisierung Fluff (1/d)
      bsa: 0.15           # Temperaturempfindlichkeit Fluff-Mineralisierung (1/°C)
      ph1: 0.15           # Hemmung der Phosphat-Freisetzung (-)
      ph2: 0.1            # Halbsättigung O2 für diese Hemmung (mmol O2/m3)
      w_p1: -0.5          # Sinken Diatomeen (m/d)
      w_p2: 0.0           # Sinken Flagellaten (m/d)
      w_p3: 0.1           # Aufschwimmen Cyanobakterien (m/d)
      w_de: -3.0          # Sinken Detritus (m/d)
    initialization:       # Startwerte (nit, amm, pho, oxy werden durch Profile ersetzt)
      dia: 0.1
      fla: 0.1
      cya: 0.1
      zoo: 0.1
      det: 0.5
      amm: 0.1
      nit: 5.0
      pho: 0.6
      oxy: 300.0
      flf: 0.0
"""


if __name__ == "__main__":
    main()
