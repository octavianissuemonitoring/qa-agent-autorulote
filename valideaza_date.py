"""
Validator de integritate pentru folderul data/.

DE CE EXISTA acest fisier:
    Tinem datele in JSON, nu intr-o baza de date. O baza de date ar refuza
    din oficiu un partener_id inexistent sau un id duplicat - se numeste
    "integritate referentiala" si e gratuita. JSON-ul accepta orice scrii.
    Deci verificarile le facem noi, aici.

    Cand ajungem la Lectia 4 (baze de date), fisierul asta devine inutil -
    si fix aia e lectia.

Rulare:
    .venv\\Scripts\\python.exe valideaza_date.py

Cod de iesire: 0 daca totul e in regula, 1 daca exista erori.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent / "data"

erori: list[str] = []
avertismente: list[str] = []


def eroare(mesaj: str) -> None:
    erori.append(mesaj)


def avertisment(mesaj: str) -> None:
    avertismente.append(mesaj)


def incarca(nume_fisier: str) -> dict:
    """Citeste un JSON si raporteaza clar daca e stricat."""
    cale = DATA / nume_fisier
    if not cale.exists():
        eroare(f"[{nume_fisier}] fisierul lipseste din data/")
        return {}
    try:
        return json.loads(cale.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        eroare(f"[{nume_fisier}] JSON invalid la linia {e.lineno}, coloana {e.colno}: {e.msg}")
        return {}


def verifica_unicitate(elemente: list[dict], cheie: str, eticheta: str) -> None:
    vazute = set()
    for el in elemente:
        valoare = el.get(cheie)
        if valoare in vazute:
            eroare(f"[{eticheta}] id duplicat: {valoare!r}")
        vazute.add(valoare)


def in_interval(zi: date, de_la: str, pana_la: str) -> bool:
    """
    Verifica daca o zi cade intr-un interval scris ca LL-ZZ, recurent anual.
    Trateaza si intervalele care trec peste Anul Nou (ex. 11-01 -> 03-31).
    """
    curent = (zi.month, zi.day)
    start = tuple(int(x) for x in de_la.split("-"))
    sfarsit = tuple(int(x) for x in pana_la.split("-"))
    if start <= sfarsit:
        return start <= curent <= sfarsit
    return curent >= start or curent <= sfarsit


# =====================================================================
# 1. Incarcare
# =====================================================================
nomenclatoare = incarca("nomenclatoare.json")
extraoptiuni_glob = incarca("extraoptiuni.json")
parteneri_doc = incarca("parteneri.json")
flota_doc = incarca("flota.json")
rezervari_doc = incarca("rezervari.json")
mentenanta_doc = incarca("mentenanta.json")

if erori:
    print("Nu pot continua - fisiere lipsa sau JSON stricat:\n")
    for e in erori:
        print(f"  EROARE  {e}")
    sys.exit(1)

statusuri = {s["cod"]: s for s in nomenclatoare.get("statusuri_rezervare", [])}
sisteme_calcul = {s["cod"] for s in nomenclatoare.get("sisteme_calcul", [])}
unitati_tarifare = {u["cod"] for u in nomenclatoare.get("unitati_tarifare", [])}
regimuri = {r["cod"] for r in nomenclatoare.get("regimuri_extraoptiuni", [])}

catalog_global = {e["id"]: e for e in extraoptiuni_glob.get("extraoptiuni", [])}
parteneri = {p["id"]: p for p in parteneri_doc.get("parteneri", [])}
vehicule = flota_doc.get("vehicule", [])
rezervari = rezervari_doc.get("rezervari", [])
mentenanta = mentenanta_doc.get("mentenanta", [])

# =====================================================================
# 2. Unicitatea identificatorilor
# =====================================================================
verifica_unicitate(list(catalog_global.values()), "id", "extraoptiuni")
verifica_unicitate(parteneri_doc.get("parteneri", []), "id", "parteneri")
verifica_unicitate(vehicule, "id", "flota")
verifica_unicitate(rezervari, "id", "rezervari")
verifica_unicitate(nomenclatoare.get("statusuri_rezervare", []), "cod", "statusuri")

# =====================================================================
# 3. Parteneri: reguli interne coerente
# =====================================================================
for pid, p in parteneri.items():
    reguli = p.get("reguli_operationale", {})

    sistem = reguli.get("sistem_calcul")
    if sistem not in sisteme_calcul:
        eroare(f"[parteneri/{pid}] sistem_calcul={sistem!r} nu exista in nomenclatoare.json")

    coduri_sezon = [s["cod"] for s in p.get("sezoane", [])]
    if len(coduri_sezon) != len(set(coduri_sezon)):
        eroare(f"[parteneri/{pid}] coduri de sezon duplicate: {coduri_sezon}")

    # --- acoperirea calendarului: fiecare zi a anului apartine exact unui sezon
    an_bisect = date(2028, 1, 1)  # 2028 e bisect - acopera si 29 februarie
    neacoperite, suprapuse = [], []
    for i in range(366):
        zi = an_bisect + timedelta(days=i)
        potriviri = [
            s["cod"]
            for s in p.get("sezoane", [])
            for per in s.get("perioade", [])
            if in_interval(zi, per["de_la"], per["pana_la"])
        ]
        if not potriviri:
            neacoperite.append(zi.strftime("%m-%d"))
        elif len(potriviri) > 1:
            suprapuse.append((zi.strftime("%m-%d"), potriviri))
    if neacoperite:
        eroare(
            f"[parteneri/{pid}] {len(neacoperite)} zile nu apartin niciunui sezon "
            f"(prima: {neacoperite[0]}, ultima: {neacoperite[-1]})"
        )
    if suprapuse:
        eroare(
            f"[parteneri/{pid}] {len(suprapuse)} zile apartin mai multor sezoane "
            f"(ex. {suprapuse[0][0]} -> {suprapuse[0][1]})"
        )

    # --- pachete km: exact unul implicit
    implicite = [k["cod"] for k in p.get("pachete_km", []) if k.get("implicit")]
    if len(implicite) != 1:
        eroare(f"[parteneri/{pid}] trebuie exact un pachet km implicit, gasite: {implicite}")

    # --- grilele de discount acopera toate sezoanele
    for fel in ("durata", "early_booking"):
        grila = p.get("discounturi", {}).get(fel, {})
        lipsa = set(coduri_sezon) - set(grila)
        if lipsa:
            eroare(f"[parteneri/{pid}] discounturi.{fel} nu acopera sezoanele: {sorted(lipsa)}")

    # --- scara de matching: offset-uri unice si crescatoare ca reducere
    scara = p.get("matching", {}).get("scara", [])
    offsets = [s["offset"] for s in scara]
    if len(offsets) != len(set(offsets)):
        eroare(f"[parteneri/{pid}] matching.scara are offset-uri duplicate: {offsets}")

    # --- CASCADA nivel 2: partenerul ofera doar din catalogul global
    for e in p.get("extraoptiuni", []):
        if e["id"] not in catalog_global:
            eroare(
                f"[parteneri/{pid}] ofera extraoptiunea {e['id']!r}, "
                f"care NU exista in catalogul global"
            )
        if e.get("unitate_tarifare") not in unitati_tarifare:
            eroare(
                f"[parteneri/{pid}] extraoptiunea {e['id']!r} are "
                f"unitate_tarifare={e.get('unitate_tarifare')!r}, necunoscuta"
            )

# =====================================================================
# 4. Flota: legaturile catre partener si cascada extraoptiunilor
# =====================================================================
id_vehicule = {v["id"] for v in vehicule}

for v in vehicule:
    vid = v.get("id", "???")
    pid = v.get("partener_id")

    if pid not in parteneri:
        eroare(f"[flota/{vid}] partener_id={pid!r} nu exista in parteneri.json")
        continue

    partener = parteneri[pid]
    coduri_sezon = {s["cod"] for s in partener["sezoane"]}

    # --- tarifele acopera exact sezoanele partenerului
    tarife = v.get("tarife_sezon", {})
    lipsa = coduri_sezon - set(tarife)
    in_plus = set(tarife) - coduri_sezon
    if lipsa:
        eroare(f"[flota/{vid}] lipsesc tarife pentru sezoanele: {sorted(lipsa)}")
    if in_plus:
        eroare(f"[flota/{vid}] are tarife pentru sezoane inexistente la {pid}: {sorted(in_plus)}")
    for cod, pret in tarife.items():
        if not isinstance(pret, (int, float)) or pret <= 0:
            eroare(f"[flota/{vid}] tarif invalid pentru {cod!r}: {pret!r}")

    # --- garantia
    if not isinstance(v.get("garantie"), (int, float)) or v.get("garantie", 0) <= 0:
        eroare(f"[flota/{vid}] garantie lipsa sau invalida: {v.get('garantie')!r}")

    # --- CASCADA nivel 3: vehiculul poate marca doar ce ofera partenerul lui
    oferite_de_partener = {e["id"] for e in partener.get("extraoptiuni", []) if e.get("activ", True)}
    catalog_vehicul = v.get("extraoptiuni", {})

    if not isinstance(catalog_vehicul, dict):
        eroare(f"[flota/{vid}] extraoptiuni trebuie sa fie un obiect (id -> regim), nu o lista")
        catalog_vehicul = {}

    for eid, intrare in catalog_vehicul.items():
        if eid not in catalog_global:
            eroare(f"[flota/{vid}] extraoptiunea {eid!r} nu exista in catalogul global")
        elif eid not in oferite_de_partener:
            eroare(
                f"[flota/{vid}] extraoptiunea {eid!r} nu e oferita de partenerul {pid} "
                f"- cascada e rupta"
            )

        if not isinstance(intrare, dict):
            eroare(f"[flota/{vid}] extraoptiunea {eid!r} trebuie sa fie un obiect cu 'regim'")
            continue

        regim = intrare.get("regim")
        if regim not in regimuri:
            eroare(
                f"[flota/{vid}] extraoptiunea {eid!r} are regim={regim!r}; "
                f"valori permise: {sorted(regimuri)}"
            )

        cantitate = intrare.get("cantitate")
        if cantitate is not None and (not isinstance(cantitate, int) or cantitate <= 0):
            eroare(f"[flota/{vid}] extraoptiunea {eid!r} are cantitate invalida: {cantitate!r}")

    # Completitudine: catalogul vehiculului ar trebui sa acopere tot ce ofera partenerul.
    # Avertisment, nu eroare - lipsa se interpreteaza ca 'indisponibil'.
    neacoperite = oferite_de_partener - set(catalog_vehicul)
    if neacoperite:
        avertisment(
            f"[flota/{vid}] nu declara regim pentru {len(neacoperite)} extraoptiuni oferite de "
            f"{pid} (se considera 'indisponibil'): {sorted(neacoperite)}"
        )

    # --- coerenta permis / masa
    mma = v.get("masa_maxima_autorizata_kg")
    permis = v.get("permis_necesar")
    if isinstance(mma, (int, float)) and mma > 3500 and permis == "B":
        eroare(f"[flota/{vid}] MMA {mma} kg depaseste 3500 dar permis_necesar='B'")

    # --- coerenta locuri
    if v.get("locuri_dormit", 0) <= 0:
        eroare(f"[flota/{vid}] locuri_dormit invalid: {v.get('locuri_dormit')!r}")

# =====================================================================
# 5. Rezervari
# =====================================================================
for r in rezervari:
    rid = r.get("id", "???")

    if r.get("vehicul_id") not in id_vehicule:
        eroare(f"[rezervari/{rid}] vehicul_id={r.get('vehicul_id')!r} nu exista in flota")

    if r.get("status") not in statusuri:
        eroare(f"[rezervari/{rid}] status={r.get('status')!r} nu exista in nomenclatoare.json")

    try:
        start = date.fromisoformat(r["data_start"])
        sfarsit = date.fromisoformat(r["data_sfarsit"])
        if sfarsit < start:
            eroare(f"[rezervari/{rid}] data_sfarsit ({sfarsit}) e inainte de data_start ({start})")
    except (KeyError, ValueError) as e:
        eroare(f"[rezervari/{rid}] date calendaristice invalide: {e}")

# --- suprapuneri intre rezervari FERME pe acelasi vehicul
ferme = [r for r in rezervari if statusuri.get(r.get("status"), {}).get("blocheaza_calendar")]
for i, a in enumerate(ferme):
    for b in ferme[i + 1 :]:
        if a["vehicul_id"] != b["vehicul_id"]:
            continue
        try:
            a_start, a_sf = date.fromisoformat(a["data_start"]), date.fromisoformat(a["data_sfarsit"])
            b_start, b_sf = date.fromisoformat(b["data_start"]), date.fromisoformat(b["data_sfarsit"])
        except ValueError:
            continue
        if a_start <= b_sf and b_start <= a_sf:
            eroare(
                f"[rezervari] {a['id']} si {b['id']} se suprapun pe acelasi vehicul "
                f"{a['vehicul_id']}, ambele cu status ferm"
            )

# =====================================================================
# 6. Mentenanta
# =====================================================================
id_mentenanta = {m.get("vehicul_id") for m in mentenanta}

for m in mentenanta:
    vid = m.get("vehicul_id")
    if vid not in id_vehicule:
        eroare(f"[mentenanta] vehicul_id={vid!r} nu exista in flota")
    for camp in ("itp_expira", "rca_expira", "casco_expira", "rovinieta_expira"):
        try:
            date.fromisoformat(m[camp])
        except (KeyError, ValueError):
            eroare(f"[mentenanta/{vid}] {camp} lipseste sau nu e o data valida")
    if m.get("km_actuali", 0) < m.get("ultima_revizie_km", 0):
        eroare(f"[mentenanta/{vid}] km_actuali mai mici decat ultima_revizie_km")

for vid in sorted(id_vehicule - id_mentenanta):
    avertisment(f"[mentenanta] vehiculul {vid} nu are fisa de mentenanta")

# =====================================================================
# 7. Raport
# =====================================================================
print("=" * 62)
print("VALIDARE DATE - QA Agent Autorulote")
print("=" * 62)
print(
    f"\nIncarcate: {len(catalog_global)} extraoptiuni globale | {len(parteneri)} parteneri | "
    f"{len(vehicule)} vehicule | {len(rezervari)} rezervari | {len(mentenanta)} fise mentenanta"
)

if avertismente:
    print(f"\n{len(avertismente)} AVERTISMENTE:")
    for a in avertismente:
        print(f"  !  {a}")

if erori:
    print(f"\n{len(erori)} ERORI:")
    for e in erori:
        print(f"  X  {e}")
    print("\n" + "=" * 62)
    print("VALIDARE ESUATA")
    print("=" * 62)
    sys.exit(1)

print("\n" + "=" * 62)
print("TOATE VERIFICARILE AU TRECUT")
print("=" * 62)
