"""
Tool: get_vehicle_details - fisa completa a unei autorulote.

Aici se vede cascada pe 3 niveluri in actiune: tool-ul primeste un id si
returneaza date compuse din catalogul global + grila partenerului + catalogul
vehiculului, fara ca agentul sa stie ca exista trei fisiere.

CONSTRANGERE WHITE-LABEL:
    Tool-ul foloseste partenerul ca sa afle preturile si sezoanele, dar NU
    scrie niciodata numele partenerului in textul returnat. Ce nu ajunge in
    text, agentul nu poate scapa in conversatie.
"""

from pydantic import BaseModel, Field

from tools import datastore
from tools.registry import register_tool


class VehiculParams(BaseModel):
    """Parametrii pentru tool-ul get_vehicle_details."""

    vehicul_id: str = Field(
        description=(
            "Identificatorul autorulotei, ex: 'GC-001', 'AR-002'. "
            "Daca nu il cunosti, foloseste intai check_availability ca sa obtii "
            "lista de identificatori."
        )
    )


def _linie_extraoptiune(e: dict, moneda: str) -> str:
    if e["regim"] == "inclus":
        unitate = "pe zi" if e["unitate_tarifare"] == "pe_zi" else "per inchiriere"
        bucati = ["  + " + e["nume"] + " - INCLUS"]
        if e.get("cantitate"):
            bucati.append(f"(x{e['cantitate']})")
        bucati.append(f"[valoare de lista: {e['pret_lista']} {moneda} {unitate}]")
        return " ".join(bucati)

    if e["regim"] == "indisponibil":
        return f"  - {e['nume']} - nu se poate monta pe aceasta autorulota"

    unitate = "pe zi" if e["unitate_tarifare"] == "pe_zi" else "per inchiriere"
    return f"  o {e['nume']} - {e['pret']} {moneda} {unitate}"


@register_tool
def get_vehicle_details(params: VehiculParams) -> str:
    """Returneaza fisa tehnica si comerciala completa a unei autorulote.

    Foloseste acest tool cand clientul intreaba despre o autorulota anume:
    cate persoane dorm, ce permis trebuie, ce consuma, ce dotari are, ce
    extraoptiuni sunt incluse si care se platesc separat, cat e garantia,
    ce tarif are pe fiecare sezon.

    Foloseste-l si cand compari doua autorulote - apeleaza-l o data pentru
    fiecare. Nu descrie niciodata o autorulota din memorie.
    """
    v = datastore.vehicul(params.vehicul_id)
    if v is None:
        disponibile = ", ".join(x["id"] for x in datastore.toate_vehiculele())
        return (
            f"EROARE: nu exista nicio autorulota cu identificatorul "
            f"{params.vehicul_id!r}. Identificatori valizi: {disponibile}."
        )

    partener = datastore.partenerul_vehiculului(v)
    moneda = datastore.moneda(v)
    reguli = partener["reguli_operationale"]
    nume_sezoane = {s["cod"]: s for s in partener["sezoane"]}

    r: list[str] = []
    r.append(f"AUTORULOTA {v['id']} - {v['nume_comercial']}")
    r.append(f"Tip: {v['tip']} | An: {v['an_fabricatie']} | Producator: {v['producator']}")
    r.append("")

    r.append("CONDUCERE SI GABARIT")
    r.append(
        f"  Masa maxima autorizata: {v['masa_maxima_autorizata_kg']} kg "
        f"-> necesita permis categoria {v['permis_necesar']}"
    )
    r.append(
        f"  Dimensiuni: {v['lungime_m']} m lungime, {v['inaltime_m']} m inaltime, "
        f"{v['latime_m']} m latime"
    )
    r.append(f"  Transmisie: {v['transmisie']} | Combustibil: {v['combustibil']}")
    r.append(
        f"  Consum mediu: {v['consum_mediu_l_100km']} l/100 km | "
        f"Rezervor: {v['capacitate_rezervor_l']} l"
    )
    r.append("")

    r.append("CAPACITATE")
    r.append(f"  Locuri de dormit: {v['locuri_dormit']}")
    r.append(f"  Locuri de calatorie omologate: {v['locuri_calatorie_omologate']}")
    r.append(
        f"  Apa curata: {v['capacitate_apa_curata_l']} l | "
        f"Apa uzata: {v['capacitate_apa_uzata_l']} l"
    )
    r.append("")

    r.append("DOTARI STANDARD")
    for d in v.get("dotari", []):
        r.append(f"  - {d}")
    r.append("")

    r.append(f"TARIFE PE SEZON ({moneda}/{'noapte' if reguli['sistem_calcul'] == 'nopti' else 'zi'})")
    for cod, pret in v["tarife_sezon"].items():
        sezon = nume_sezoane.get(cod, {})
        perioade = ", ".join(
            f"{p['de_la']} - {p['pana_la']}" for p in sezon.get("perioade", [])
        )
        r.append(
            f"  {sezon.get('nume', cod)}: {pret} {moneda} "
            f"(perioade {perioade}; minim {sezon.get('durata_minima_zile', '?')} zile)"
        )
    r.append("")

    extraoptiuni = datastore.extraoptiunile_vehiculului(v)
    incluse = [e for e in extraoptiuni if e["regim"] == "inclus"]
    optionale = [e for e in extraoptiuni if e["regim"] == "optional"]
    indisponibile = [e for e in extraoptiuni if e["regim"] == "indisponibil"]

    if incluse:
        r.append("EXTRAOPTIUNI INCLUSE IN PRET (nu se taxeaza)")
        for e in incluse:
            r.append(_linie_extraoptiune(e, moneda))
        r.append("")

    if optionale:
        r.append("EXTRAOPTIUNI DISPONIBILE CONTRA COST")
        for e in optionale:
            r.append(_linie_extraoptiune(e, moneda))
        r.append("")

    if indisponibile:
        r.append("NU SE POT ADAUGA PE ACEASTA AUTORULOTA")
        for e in indisponibile:
            r.append(_linie_extraoptiune(e, moneda))
        r.append("")

    r.append("CONDITII DE INCHIRIERE")
    r.append(f"  Punct de predare: {v['punct_predare']}")
    r.append(f"  Garantie (rambursabila): {v['garantie']} {moneda}")
    r.append(f"  Taxa de curatenie: {reguli['taxa_curatenie']} {moneda} per inchiriere")
    r.append(
        f"  Sistem de calcul: pe {reguli['sistem_calcul']} "
        f"({'se taxeaza noptile' if reguli['sistem_calcul'] == 'nopti' else 'se taxeaza fiecare zi calendaristica'})"
    )
    conditii = partener["conditii_sofer"]
    r.append(
        f"  Sofer: minim {conditii['varsta_minima']} ani, "
        f"minim {conditii['vechime_permis_ani']} ani vechime permis"
    )

    if v.get("observatii"):
        r.append("")
        r.append(f"Observatii: {v['observatii']}")

    return "\n".join(r)
