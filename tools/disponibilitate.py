"""
Tool: check_availability - ce autorulote sunt libere intr-o perioada.

Tool-ul asta face trei lucruri pe care un LLM nu le poate face singur:
  1. citeste rezervarile reale si aplica buffer-ul fiecarui partener
  2. distinge statusurile ferme de cele provizorii, prin steaguri
  3. verifica durata minima, care difera pe sezon si pe partener
"""

from pydantic import BaseModel, Field

from tools import calendar_flota as cal
from tools import datastore
from tools.perioada import PerioadaInchiriere
from tools.registry import register_tool


class DisponibilitateParams(BaseModel):
    """Parametrii pentru tool-ul check_availability."""

    data_start: str = Field(
        description="Data de preluare, format AAAA-LL-ZZ. Ex: '2026-10-13'."
    )
    data_sfarsit: str = Field(
        description="Data de predare, format AAAA-LL-ZZ. Trebuie sa fie >= data_start."
    )
    locuri_dormit_min: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Numarul minim de locuri de dormit. Foloseste-l cand clientul spune cati sunt.",
    )
    tip: str | None = Field(
        default=None,
        description=(
            "Filtreaza dupa tipul autorulotei: 'integral', 'semi-integral', "
            "'alcov', 'camper van', 'profilat'. Omite daca nu s-a cerut."
        ),
    )
    transmisie: str | None = Field(
        default=None,
        description="Filtreaza dupa transmisie: 'automata' sau 'manuala'. Omite daca nu s-a cerut.",
    )
    vehicul_id: str | None = Field(
        default=None,
        description=(
            "Verifica o singura autorulota anume, dupa id (ex. 'GC-001'). "
            "Omite ca sa cauti in toata flota."
        ),
    )


@register_tool
def check_availability(params: DisponibilitateParams) -> str:
    """Verifica ce autorulote sunt libere intr-o perioada data.

    Foloseste acest tool ORI DE CATE ORI clientul intreaba daca ceva e liber,
    ce optiuni are pentru niste date, sau inainte sa faci o oferta. Nu
    presupune niciodata ca o autorulota e disponibila.

    Tine cont automat de rezervarile existente, de zilele de pregatire dintre
    inchirieri si de durata minima de inchiriere, care difera pe sezon.
    Raporteaza separat perioadele pentru care exista deja cereri in lucru.
    """
    start, eroare = cal.parseaza_data(params.data_start, "data_start")
    if eroare:
        return eroare
    sfarsit, eroare = cal.parseaza_data(params.data_sfarsit, "data_sfarsit")
    if eroare:
        return eroare

    if sfarsit < start:
        return (
            f"EROARE: data_sfarsit ({sfarsit}) e inainte de data_start ({start}). "
            f"Verifica ordinea datelor."
        )

    candidati = datastore.toate_vehiculele()

    if params.vehicul_id:
        candidati = [v for v in candidati if v["id"].upper() == params.vehicul_id.strip().upper()]
        if not candidati:
            return (
                f"EROARE: nu exista nicio autorulota cu identificatorul "
                f"{params.vehicul_id!r}."
            )

    if params.locuri_dormit_min:
        candidati = [v for v in candidati if v["locuri_dormit"] >= params.locuri_dormit_min]
    if params.tip:
        candidati = [v for v in candidati if v["tip"].lower() == params.tip.strip().lower()]
    if params.transmisie:
        candidati = [
            v for v in candidati if v["transmisie"].lower() == params.transmisie.strip().lower()
        ]

    if not candidati:
        return (
            "Niciun vehicul din flota nu corespunde filtrelor cerute "
            "(inainte de a verifica disponibilitatea). Incearca criterii mai largi."
        )

    libere: list[str] = []
    ocupate: list[str] = []
    prea_scurte: list[str] = []

    for v in candidati:
        partener = datastore.partenerul_vehiculului(v)
        moneda = datastore.moneda(v)
        perioada = PerioadaInchiriere.din_date(partener, start, sfarsit)
        unitati = perioada.unitati
        eticheta_unitati = perioada.eticheta
        unitate_singular = perioada.unitate_singular

        liber, motive = cal.este_liber(v["id"], partener, start, sfarsit)
        if not liber:
            ocupate.append(f"  {v['id']} - {v['nume_comercial']}: ocupat ({motive[0]})")
            continue

        # Durata minima se ia dupa sezonul zilei de preluare.
        sezon = cal.sezon_pentru_zi(partener, start)
        if sezon is None:
            ocupate.append(
                f"  {v['id']} - {v['nume_comercial']}: ziua de {start} nu apartine niciunui sezon "
                f"(problema de configurare)"
            )
            continue

        minim = sezon.get("durata_minima_zile", 1)
        if unitati < minim:
            prea_scurte.append(
                f"  {v['id']} - {v['nume_comercial']}: e liber, dar in {sezon['nume'].lower()} "
                f"durata minima e {minim} {eticheta_unitati}, iar perioada ceruta are {unitati}"
            )
            continue

        try:
            tarif = datastore.tarif_sezon(v, sezon["cod"])
        except KeyError as e:
            # Fara tarif nu avem ce oferi: mai bine spunem ca lipseste decat
            # sa afisam vehiculul ca disponibil "la 0".
            ocupate.append(f"  {v['id']} - {v['nume_comercial']}: EROARE DE CONFIGURARE - {e.args[0]}")
            continue
        rand = [
            f"  {v['id']} - {v['nume_comercial']} ({v['tip']}, {v['locuri_dormit']} locuri de dormit, "
            f"{v['transmisie']}, permis {v['permis_necesar']})",
            f"      {unitati} {eticheta_unitati} | tarif {sezon['nume'].lower()}: "
            f"{tarif} {moneda}/{unitate_singular} | predare: {v['punct_predare']}",
        ]

        # Documentele expirate nu scot vehiculul din lista (pot fi reinnoite
        # pana la preluare), dar trebuie spuse clientului.
        for problema in datastore.documente_expirate(v["id"], perioada.predare):
            rand.append(f"      ATENTIE: {problema}")

        # Zile cu reducere de matching care cad in perioada ceruta
        reduceri = cal.reduceri_matching(v["id"], partener)
        in_perioada = {
            zi: info for zi, info in reduceri.items() if start <= zi <= sfarsit
        }
        if in_perioada:
            detalii = ", ".join(
                f"{zi.isoformat()} -{info['procent']}%" for zi, info in sorted(in_perioada.items())
            )
            rand.append(f"      AVANTAJ: zile cu reducere in aceasta perioada: {detalii}")

        # Cereri in lucru pe aceleasi date
        provizorii = cal.suprapuneri_provizorii(v["id"], start, sfarsit)
        if provizorii:
            statusuri = ", ".join(
                f"{datastore.status_rezervare(p['status'])['nume'].lower()} "
                f"({p['data_start']} - {p['data_sfarsit']})"
                for p in provizorii
            )
            rand.append(f"      ATENTIE: exista deja interes pe aceste date - {statusuri}")

        libere.append("\n".join(rand))

    r: list[str] = []
    r.append(
        f"DISPONIBILITATE pentru {start.isoformat()} - {sfarsit.isoformat()} "
        f"({len(candidati)} autorulote verificate)"
    )
    r.append("")

    if libere:
        r.append(f"DISPONIBILE ({len(libere)}):")
        r.extend(libere)
    else:
        r.append("DISPONIBILE: niciuna.")
    r.append("")

    if prea_scurte:
        r.append(f"LIBERE, DAR SUB DURATA MINIMA ({len(prea_scurte)}):")
        r.extend(prea_scurte)
        r.append("")

    if ocupate:
        r.append(f"INDISPONIBILE ({len(ocupate)}):")
        r.extend(ocupate)

    return "\n".join(r).rstrip()
