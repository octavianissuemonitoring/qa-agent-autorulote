"""
Verificare de sanatate a mediului - NU face parte din tema.
Il rulezi oricand ceva nu merge, ca sa afli DE UNDE vine problema.

Ruleaza cu:  .venv\\Scripts\\python.exe verificare_setup.py
"""

import json
import time

import config

config.pregateste_consola()

import modele  # noqa: E402
from agent import text_din  # noqa: E402

print("=" * 62)
print("VERIFICARE MEDIU - QA Agent Autorulote")
print("=" * 62)

# --- 1. Ce spune configuratia -------------------------------------
print("\n[1] Modele definite in .env")
for i, m in enumerate(modele.catalog(), start=1):
    print(f"    {i:>2}. {'ACTIV   ' if m.activ else 'inactiv '} {m.id}")
probleme = config.verifica()
for p in probleme:
    print(f"    X {p}")

# --- 2. Datele de business ----------------------------------------
with open("data/flota.json", encoding="utf-8") as f:
    vehicule = json.load(f)["vehicule"]
print("\n[2] Date flota")
print(f"    {len(vehicule)} vehicule incarcate: {[v['id'] for v in vehicule]}")

# --- 3. Raspunde fiecare model ACTIV? -----------------------------
# Modelele inactive nu se verifica: agentul oricum nu le poate folosi.
print("\n[3] Apel real catre fiecare model activ")
toate_ok = True
for m in modele.active():
    start = time.time()
    try:
        raspuns = modele.creeaza_llm(m).invoke("Raspunde doar cu cuvantul: FUNCTIONEZ")
        print(f"    OK  {m.id:36} {time.time() - start:5.1f}s  -> {text_din(raspuns).strip()[:40]}")
    except Exception as e:
        toate_ok = False
        motiv = str(e).split("\n")[0][:110]
        print(f"    X   {m.id:36} {type(e).__name__}: {motiv}")
        if m.provider == "ollama":
            print("        Ollama porneste cu docker-compose (vezi README). E pornit containerul?")

print("\n" + "=" * 62)
print("TOTUL FUNCTIONEAZA." if toate_ok and not probleme else "EXISTA PROBLEME - vezi liniile cu X.")
print("=" * 62)
