"""
Tool: find_matching_opportunities - ferestrele care merita umplute.

INIMA COMERCIALA A APLICATIEI.

Celelalte tool-uri raspund la ce intreaba clientul. Asta propune: cauta
intervalele in care o autorulota ar sta degeaba in parcare intre doua
inchirieri si calculeaza cat economiseste cineva care le umple.

Diferenta fata de check_availability:
    check_availability          -> "e liber pe 20-27 octombrie?"   (reactiv)
    find_matching_opportunities -> "daca mutati cu 2 zile, economisiti 136 EUR"
                                                                   (proactiv)
"""

from datetime import date, timedelta

from pydantic import BaseModel, Field

from tools import calendar_flota as cal
from tools import datastore
from tools.registry import register_tool


class MatchingParams(BaseModel):
    """Parametrii pentru tool-ul find_matching_opportunities."""

    data_de_la: str = Field(
        description="Inceputul intervalului in care se cauta, format AAAA-LL-ZZ."
    )
    data_pana_la: str = Field(
        description="Sfarsitul intervalului in care se cauta, format AAAA-LL-ZZ."
    )
    durata_zile: int | None = Field(
        default=None,
        ge=1,
        le=90,
        description=(
            "Cate zile vrea clientul sa stea. Omite-l ca sa se foloseasca durata "
            "minima a sezonului pentru fiecare fereastra."
        ),
    )
    vehicul_id: str | None = Field(
        default=None,
        description="Cauta doar pentru o autorulota anume. Omite ca sa cauti in toata flota.",
    )
    locuri_dormit_min: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Numarul minim de locuri de dormit.",
    )


def _economie(v: dict, partener: dict, reduceri: dict, start: date, durata: int) -> tuple[float, list[str]]:
    """Cat se economiseste pornind inchirierea la data data, pe durata data."""
    total = 0.0
    detalii: list[str] = []
    for i in range(durata):
        zi = start + timedelta(days=i)
        info = reduceri.get(zi)
        if not info:
            continue
        sezon = cal.sezon_pentru_zi(partener, zi)
        tarif = float(v["tarife_sezon"].get(sezon["cod"], 0)) if sezon else 0.0
        valoare = round(tarif * info["procent"] / 100, 2)
        total += valoare
        detalii.append(f"{zi.isoformat()} -{info['procent']}% ({valoare:.2f})")
    return round(total, 2), detalii


@register_tool
def find_matching_opportunities(params: MatchingParams) -> str:
    """Cauta perioadele in care inchirierea vine cu reduceri pentru zile lipite.

    Foloseste acest tool cand clientul are date flexibile, cand intreaba
    "cand e mai ieftin", cand cauti o alternativa la o perioada ocupata, sau
    cand vrei sa propui proactiv o economie.

    Reducerile apar pentru zilele imediat dupa sau imediat inainte de o alta
    inchiriere: prima zi libera -50%, urmatoarea -25%. Cu cat clientul preia
    mai aproape de data la care autorulota se elibereaza, cu atat plateste mai
    putin.

    Returneaza ferestrele ordonate dupa economia obtinuta.
    """
    de_la, eroare = cal.parseaza_data(params.data_de_la, "data_de_la")
    if eroare:
        return eroare
    pana_la, eroare = cal.parseaza_data(params.data_pana_la, "data_pana_la")
    if eroare:
        return eroare
    if pana_la < de_la:
        return f"EROARE: data_pana_la ({pana_la}) e inainte de data_de_la ({de_la})."
    if (pana_la - de_la).days > 400:
        return "EROARE: intervalul de cautare e prea mare. Foloseste cel mult un an."

    vehicule = datastore.toate_vehiculele()
    if params.vehicul_id:
        vehicule = [v for v in vehicule if v["id"].upper() == params.vehicul_id.strip().upper()]
        if not vehicule:
            return f"EROARE: nu exista autorulota {params.vehicul_id!r}."
    if params.locuri_dormit_min:
        vehicule = [v for v in vehicule if v["locuri_dormit"] >= params.locuri_dormit_min]
    if not vehicule:
        return "Nicio autorulota nu corespunde filtrelor cerute."

    oportunitati: list[dict] = []

    for v in vehicule:
        partener = datastore.partenerul_vehiculului(v)
        moneda = partener["reguli_operationale"]["moneda"]
        reduceri = cal.reduceri_matching(v["id"], partener)
        if not reduceri:
            continue

        for fereastra_start, fereastra_sfarsit in cal.ferestre_libere(v["id"], partener, de_la, pana_la):
            lungime_fereastra = (fereastra_sfarsit - fereastra_start).days + 1

            # Cautam ziua de start care aduce cea mai mare economie.
            #
            # ATENTIE: sezonul si durata minima se iau de la ZIUA DE START a
            # inchirierii propuse, NU de la inceputul ferestrei. O fereastra
            # libera poate acoperi mai multe sezoane (ex. octombrie - iunie),
            # iar regulile difera de la un capat la altul.
            cea_mai_buna = None
            for offset in range(lungime_fereastra):
                start = fereastra_start + timedelta(days=offset)

                sezon = cal.sezon_pentru_zi(partener, start)
                if sezon is None:
                    continue
                minim = sezon.get("durata_minima_zile", 1)
                durata = params.durata_zile or minim

                if durata < minim:
                    continue  # sub durata minima a sezonului in care s-ar prelua
                if offset + durata > lungime_fereastra:
                    continue  # nu incape in fereastra

                economie, detalii = _economie(v, partener, reduceri, start, durata)
                if economie <= 0:
                    continue
                if cea_mai_buna is None or economie > cea_mai_buna["economie"]:
                    cea_mai_buna = {
                        "start": start,
                        "sfarsit": start + timedelta(days=durata - 1),
                        "economie": economie,
                        "detalii": detalii,
                        "durata": durata,
                        "sezon": sezon["nume"],
                    }

            if cea_mai_buna:
                oportunitati.append(
                    {
                        **cea_mai_buna,
                        "vehicul": v,
                        "moneda": moneda,
                        "fereastra": (fereastra_start, fereastra_sfarsit),
                    }
                )

    if not oportunitati:
        return (
            f"Nu am gasit perioade cu reducere pentru zile lipite intre "
            f"{de_la.isoformat()} si {pana_la.isoformat()}"
            + (f" pentru o durata de {params.durata_zile} zile" if params.durata_zile else "")
            + ". Reducerile apar doar in jurul inchirierilor deja confirmate."
        )

    oportunitati.sort(key=lambda o: o["economie"], reverse=True)

    r: list[str] = []
    r.append(
        f"OPORTUNITATI CU REDUCERE, {de_la.isoformat()} - {pana_la.isoformat()} "
        f"({len(oportunitati)} gasite, ordonate dupa economie)"
    )
    r.append("")

    for o in oportunitati[:10]:
        v = o["vehicul"]
        r.append(
            f"  {v['id']} - {v['nume_comercial']} ({v['locuri_dormit']} locuri de dormit)"
        )
        r.append(
            f"      Perioada recomandata: {o['start'].isoformat()} - {o['sfarsit'].isoformat()} "
            f"({o['durata']} zile, {o['sezon'].lower()})"
        )
        r.append(f"      Zile cu reducere: {', '.join(o['detalii'])}")
        r.append(f"      ECONOMIE: {o['economie']:.2f} {o['moneda']}")
        r.append(
            f"      Fereastra libera completa: {o['fereastra'][0].isoformat()} - "
            f"{o['fereastra'][1].isoformat()}"
        )
        r.append("")

    if len(oportunitati) > 10:
        r.append(f"  ... si inca {len(oportunitati) - 10} oportunitati.")

    r.append(
        "Pentru devizul exact al oricareia dintre ele, foloseste calculate_quote "
        "cu datele recomandate."
    )
    return "\n".join(r)
