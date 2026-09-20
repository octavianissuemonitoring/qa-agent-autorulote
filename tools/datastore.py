"""
Accesul la datele din data/ - NU e un tool, e infrastructura.

De ce exista un fisier separat:
    Sase tool-uri au nevoie de aceleasi date. Daca fiecare si-ar citi singur
    JSON-urile, am avea acelasi cod copiat de sase ori, sase citiri de pe disc
    la fiecare intrebare, si sase locuri de modificat cand trecem la baza de
    date reala (Lectia 4).

    Asa, tool-urile cer "da-mi vehiculul GC-001" si nu stiu de unde vine.
    In Lectia 4 rescriem doar fisierul asta si tool-urile raman neatinse.

Fisierul NU importa niciun tool si nu e un tool el insusi.
"""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------
# Incarcare cu cache
# ---------------------------------------------------------------------
@lru_cache(maxsize=None)
def _incarca(nume_fisier: str) -> dict[str, Any]:
    """
    Citeste un JSON din data/ si il tine in memorie.

    @lru_cache face ca fisierul sa fie citit de pe disc O SINGURA DATA per
    proces. Al doilea apel primeste ce e deja in memorie. Fara el, un singur
    raspuns al agentului ar deschide aceleasi fisiere de zeci de ori.
    """
    cale = DATA / nume_fisier
    return json.loads(cale.read_text(encoding="utf-8"))


def reincarca() -> None:
    """
    Goleste cache-ul. De apelat dupa ce editezi manual un JSON, ca sa vezi
    schimbarea fara sa repornesti agentul (acelasi principiu ca hot reload-ul
    prompturilor din slide-ul S3.8).
    """
    _incarca.cache_clear()


# ---------------------------------------------------------------------
# Accesori pe fiecare fisier
# ---------------------------------------------------------------------
def toate_vehiculele(doar_active: bool = True) -> list[dict]:
    vehicule = _incarca("flota.json")["vehicule"]
    return [v for v in vehicule if v.get("activ", True)] if doar_active else list(vehicule)


def vehicul(vehicul_id: str) -> dict | None:
    """Cauta un vehicul dupa id. Returneaza None daca nu exista."""
    for v in _incarca("flota.json")["vehicule"]:
        if v["id"].upper() == vehicul_id.strip().upper():
            return v
    return None


def partener(partener_id: str) -> dict | None:
    for p in _incarca("parteneri.json")["parteneri"]:
        if p["id"].upper() == partener_id.strip().upper():
            return p
    return None


def partenerul_vehiculului(v: dict) -> dict:
    """
    Partenerul care detine vehiculul. Arunca daca lipseste, pentru ca e o
    ruptura de integritate in data/flota.json sau data/parteneri.json.
    """
    p = partener(v["partener_id"])
    if p is None:
        raise KeyError(
            f"Vehiculul {v['id']} indica partenerul {v['partener_id']!r}, care nu exista. "
            f"Verifica data/flota.json si data/parteneri.json."
        )
    return p


def rezervarile_vehiculului(vehicul_id: str) -> list[dict]:
    """Rezervarile unui vehicul, ordonate cronologic."""
    rezervari = [
        r
        for r in _incarca("rezervari.json")["rezervari"]
        if r["vehicul_id"].upper() == vehicul_id.strip().upper()
    ]
    return sorted(rezervari, key=lambda r: r["data_start"])


def mentenanta_vehiculului(vehicul_id: str) -> dict | None:
    for m in _incarca("mentenanta.json")["mentenanta"]:
        if m["vehicul_id"].upper() == vehicul_id.strip().upper():
            return m
    return None


# ---------------------------------------------------------------------
# Nomenclatoare - regulile de business citite din date, nu scrise in cod
# ---------------------------------------------------------------------
def status_rezervare(cod: str) -> dict:
    """
    Fisa unui status. Daca nu-l gasim, returnam varianta prudenta: BLOCHEAZA.

    De ce blocheaza si nu invers: un cod nerecunoscut inseamna aproape mereu o
    greseala de scriere in rezervari.json. Daca l-am ignora, o rezervare reala
    ar disparea din calendar si am inchiria de doua ori acelasi vehicul. Asa,
    cel mult refuzam o perioada libera - greseala care se repara cu un telefon,
    nu cu doi clienti in fata aceleiasi autorulote.

    Steagul 'necunoscut' ajunge in raspunsul tool-urilor ca avertisment, iar
    valideaza_configurarea() semnaleaza problema inca de la pornire.
    """
    for s in _incarca("nomenclatoare.json")["statusuri_rezervare"]:
        if s["cod"] == cod:
            return s
    return {
        "cod": cod,
        "nume": f"{cod} (status necunoscut)",
        "blocheaza_calendar": True,
        "ancoreaza_matching": False,
        "avertizeaza": True,
        "necunoscut": True,
    }


def status_necunoscut(rezervare: dict) -> bool:
    """Rezervarea are un status care nu exista in nomenclator?"""
    return bool(status_rezervare(rezervare["status"]).get("necunoscut"))


def blocheaza_calendarul(rezervare: dict) -> bool:
    return bool(status_rezervare(rezervare["status"])["blocheaza_calendar"])


def ancoreaza_matching(rezervare: dict) -> bool:
    return bool(status_rezervare(rezervare["status"])["ancoreaza_matching"])


def avertizeaza(rezervare: dict) -> bool:
    return bool(status_rezervare(rezervare["status"])["avertizeaza"])


def regim_extraoptiune(cod: str) -> dict:
    for r in _incarca("nomenclatoare.json")["regimuri_extraoptiuni"]:
        if r["cod"] == cod:
            return r
    return {
        "cod": cod,
        "nume": cod,
        "se_taxeaza": True,
        "se_poate_cere": False,
        "mesaj_agent": "Regim necunoscut.",
    }


# ---------------------------------------------------------------------
# Extraoptiuni - rezolvarea cascadei pe 3 niveluri
# ---------------------------------------------------------------------
def extraoptiune_globala(extra_id: str) -> dict | None:
    for e in _incarca("extraoptiuni.json")["extraoptiuni"]:
        if e["id"] == extra_id:
            return e
    return None


def extraoptiunile_vehiculului(v: dict) -> list[dict]:
    """
    Rezolva cele 3 niveluri ale cascadei intr-o singura lista gata de afisat:

        catalog global  ->  nume, descriere, categorie
        partener        ->  pret, unitate tarifare
        vehicul         ->  regim (inclus / optional / indisponibil)

    Rezultatul e ordonat: intai ce e inclus, apoi ce se poate lua contra cost,
    apoi ce nu se poate monta - adica exact ordinea in care il intereseaza pe
    client.
    """
    p = partenerul_vehiculului(v)
    preturi_partener = {e["id"]: e for e in p.get("extraoptiuni", []) if e.get("activ", True)}
    catalog_vehicul = v.get("extraoptiuni", {})

    rezultat = []
    for extra_id, oferta in preturi_partener.items():
        glob = extraoptiune_globala(extra_id)
        if glob is None:
            continue  # integritate rupta: extraoptiune inexistenta in extraoptiuni.json

        # Lipsa din catalogul vehiculului = nu se poate monta.
        intrare = catalog_vehicul.get(extra_id, {"regim": "indisponibil"})
        fisa_regim = regim_extraoptiune(intrare.get("regim", "indisponibil"))

        rezultat.append(
            {
                "id": extra_id,
                "nume": glob["nume"],
                "descriere": glob["descriere"],
                "categorie": glob["categorie"],
                "regim": fisa_regim["cod"],
                "se_taxeaza": fisa_regim["se_taxeaza"],
                "se_poate_cere": fisa_regim["se_poate_cere"],
                # pret     = ce plateste efectiv clientul (0 daca e inclus)
                # pret_lista = cat ar costa daca nu ar fi inclus - folosit ca sa
                #              aratam clientului valoarea dotarilor primite gratuit
                "pret": oferta["pret"] if fisa_regim["se_taxeaza"] else 0,
                "pret_lista": oferta["pret"],
                "unitate_tarifare": oferta["unitate_tarifare"],
                "cantitate": intrare.get("cantitate"),
                "nota": intrare.get("nota"),
            }
        )

    ordine = {"inclus": 0, "optional": 1, "indisponibil": 2}
    return sorted(rezultat, key=lambda e: (ordine.get(e["regim"], 9), e["nume"]))


def moneda(v: dict) -> str:
    return partenerul_vehiculului(v)["reguli_operationale"].get("moneda", "EUR")


# ---------------------------------------------------------------------
# Tarife - lipsa unui tarif NU e zero
# ---------------------------------------------------------------------
def tarif_sezon(v: dict, cod_sezon: str) -> float:
    """
    Tariful vehiculului pentru un sezon. Arunca daca lipseste.

    Varianta veche, .get(cod, 0), era "fail open": o greseala de configurare
    producea o zi gratuita intr-un deviz, fara ca nimeni sa observe. Un pret
    gresit trimis clientului e mai scump decat o oferta refuzata, deci aici
    oprim calculul si spunem exact ce lipseste.
    """
    tarife = v.get("tarife_sezon") or {}
    if cod_sezon not in tarife:
        disponibile = ", ".join(sorted(tarife)) or "(niciunul)"
        raise KeyError(
            f"Vehiculul {v['id']} nu are tarif pentru sezonul {cod_sezon!r}. "
            f"Sezoane cu tarif definit: {disponibile}. Completeaza data/flota.json."
        )
    return float(tarife[cod_sezon])


# ---------------------------------------------------------------------
# Documentele vehiculului (ITP, RCA, rovinieta, CASCO)
# ---------------------------------------------------------------------
DOCUMENTE = {
    "itp_expira": "ITP",
    "rca_expira": "RCA",
    "casco_expira": "CASCO",
    "rovinieta_expira": "Rovinieta",
}


def documente_expirate(vehicul_id: str, pana_la: date) -> list[str]:
    """
    Documentele care expira inainte de o data (de regula ziua predarii).

    Nu blocheaza inchirierea - vehiculul poate fi disponibil, iar documentul
    reinnoit intre timp. Dar clientul trebuie sa afle, iar operatorul la fel.
    """
    m = mentenanta_vehiculului(vehicul_id)
    if not m:
        return []

    probleme: list[str] = []
    for camp, eticheta in DOCUMENTE.items():
        text = m.get(camp)
        if not text:
            probleme.append(f"{eticheta}: data lipseste din fisa de mentenanta")
            continue
        try:
            scadenta = date.fromisoformat(text)
        except ValueError:
            probleme.append(f"{eticheta}: data {text!r} e invalida in fisa de mentenanta")
            continue
        if scadenta < pana_la:
            probleme.append(f"{eticheta} expira la {scadenta.isoformat()}, inainte de predare")
    return probleme


# ---------------------------------------------------------------------
# Validarea datelor, la pornire si la /reload
# ---------------------------------------------------------------------
def valideaza_configurarea() -> list[str]:
    """
    Verifica integritatea pe care un fisier JSON nu o poate garanta singur.

    O baza de date ar refuza din oficiu un partener_id inexistent sau un status
    inventat. JSON-ul accepta orice, deci verificam noi - si o facem la fiecare
    pornire, nu cand isi aminteste cineva sa ruleze un script separat.
    """
    probleme: list[str] = []

    parteneri = {p["id"]: p for p in _incarca("parteneri.json")["parteneri"]}
    statusuri = {s["cod"] for s in _incarca("nomenclatoare.json")["statusuri_rezervare"]}
    extra_globale = {e["id"] for e in _incarca("extraoptiuni.json")["extraoptiuni"]}
    vehicule = {v["id"]: v for v in _incarca("flota.json")["vehicule"]}

    # 1. Fiecare vehicul are un partener real si tarif pentru toate sezoanele lui.
    for vid, v in vehicule.items():
        p = parteneri.get(v.get("partener_id"))
        if p is None:
            probleme.append(f"{vid}: partener inexistent {v.get('partener_id')!r}")
            continue
        for sezon in p.get("sezoane", []):
            if sezon["cod"] not in (v.get("tarife_sezon") or {}):
                probleme.append(
                    f"{vid}: lipseste tariful pentru sezonul {sezon['cod']!r} "
                    f"(partener {p['id']})"
                )

    # 2. Rezervarile indica vehicule si statusuri care exista.
    for r in _incarca("rezervari.json")["rezervari"]:
        if r["vehicul_id"] not in vehicule:
            probleme.append(f"{r['id']}: vehicul inexistent {r['vehicul_id']!r}")
        if r["status"] not in statusuri:
            probleme.append(
                f"{r['id']}: status necunoscut {r['status']!r}. "
                f"Pana la corectare, rezervarea BLOCHEAZA calendarul."
            )

    # 3. Extraoptiunile oferite de parteneri exista in nomenclatorul global.
    for p in parteneri.values():
        for extra_id in (p.get("preturi_extraoptiuni") or {}):
            if extra_id not in extra_globale:
                probleme.append(
                    f"partenerul {p['id']}: extraoptiune inexistenta {extra_id!r}"
                )

    return probleme
