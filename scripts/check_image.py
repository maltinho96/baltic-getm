"""
check_image.py
Prüft, ob das Image alles enthält: GOTM (1D), pygetm (3D) und ERGOM in pygetms FABM.

Aufruf im Projektordner:
    ./run.sh python scripts/check_image.py
"""

import os
import shutil
import subprocess
import tempfile

ok = True

# 1) GOTM (1D)
gotm = shutil.which("gotm")
if gotm:
    res = subprocess.run([gotm, "-v"], capture_output=True, text=True)
    out = res.stdout + res.stderr          # GOTM schreibt die Versionsinfo teils nach stderr
    fabm_line = next((l.strip() for l in out.splitlines() if "FABM" in l), "FABM: ?")
    print(f"✔ GOTM gefunden: {gotm}  ({fabm_line})")
else:
    print("✘ GOTM fehlt")
    ok = False

# 2) pygetm (3D)
try:
    import pygetm
    import pygetm.fabm
    print("✔ pygetm lässt sich laden")
except Exception as e:  # noqa: BLE001
    print(f"✘ pygetm: {e}")
    ok = False

# 3) ERGOM im FABM, das pygetm benutzt
try:
    import pyfabm
    lib = os.path.join(os.path.dirname(pygetm.fabm.__file__), "fabm")
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write("instances:\n  ergom:\n    model: gotm/ergom\n")
    # pygetms FABM erwartet ein 3D-Gebiet: hier eine einzelne Zelle (1 x 1 x 1)
    model = pyfabm.Model(f.name, shape=(1, 1, 1), libname=lib)
    names = [v.name for v in model.interior_state_variables]
    print(f"✔ ERGOM in pygetm verfügbar: {', '.join(names)}")
except Exception as e:  # noqa: BLE001
    print(f"✘ ERGOM-Test: {e}")
    ok = False

print("\nAlles bereit." if ok else "\nEs fehlt noch etwas, siehe oben.")
