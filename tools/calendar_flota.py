"""
Motorul de calendar - NU e un tool, e infrastructura (ca datastore.py).

Aici traieste toata logica temporala pe care trei tool-uri o folosesc in comun:
check_availability, find_matching_opportunities si calculate_quote.

Patru concepte, in ordinea in care se construiesc unul pe altul:

  1. SEZONUL unei zile      - care grila de tarife se aplica pe 14 august
  2. ZILELE BLOCATE         - rezervari ferme + zilele de buffer din jurul lor
  3. FERESTRELE LIBERE      - intervalele continue ramase intre blocaje
  4. ANCORELE DE MATCHING   - zilele cu reducere din marginea ferestrelor

Regula de buffer:
    Buffer-ul se aplica de AMBELE parti ale unei rezervari ferme. Astfel, intre
    doua inchirieri consecutive ramane exact o perioada de curatenie, nu doua.
      rezervare pana pe 10 + buffer 2  ->  11 si 12 blocate, prima zi libera 13
      rezervare de pe  1 nov, buffer 2 ->  30 si 31 blocate, ultima libera 29
"""

from datetime import date, timedelta

from tools import datastore
from tools.perioada import PerioadaInchiriere


# ---------------------------------------------------------------------
# 1. Sezonul unei zile
# ---------------------------------------------------------------------
def in_interval(zi: date, de_la: str, pana_la: str) -> bool:
    """
    Intervalele se scriu ca LL-ZZ si se repeta in fiecare an.
    Trateaza si cazul care trece peste Anul Nou (ex. 10-15 -> 04-14):
    acolo conditia devine "dupa start SAU inainte de sfarsit".
    """
    curent = (zi.month, zi.day)
    start = tuple(int(x) for x in de_la.split("-"))
    sfarsit = tuple(int(x) for x in pana_la.split("-"))
    if start <= sfarsit:
        return start <= curent <= sfarsit
    return curent >= start or curent <= sfarsit


def sezon_pentru_zi(partener: dict, zi: date) -> dict | None:
    """Sezonul caruia ii apartine ziua, dupa grila partenerului."""
    for sezon in partener.get("sezoane", []):
        for perioada in sezon.get("perioade", []):
            if in_interval(zi, perioada["de_la"], perioada["pana_la"]):
                return sezon
    return None


# ---------------------------------------------------------------------
# 2. Numarul de unitati facturabile
# ---------------------------------------------------------------------
def numar_unitati(partener: dict, start: date, sfarsit: date) -> int:
    """
    Cate unitati se factureaza, dupa sistemul partenerului.

    Socoteala traieste acum in PerioadaInchiriere - singurul loc care traduce
    intre date calendaristice si unitati facturabile. Functia ramane ca scurtatura
    pentru codul care vrea doar numarul.
    """
    return PerioadaInchiriere.din_date(partener, start, sfarsit).unitati


def zilele_facturate(partener: dict, start: date, sfarsit: date) -> list[date]:
    """
    Zilele efectiv facturate, ca lista. In sistemul pe nopti, ultima zi
    (ziua predarii) nu se factureaza - de aceea lista e mai scurta cu una.
    """
    return PerioadaInchiriere.din_date(partener, start, sfarsit).zile_facturate


# ---------------------------------------------------------------------
# 3. Zilele blocate si ferestrele libere
# ---------------------------------------------------------------------
def rezervari_blocante(vehicul_id: str) -> list[dict]:
    return [r for r in datastore.rezervarile_vehiculului(vehicul_id) if datastore.blocheaza_calendarul(r)]


def rezervari_ancora(vehicul_id: str) -> list[dict]:
    return [r for r in datastore.rezervarile_vehiculului(vehicul_id) if datastore.ancoreaza_matching(r)]


def rezervari_provizorii(vehicul_id: str) -> list[dict]:
    return [r for r in datastore.rezervarile_vehiculului(vehicul_id) if datastore.avertizeaza(r)]


def zile_blocate(vehicul_id: str, partener: dict) -> dict[date, str]:
    """
    Toate zilele indisponibile, cu motivul fiecareia.
    Motivul e text, ca sa putem raspunde "de ce nu e liber pe 11 octombrie".
    """
    buffer = partener["reguli_operationale"]["zile_buffer"]
    blocate: dict[date, str] = {}

    for r in rezervari_blocante(vehicul_id):
        start = date.fromisoformat(r["data_start"])
        sfarsit = date.fromisoformat(r["data_sfarsit"])

        zi = start
        while zi <= sfarsit:
            eticheta = r["status"]
            if datastore.status_necunoscut(r):
                # Blocam prudent, dar spunem clar ca e o problema de date:
                # altfel operatorul nu afla niciodata de greseala din JSON.
                eticheta = f"{r['status']} - STATUS NECUNOSCUT, blocat prudent"
            blocate[zi] = f"rezervare {r['id']} ({eticheta})"
            zi += timedelta(days=1)

        # buffer dupa rezervare
        for i in range(1, buffer + 1):
            blocate.setdefault(sfarsit + timedelta(days=i), f"buffer dupa {r['id']}")
        # buffer inainte de rezervare
        for i in range(1, buffer + 1):
            blocate.setdefault(start - timedelta(days=i), f"buffer inainte de {r['id']}")

    return blocate


def este_liber(vehicul_id: str, partener: dict, start: date, sfarsit: date) -> tuple[bool, list[str]]:
    """Verifica daca intervalul cerut e integral liber. Returneaza si motivele."""
    blocate = zile_blocate(vehicul_id, partener)
    motive: list[str] = []
    zi = start
    while zi <= sfarsit:
        if zi in blocate:
            motiv = f"{zi.isoformat()}: {blocate[zi]}"
            if motiv not in motive:
                motive.append(motiv)
        zi += timedelta(days=1)
    return (not motive), motive


def suprapuneri_provizorii(vehicul_id: str, start: date, sfarsit: date) -> list[dict]:
    """
    Rezervarile provizorii (cerere / oferta / contractare) care ating intervalul.
    NU blocheaza nimic - dar agentul trebuie sa le mentioneze clientului.
    """
    rezultat = []
    for r in rezervari_provizorii(vehicul_id):
        r_start = date.fromisoformat(r["data_start"])
        r_sfarsit = date.fromisoformat(r["data_sfarsit"])
        if r_start <= sfarsit and start <= r_sfarsit:
            rezultat.append(r)
    return rezultat


def ferestre_libere(
    vehicul_id: str, partener: dict, de_la: date, pana_la: date
) -> list[tuple[date, date]]:
    """Intervalele continue libere dintr-un orizont dat."""
    blocate = zile_blocate(vehicul_id, partener)
    ferestre: list[tuple[date, date]] = []
    inceput: date | None = None

    zi = de_la
    while zi <= pana_la:
        if zi in blocate:
            if inceput is not None:
                ferestre.append((inceput, zi - timedelta(days=1)))
                inceput = None
        elif inceput is None:
            inceput = zi
        zi += timedelta(days=1)

    if inceput is not None:
        ferestre.append((inceput, pana_la))
    return ferestre


# ---------------------------------------------------------------------
# 4. Ancorele de matching
# ---------------------------------------------------------------------
def reduceri_matching(vehicul_id: str, partener: dict) -> dict[date, dict]:
    """
    Harta zi -> reducere, construita din rezervarile care ancoreaza matching.

    Pentru fiecare rezervare ancora:
      - prima zi libera DUPA ea    = offset 0, apoi offset 1, 2...
      - ultima zi libera INAINTE   = offset 0, apoi inapoi in timp

    Reducerea apartine ZILEI de calendar, nu sejurului. Daca o zi ar primi doua
    reduceri (inchiriere scurta intre doua rezervari), pastram pe cea mai mare -
    niciodata suma, ca sa nu ajungem la zile gratuite.
    """
    matching = partener.get("matching", {})
    if not matching.get("activ", False):
        return {}

    scara = {s["offset"]: s["procent"] for s in matching.get("scara", [])}
    if not scara:
        return {}

    buffer = partener["reguli_operationale"]["zile_buffer"]
    harta: dict[date, dict] = {}

    def pune(zi: date, procent: int, motiv: str) -> None:
        existent = harta.get(zi)
        if existent is None or procent > existent["procent"]:
            harta[zi] = {"procent": procent, "motiv": motiv}

    for r in rezervari_ancora(vehicul_id):
        sfarsit = date.fromisoformat(r["data_sfarsit"])
        start = date.fromisoformat(r["data_start"])

        prima_libera = sfarsit + timedelta(days=buffer + 1)
        ultima_libera = start - timedelta(days=buffer + 1)

        for offset, procent in scara.items():
            pune(
                prima_libera + timedelta(days=offset),
                procent,
                f"la {offset} zile de prima zi libera dupa o inchiriere care se incheie pe {sfarsit.isoformat()}",
            )
            pune(
                ultima_libera - timedelta(days=offset),
                procent,
                f"la {offset} zile de ultima zi libera dinainte de o inchiriere care incepe pe {start.isoformat()}",
            )

    # O zi blocata nu poate primi reducere - nu se poate inchiria oricum.
    blocate = zile_blocate(vehicul_id, partener)
    return {zi: info for zi, info in harta.items() if zi not in blocate}


# ---------------------------------------------------------------------
# Utilitar: parsarea datelor primite de la LLM
# ---------------------------------------------------------------------
def parseaza_data(text: str, eticheta: str) -> tuple[date | None, str | None]:
    """
    Converteste un text in data. Returneaza (data, eroare) - exact unul e None.
    Mesajul de eroare e scris pentru LLM, nu pentru programator.
    """
    try:
        return date.fromisoformat(text.strip()), None
    except (ValueError, AttributeError):
        return None, (
            f"EROARE: {eticheta}={text!r} nu e o data valida. "
            f"Foloseste formatul AAAA-LL-ZZ, ex. 2026-10-13."
        )
