# Phase C: ERGOM über FABM in pygetm einbinden

Stand: 29.10.2026, recherchiert im Quellcode von pygetm 0.9.23 und FABM (GitHub, master).

## Kurzfassung

- pygetm koppelt FABM direkt: `pygetm.Simulation(..., fabm=pygetm.fabm.FABM("fabm.yaml"))`.
- FABM enthält **mehrere Ostsee-Biogeochemiemodelle**, alle im Standardumfang (also wahrscheinlich im Image):
  `gotm/ergom` (klassisches ERGOM), `iow/ergom` (ERGOM-Variante aus dem Code-Generator des IOW),
  `msi/ergom1` (Tallinn), `selma` (vereinfachtes ERGOM).
- **Die bio-optische Rückkopplung ist schon eingebaut:** Mit `bioshade_feedback=True` gibt FABM die
  Lichtdämpfung durch Algen und Detritus an die Strahlungsrechnung von GETM weiter. Damit wird die
  Erwärmung des Wassers durch Algen berechnet. Für die Arbeit heißt das: ein Lauf mit und einer
  ohne diese Rückkopplung genügt, kein eigener Code nötig.

## Empfohlener Einstieg: `gotm/ergom`

Begründung: einfach, gut dokumentiert, Einheiten passen direkt zur Copernicus-Reanalyse.
Vorlage: `testcases/fabm-gotm-ergom.yaml` im FABM-Repository.

| Variable | Bedeutung | Einheit | Startwert aus Reanalyse (BGC) |
|---|---|---|---|
| `nit` | Nitrat | mmol N/m³ | `no3` |
| `amm` | Ammonium | mmol N/m³ | `nh4` |
| `pho` | Phosphat | mmol P/m³ | `po4` |
| `oxy` | Sauerstoff; **negativ = Schwefelwasserstoff** | mmol O₂/m³ | `o2` (Werte ≤ 0 prüfen) |
| `dia`, `fla`, `cya` | Diatomeen, Flagellaten, Cyanobakterien | mmol N/m³ | klein starten oder aus Chlorophyll schätzen |
| `zoo` | Zooplankton | mmol N/m³ | klein starten |
| `det` | Detritus | mmol N/m³ | klein starten |
| `flf` | Fluff (Sediment-Oberschicht, nur mit `fluff: true`) | mmol N/m² | 0 |

Wichtige Parameter: `kc` (Lichtdämpfung pro Algenbiomasse, Standard 0,03 m²/mmol N) steuert die
Stärke der bio-optischen Rückkopplung. Oberflächenflüsse `sfl_*` (Eintrag aus der Atmosphäre)
stehen in der Vorlage auf Ostsee-Werten.

Ein Plus für die Todeszone: ERGOM rechnet Schwefelwasserstoff als negativen Sauerstoff.
Anoxie ist also direkt in `oxy` sichtbar.

## Technische Schritte

1. `setups/stufe1_10km/fabm.yaml` aus der Vorlage anlegen (`fluff: true`).
2. In `08_run_phase_b.py` (oder neuem Skript 11) `fabm=pygetm.fabm.FABM(path, bioshade_feedback=True)`
   an `pygetm.Simulation` übergeben.
3. Startwerte setzen: Variablen heißen in pygetm `<instanz>_<variable>`, z. B. `ergom_nit`.
   Werte aus `data/raw/cmems/bgc/init_2015-01-01.nc` (nach Lückenfüllung wie in Skript 05).
4. Rand: Nährstoffe und Sauerstoff am Skagerrak-Rand aus der BGC-Reanalyse (Skript 07 erweitern).
5. Fehlende Abhängigkeiten, die GETM nicht liefert, prüfen: `sim.fabm.get_dependency(...)`
   (im Nordsee-Beispiel z. B. `absorption_of_silt`, `mole_fraction_of_carbon_dioxide_in_air`).
6. Ausgabe ergänzen: `ergom_oxy`, `ergom_nit`, `ergom_pho`, `ergom_cya`, `kc_fabm`.
7. Testwoche, dann ein Jahr; Rechenzeit vermutlich 2–3× langsamer als nur Physik.

## Phase C1: ERGOM zuerst in 1D (GOTM), Station BY15

Stand 01.11.2026. Getestet mit GOTM 771b3b5a + FABM (synthetische Daten): 1 Modelljahr in ca. 6 s.

| Schritt | Skript | Ergebnis |
|---|---|---|
| Stationsprofile laden (täglich, Physik + BGC) | `11_download_station.py` | `data/raw/cmems/station/BY15_*.nc` |
| Setup bauen | `12_prepare_gotm_station.py` | `setups/gotm_BY15/` (gotm.yaml, fabm.yaml, *.dat) |
| Lauf starten | `13_run_gotm.py [--no-shade] [--kc X]` | `results/gotm_BY15_<was>/gotm_out.nc` |
| Bilder | `14_plot_gotm.py <lauf> [<lauf2>]` | Hovmöller, Oberfläche, Vergleich Reanalyse, Differenz |

Annahmen: T/S unterhalb 70 m mit 10 Tagen an die Reanalyse nachgeführt (ersetzt seitliche Einströme);
Biologie frei; Startprofile nit/amm/pho/oxy aus der Reanalyse; Licht Jerlov III + Algen (`shade: true`).
GOTM-Ausgabenamen: `temp`, `salt`, `z`, `ergom_<var>`, `bioshade`.

## Zu beachten

- pygetm übergibt FABM den **absoluten** Salzgehalt unter dem Namen „practical salinity"
  (Unterschied ~0,5 %, für ERGOM unerheblich).
- Ohne Flüsse sinken die Nährstoffe über die Jahre. Für technische Tests unkritisch, für Ergebnisse nicht.
- Für das Muschelmodul (Phase D) muss FABM mit eigenem Code neu gebaut werden; die conda-Version von
  pygetm reicht dann nicht mehr. pygetm hat dafür einen eigenen Build-Weg (`source ./install`,
  `cmake_opts` mit `-DFABM_EXTRA_INSTITUTES`).
- Interessant für später: FABM enthält auch `uhh` (Universität Hamburg, Arbeitsgruppe Hense) mit
  Modellen zu Cyanobakterien und Lichtabsorption.

## Quellen

- pygetm: https://github.com/BoldingBruggeman/getm-rewrite (v0.9.23, `python/pygetm/fabm.py`, `radiation.py`)
- FABM: https://github.com/fabm-model/fabm (`src/models/gotm/ergom.F90`, `testcases/fabm-gotm-ergom.yaml`)
- Hofmeister et al. (2010), adaptive Vertikalkoordinaten: https://doi.org/10.1016/j.ocemod.2009.12.003
