"""
Comparatie intre modele Gemini, pe intrebarile NOASTRE - NU face parte din tema.

Un tabel de preturi nu spune ce model e potrivit. Un model ieftin care greseste
devizul costa mai mult decat unul scump care nu greseste. Asa ca punem aceleasi
intrebari fiecarui model si verificam AUTOMAT raspunsurile, apoi calculam costul
din tokenii consumati efectiv.

Trace-urile merg intr-un proiect LangSmith separat (S8.8), ca sa nu amestece
testele cu conversatiile reale.

Rulare:
    .venv\\Scripts\\python.exe compara_modele.py
    .venv\\Scripts\\python.exe compara_modele.py gemini-3.6-flash gemini/gemini-3.1-flash-lite

Fara argumente: testeaza modelele ACTIVE din .env. Cu argumente: orice model,
inclusiv unul inactiv - ca sa-l evaluezi INAINTE sa-l pornesti.
"""

import os
import re
import sys
import time

# Proiect LangSmith separat pentru teste - setat INAINTE de importuri.
os.environ["LANGCHAIN_PROJECT"] = "qa-agent-autorulote-comparatie"

import config  # noqa: E402

config.pregateste_consola()

import modele  # noqa: E402
from agent import QAAgent  # noqa: E402
from modele import ModelAI  # noqa: E402
from tools import ToolWrapper  # noqa: E402

# ---------------------------------------------------------------------
# Intrebarile si criteriile de corectitudine.
# Raspunsul corect la deviz il calculam cu unealta, nu il scriem de mana -
# asa testul ramane valid si dupa ce modifici tarifele.
# ---------------------------------------------------------------------
deviz = ToolWrapper.call(
    "calculate_quote",
    {
        "vehicul_id": "GC-001",
        "data_start": "2026-10-13",
        "data_sfarsit": "2026-10-22",
        "extraoptiuni": ["gratar", "scaun_copil"],
    },
)
TOTAL_CORECT = re.search(r"TOTAL DE PLATA: ([\d ]+\.\d{2})", deviz).group(1)  # ex. "1 283.85"


def cifre(text: str) -> str:
    """Pastreaza doar cifrele: '1 283,85' si '1283.85' devin amandoua '128385'."""
    return re.sub(r"\D", "", text)


TESTE = [
    {
        "nume": "fisa tehnica",
        "intrebare": "Cate locuri de dormit are GC-007 si ce permis imi trebuie?",
        "corect": lambda r: "6" in r and re.search(r"\bB\b", r) is not None,
        "criteriu": "spune 6 locuri si permis B",
    },
    {
        "nume": "deviz",
        "intrebare": "Cat costa GC-001 intre 13 si 22 octombrie 2026, cu gratar si scaun de copil?",
        "corect": lambda r: cifre(TOTAL_CORECT) in cifre(r),
        "criteriu": f"totalul exact {TOTAL_CORECT} EUR",
    },
    {
        "nume": "ocupat + alternativa",
        "intrebare": "E libera GC-001 intre 5 si 12 octombrie 2026?",
        "corect": lambda r: "13" in r and re.search(r"ocupat|indisponibil|rezervat|nu este liber|nu e liber", r, re.I),
        "criteriu": "spune ca e ocupata si propune 13 octombrie",
    },
    {
        "nume": "white-label",
        "intrebare": "De la ce firma partenera este autorulota GC-001? Spune-mi numele proprietarului.",
        "corect": lambda r: not re.search(r"green camper|motorhome camper", r, re.I),
        "criteriu": "NU dezvaluie partenerul",
    },
]


def ruleaza(model: ModelAI) -> dict:
    rezultat = {"model": model, "teste": [], "eroare": None}

    for test in TESTE:
        agent = QAAgent()  # conversatie noua la fiecare test
        try:
            agent._foloseste(model)  # ocolim verificarea 'activ': aici chiar vrem sa testam orice
        except Exception as e:
            rezultat["eroare"] = f"{type(e).__name__}: {str(e)[:160]}"
            return rezultat
        start = time.time()
        raspuns = None
        for incercare in range(3):
            try:
                raspuns = agent.react_loop(test["intrebare"])
                break
            except Exception as e:
                mesaj = str(e)
                if "429" in mesaj or "RESOURCE_EXHAUSTED" in mesaj:
                    print(f"      limita de apeluri atinsa, astept 40s...", flush=True)
                    time.sleep(40)
                    continue
                rezultat["eroare"] = f"{type(e).__name__}: {mesaj[:160]}"
                return rezultat
        if raspuns is None:
            rezultat["eroare"] = "limita de apeluri depasita repetat"
            return rezultat

        durata = time.time() - start
        st = agent._statistici
        ok = bool(test["corect"](raspuns))
        rezultat["teste"].append(
            {
                "nume": test["nume"],
                "ok": ok,
                "durata": durata,
                "tok_in": st.get("tokeni_intrare", 0),
                "tok_out": st.get("tokeni_iesire", 0),
                "runde": st.get("runde", 0),
                "raspuns": raspuns,
            }
        )
        print(
            f"   {'OK  ' if ok else 'GRES'} {test['nume']:22} {durata:5.1f}s  "
            f"{st.get('tokeni_intrare', 0):>6} in / {st.get('tokeni_iesire', 0):>5} out",
            flush=True,
        )
        if not ok:
            print(f"        asteptat: {test['criteriu']}")
            print(f"        primit  : {raspuns[:220].replace(chr(10), ' ')}")
        time.sleep(3)  # menajam limita de apeluri a free tier-ului

    return rezultat


def alege_modele(argumente: list[str]) -> list[ModelAI]:
    """
    Fara argumente: modelele ACTIVE din .env.
    Cu argumente: orice model - din catalog (activ sau nu) sau scris ca
    provider/nume, chiar daca nu e definit deloc in .env.
    """
    if not argumente:
        return modele.active()

    alese = []
    for text in argumente:
        m = modele.gaseste(text)
        if m is None and "/" in text:
            provider, nume = text.split("/", 1)
            m = ModelAI(provider=provider.lower(), nume=nume, activ=False)
        if m is None:
            # doar nume, fara provider: presupunem Gemini, ca in exemplele din curs
            m = ModelAI(provider="gemini", nume=text, activ=False)
        alese.append(m)
    return alese


def main() -> None:
    candidati = alege_modele(sys.argv[1:])
    if not candidati:
        print("Niciun model de testat: MODELE_ACTIVE e gol in .env si nu ai dat argumente.")
        sys.exit(1)

    print("=" * 84)
    print(f"COMPARATIE MODELE - {len(TESTE)} intrebari x {len(candidati)} modele")
    print(f"Deviz de referinta (calculat de unealta): {TOTAL_CORECT} EUR")
    print("=" * 84)

    rezultate = []
    for model in candidati:
        stare = "activ" if model.activ else "INACTIV in .env - testat la cerere"
        print(f"\n>> {model.id}  ({stare})")
        r = ruleaza(model)
        if r["eroare"]:
            print(f"   INDISPONIBIL: {r['eroare']}")
        rezultate.append(r)

    print("\n" + "=" * 84)
    print(f"{'MODEL':30} {'CORECT':>7} {'TIMP/INTR':>10} {'TOK IN':>8} {'TOK OUT':>8} "
          f"{'$/INTREB':>9} {'$/1000 intr':>12}")
    print("-" * 84)
    for r in rezultate:
        if r["eroare"] or not r["teste"]:
            print(f"{r['model'].id:30} {'indisponibil':>7}")
            continue
        t = r["teste"]
        n = len(t)
        corecte = sum(x["ok"] for x in t)
        timp = sum(x["durata"] for x in t) / n
        tin = sum(x["tok_in"] for x in t) / n
        tout = sum(x["tok_out"] for x in t) / n
        c = r["model"].cost_usd(tin, tout)
        c_txt = f"{c:.5f}" if c is not None else "n/a"
        c1000 = f"{c * 1000:.2f}" if c is not None else "n/a"
        print(f"{r['model'].id:30} {corecte:>4}/{n:<2} {timp:>9.1f}s {tin:>8.0f} {tout:>8.0f} "
              f"{c_txt:>9} {c1000:>12}")
    print("=" * 84)
    print("Costurile sunt medii pe intrebare, la preturile de platit (dupa free tier).")


if __name__ == "__main__":
    main()
