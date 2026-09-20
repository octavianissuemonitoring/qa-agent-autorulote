"""
Tool: calculate_quote - devizul complet al unei inchirieri.

TOOL-UL CENTRAL AL APLICATIEI.

De ce e obligatoriu sa fie tool si nu treaba LLM-ului (slide S6.1):
    Calculul are zece etape, tarife care se schimba zi de zi, trei feluri de
    discount care se compun in cascada si reguli diferite pe partener. Un LLM
    ar "estima" un rezultat plauzibil. Aici plauzibil inseamna factura gresita.

    Regula din curs: daca raspunsul gresit are consecinte financiare -> tool.

ORDINEA DE CALCUL (nu e negociabila - schimbi ordinea, schimbi suma):
     1. unitati facturabile: zile calendaristice SAU nopti, dupa partener
     2. verificare durata minima (dupa sezonul zilei de preluare)
     3. pret per zi, fiecare zi la sezonul EI
     4. matching: reduceri pe zile individuale (-50% / -25%)
     5. subtotal = suma zilelor
     6. x (1 - discount durata)        \\
     7. x (1 - discount early booking) /  cascada
     8. + pachet km
     9. + extraoptiuni
    10. + taxa de curatenie
    11. = TOTAL. Garantia se raporteaza separat, e rambursabila.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from tools import calendar_flota as cal
from tools import datastore
from tools.perioada import PerioadaInchiriere
from tools.registry import register_tool


class OfertaParams(BaseModel):
    """Parametrii pentru tool-ul calculate_quote."""

    vehicul_id: str = Field(
        description="Identificatorul autorulotei, ex: 'GC-001'. Obligatoriu."
    )
    data_start: str = Field(description="Data de preluare, format AAAA-LL-ZZ.")
    data_sfarsit: str = Field(description="Data de predare, format AAAA-LL-ZZ.")
    pachet_km: str | None = Field(
        default=None,
        description=(
            "Codul pachetului de kilometri: 'standard', 'redus' sau 'nelimitat'. "
            "Omite-l ca sa se foloseasca pachetul implicit al partenerului."
        ),
    )
    km_estimati: int | None = Field(
        default=None,
        ge=0,
        le=50000,
        description=(
            "Cati kilometri estimeaza clientul ca va parcurge in total. "
            "Necesar ca sa calculezi eventualele depasiri de plafon."
        ),
    )
    extraoptiuni: list[str] | None = Field(
        default=None,
        description=(
            "Lista de id-uri de extraoptiuni cerute de client, ex: "
            "['suport_biciclete', 'scaun_copil']. Id-urile exacte se afla cu "
            "get_vehicle_details. Omite daca nu s-a cerut nimic suplimentar."
        ),
    )
    varsta_sofer: int | None = Field(
        default=None,
        ge=16,
        le=100,
        description="Varsta soferului, pentru verificarea conditiilor de inchiriere.",
    )
    vechime_permis_ani: int | None = Field(
        default=None,
        ge=0,
        le=80,
        description="De cati ani are soferul permisul de conducere.",
    )


def _bani(suma: float) -> str:
    return f"{suma:,.2f}".replace(",", " ")


@register_tool
def calculate_quote(params: OfertaParams) -> str:
    """Calculeaza devizul complet si detaliat al unei inchirieri.

    Foloseste acest tool ORI DE CATE ORI clientul intreaba cat costa, cere o
    oferta, sau vrea sa compare preturi. Nu calcula niciodata singur un pret -
    nici macar o inmultire simpla de tipul zile x tarif.

    Devizul tine cont automat de: sezonul fiecarei zile in parte, reducerile
    pentru zilele lipite de alte inchirieri, discountul pe durata, discountul
    pentru rezervare din timp, pachetul de kilometri, extraoptiunile cerute,
    taxa de curatenie si garantia.

    Rezultatul contine explicatii pe fiecare linie - foloseste-le ca sa arati
    clientului DE CE pretul e cel afisat si unde a economisit.
    """
    # -----------------------------------------------------------------
    # 0. Validari de intrare
    # -----------------------------------------------------------------
    v = datastore.vehicul(params.vehicul_id)
    if v is None:
        disponibile = ", ".join(x["id"] for x in datastore.toate_vehiculele())
        return f"EROARE: nu exista autorulota {params.vehicul_id!r}. Valide: {disponibile}."

    start, eroare = cal.parseaza_data(params.data_start, "data_start")
    if eroare:
        return eroare
    sfarsit, eroare = cal.parseaza_data(params.data_sfarsit, "data_sfarsit")
    if eroare:
        return eroare
    if sfarsit < start:
        return f"EROARE: data_sfarsit ({sfarsit}) e inainte de data_start ({start})."

    partener = datastore.partenerul_vehiculului(v)
    reguli = partener["reguli_operationale"]
    moneda = reguli["moneda"]
    avertismente: list[str] = []

    # -----------------------------------------------------------------
    # 1. Perioada, in reprezentarea partenerului (zile sau nopti)
    # -----------------------------------------------------------------
    perioada = PerioadaInchiriere.din_date(partener, start, sfarsit)
    pe_nopti = perioada.pe_nopti
    eticheta = perioada.eticheta
    unitate_singular = perioada.unitate_singular
    unitati = perioada.unitati
    if unitati <= 0:
        return (
            f"EROARE: perioada {start} - {sfarsit} nu produce nicio unitate facturabila. "
            f"In sistemul pe nopti, preluarea si predarea nu pot fi in aceeasi zi."
        )
    zile = perioada.zile_facturate

    # -----------------------------------------------------------------
    # 2. Durata minima (dupa sezonul zilei de preluare)
    # -----------------------------------------------------------------
    sezon_preluare = cal.sezon_pentru_zi(partener, start)
    if sezon_preluare is None:
        return (
            f"EROARE de configurare: ziua {start} nu apartine niciunui sezon definit. "
            f"Verifica sezoanele partenerului in data/parteneri.json."
        )
    minim = sezon_preluare.get("durata_minima_zile", 1)
    if unitati < minim:
        return (
            f"NU SE POATE OFERTA: in {sezon_preluare['nume'].lower()} durata minima de "
            f"inchiriere este {minim} {eticheta}, iar perioada ceruta are doar {unitati}. "
            f"Propune clientului o perioada de cel putin {minim} {eticheta}."
        )

    # -----------------------------------------------------------------
    # Disponibilitate (nu opreste calculul, dar se semnaleaza)
    # -----------------------------------------------------------------
    liber, motive = cal.este_liber(v["id"], partener, start, sfarsit)
    if not liber:
        avertismente.append(
            f"AUTORULOTA NU E DISPONIBILA in aceasta perioada: {motive[0]}. "
            f"Devizul de mai jos e doar informativ."
        )
    # Documentele nu blocheaza oferta, dar clientul trebuie sa stie (pot fi
    # reinnoite pana la preluare - de aceea e avertisment, nu refuz).
    for problema in datastore.documente_expirate(v["id"], perioada.predare):
        avertismente.append(f"DOCUMENTE: {problema}.")

    for p in cal.suprapuneri_provizorii(v["id"], start, sfarsit):
        avertismente.append(
            f"Exista deja interes pe aceste date "
            f"({datastore.status_rezervare(p['status'])['nume'].lower()}, "
            f"{p['data_start']} - {p['data_sfarsit']})."
        )

    # -----------------------------------------------------------------
    # Conditii sofer
    # -----------------------------------------------------------------
    conditii = partener["conditii_sofer"]
    if params.varsta_sofer is not None and params.varsta_sofer < conditii["varsta_minima"]:
        avertismente.append(
            f"Soferul are {params.varsta_sofer} ani, sub minimul de "
            f"{conditii['varsta_minima']} ani cerut."
        )
    if (
        params.vechime_permis_ani is not None
        and params.vechime_permis_ani < conditii["vechime_permis_ani"]
    ):
        avertismente.append(
            f"Vechimea permisului este de {params.vechime_permis_ani} ani, sub minimul de "
            f"{conditii['vechime_permis_ani']} ani cerut."
        )

    # -----------------------------------------------------------------
    # 3 + 4. Pretul fiecarei zile, cu sezonul ei si reducerea de matching
    # -----------------------------------------------------------------
    reduceri = cal.reduceri_matching(v["id"], partener)
    randuri_zile: list[str] = []
    subtotal = 0.0
    economie_matching = 0.0
    zile_reduse: list[str] = []

    for zi in zile:
        sezon = cal.sezon_pentru_zi(partener, zi)
        if sezon is None:
            return (
                f"EROARE DE CONFIGURARE: ziua {zi.isoformat()} nu apartine niciunui sezon "
                f"definit pentru partenerul {partener['id']}. Verifica data/parteneri.json."
            )
        cod = sezon["cod"]

        try:
            tarif = datastore.tarif_sezon(v, cod)
        except KeyError as e:
            # Fail closed (S6.6): mai bine oprim oferta decat sa trimitem
            # clientului un pret in care o zi costa 0.
            return f"EROARE DE CONFIGURARE: {e.args[0]}"

        reducere = reduceri.get(zi)
        if reducere:
            procent = reducere["procent"]
            valoare = round(tarif * procent / 100, 2)
            pret_zi = round(tarif - valoare, 2)
            economie_matching += valoare
            zile_reduse.append(f"{zi.isoformat()} (-{procent}%)")
            randuri_zile.append(
                f"    {zi.isoformat()}  {sezon['nume']:16} {_bani(tarif):>10}"
                f"   -{procent}%  ->{_bani(pret_zi):>10} {moneda}"
            )
        else:
            pret_zi = tarif
            randuri_zile.append(
                f"    {zi.isoformat()}  {sezon['nume']:16} {_bani(tarif):>10}"
                f"          {_bani(pret_zi):>10} {moneda}"
            )
        subtotal += pret_zi

    subtotal = round(subtotal, 2)
    subtotal_fara_matching = round(subtotal + economie_matching, 2)

    # -----------------------------------------------------------------
    # 6. Discount pe durata (grila sezonului de preluare)
    # -----------------------------------------------------------------
    grila_durata = partener["discounturi"]["durata"].get(sezon_preluare["cod"], [])
    praguri_atinse = [p for p in grila_durata if unitati >= p["min_zile"]]
    procent_durata = max((p["procent"] for p in praguri_atinse), default=0)
    valoare_durata = round(subtotal * procent_durata / 100, 2)
    dupa_durata = round(subtotal - valoare_durata, 2)

    # -----------------------------------------------------------------
    # 7. Early booking (in cascada, pe ce a ramas)
    # -----------------------------------------------------------------
    azi = datetime.now(ZoneInfo("Europe/Bucharest")).date()
    zile_pana_la_preluare = (start - azi).days
    regula_early = partener["discounturi"]["early_booking"].get(sezon_preluare["cod"], {})
    procent_early = 0
    if regula_early and zile_pana_la_preluare >= regula_early.get("min_zile_inainte", 10**9):
        procent_early = regula_early["procent"]
    valoare_early = round(dupa_durata * procent_early / 100, 2)
    dupa_early = round(dupa_durata - valoare_early, 2)

    # -----------------------------------------------------------------
    # 8. Pachetul de kilometri
    # -----------------------------------------------------------------
    pachete = {p["cod"]: p for p in partener["pachete_km"]}
    if params.pachet_km:
        pachet = pachete.get(params.pachet_km.strip().lower())
        if pachet is None:
            return (
                f"EROARE: pachetul de kilometri {params.pachet_km!r} nu exista. "
                f"Optiuni valide: {', '.join(pachete)}."
            )
    else:
        pachet = next((p for p in partener["pachete_km"] if p.get("implicit")), None)
        if pachet is None:
            return "EROARE de configurare: partenerul nu are niciun pachet de kilometri implicit."

    cost_km = round(pachet.get("supliment_pe_zi", 0) * unitati, 2)
    randuri_km: list[str] = []
    if pachet["km_inclusi_pe_zi"] is None:
        randuri_km.append(f"    Pachet {pachet['nume']}: kilometraj nelimitat")
    else:
        plafon = pachet["km_inclusi_pe_zi"] * unitati
        randuri_km.append(
            f"    Pachet {pachet['nume']}: {pachet['km_inclusi_pe_zi']} km/{unitate_singular} "
            f"-> {plafon} km inclusi"
        )
        if params.km_estimati is not None and params.km_estimati > plafon:
            depasire = params.km_estimati - plafon
            cost_depasire = round(depasire * pachet["pret_km_suplimentar"], 2)
            cost_km += cost_depasire
            randuri_km.append(
                f"    Depasire estimata: {depasire} km x {pachet['pret_km_suplimentar']} "
                f"{moneda} = {_bani(cost_depasire)} {moneda}"
            )
        elif params.km_estimati is None:
            avertismente.append(
                "Nu s-a estimat numarul de kilometri - eventualele depasiri de plafon "
                "nu sunt incluse in total."
            )
    if pachet.get("supliment_pe_zi", 0):
        randuri_km.append(
            f"    Supliment pachet: {pachet['supliment_pe_zi']} {moneda} x {unitati} "
            f"{eticheta} = {_bani(pachet['supliment_pe_zi'] * unitati)} {moneda}"
        )

    # -----------------------------------------------------------------
    # 9. Extraoptiuni
    # -----------------------------------------------------------------
    catalog = {e["id"]: e for e in datastore.extraoptiunile_vehiculului(v)}
    cerute = params.extraoptiuni or []
    cost_extras = 0.0
    randuri_extras: list[str] = []

    for extra_id in cerute:
        e = catalog.get(extra_id.strip())
        if e is None:
            valide = ", ".join(sorted(catalog))
            return (
                f"EROARE: extraoptiunea {extra_id!r} nu exista pentru aceasta autorulota. "
                f"Optiuni valide: {valide}."
            )
        if e["regim"] == "indisponibil":
            avertismente.append(
                f"{e['nume']}: nu se poate monta pe aceasta autorulota, nu a fost inclusa in deviz."
            )
            continue
        if e["regim"] == "inclus":
            randuri_extras.append(f"    {e['nume']}: INCLUS, fara cost")
            continue
        cost = e["pret"] * unitati if e["unitate_tarifare"] == "pe_zi" else e["pret"]
        cost = round(cost, 2)
        cost_extras += cost
        unitate_txt = f"{e['pret']} {moneda} x {unitati} {eticheta}" if e["unitate_tarifare"] == "pe_zi" else f"{e['pret']} {moneda}"
        randuri_extras.append(f"    {e['nume']}: {unitate_txt} = {_bani(cost)} {moneda}")

    # Dotarile incluse din oficiu (chiar daca nu au fost cerute) - argument de vanzare
    incluse_automat = [e for e in catalog.values() if e["regim"] == "inclus"]
    valoare_incluse = 0.0
    for e in incluse_automat:
        valoare_incluse += e["pret_lista"] * unitati if e["unitate_tarifare"] == "pe_zi" else e["pret_lista"]
    valoare_incluse = round(valoare_incluse, 2)

    # -----------------------------------------------------------------
    # 10 + 11. Taxa de curatenie si totalul
    # -----------------------------------------------------------------
    taxa_curatenie = float(reguli["taxa_curatenie"])
    total = round(dupa_early + cost_km + cost_extras + taxa_curatenie, 2)
    economie_totala = round(economie_matching + valoare_durata + valoare_early, 2)

    # -----------------------------------------------------------------
    # Raport
    # -----------------------------------------------------------------
    r: list[str] = []
    r.append(f"DEVIZ - {v['id']} {v['nume_comercial']}")
    r.append(f"Perioada: {start.isoformat()} - {sfarsit.isoformat()}  ({unitati} {eticheta})")
    r.append(f"Sistem de calcul: pe {eticheta}")
    r.append("")

    if avertismente:
        r.append("ATENTIE:")
        for a in avertismente:
            r.append(f"  ! {a}")
        r.append("")

    r.append(f"1. TARIF PE {eticheta.upper()}, fiecare la sezonul ei")
    r.extend(randuri_zile)
    if economie_matching:
        r.append(
            f"    Reducere pentru zile lipite de alte inchirieri: "
            f"-{_bani(economie_matching)} {moneda}  ({', '.join(zile_reduse)})"
        )
    r.append(f"    SUBTOTAL: {_bani(subtotal)} {moneda}")
    r.append("")

    r.append("2. DISCOUNTURI PE SUBTOTAL (in cascada)")
    if procent_durata:
        prag = max(p["min_zile"] for p in praguri_atinse)
        r.append(
            f"    Durata ({unitati} {eticheta}, prag {prag}+, {sezon_preluare['nume'].lower()}): "
            f"-{procent_durata}% = -{_bani(valoare_durata)} {moneda}  -> {_bani(dupa_durata)} {moneda}"
        )
    else:
        praguri = ", ".join(f"{p['min_zile']} {eticheta} = -{p['procent']}%" for p in grila_durata)
        r.append(f"    Durata: fara discount. Praguri disponibile: {praguri or 'niciunul'}")
    if procent_early:
        r.append(
            f"    Rezervare din timp ({zile_pana_la_preluare} zile inainte, prag "
            f"{regula_early['min_zile_inainte']}+): -{procent_early}% = -{_bani(valoare_early)} "
            f"{moneda}  -> {_bani(dupa_early)} {moneda}"
        )
    elif regula_early:
        lipsa = regula_early["min_zile_inainte"] - zile_pana_la_preluare
        if lipsa > 0:
            r.append(
                f"    Rezervare din timp: fara discount. Mai lipsesc {lipsa} zile pana la pragul "
                f"de {regula_early['min_zile_inainte']} zile in avans (-{regula_early['procent']}%)"
            )
    r.append(f"    DUPA DISCOUNTURI: {_bani(dupa_early)} {moneda}")
    r.append("")

    r.append("3. KILOMETRI")
    r.extend(randuri_km)
    r.append(f"    Cost kilometri: {_bani(cost_km)} {moneda}")
    r.append("")

    if randuri_extras or incluse_automat:
        r.append("4. EXTRAOPTIUNI")
        if randuri_extras:
            r.extend(randuri_extras)
        if incluse_automat and valoare_incluse:
            nume = ", ".join(e["nume"] for e in incluse_automat)
            r.append(
                f"    Incluse din oficiu ({nume}): 0 {moneda} "
                f"- valoare de lista {_bani(valoare_incluse)} {moneda}"
            )
        r.append(f"    Cost extraoptiuni: {_bani(cost_extras)} {moneda}")
        r.append("")

    r.append("5. TAXE")
    r.append(f"    Curatenie si pregatire: {_bani(taxa_curatenie)} {moneda}")
    r.append("")

    r.append("=" * 58)
    r.append(f"TOTAL DE PLATA: {_bani(total)} {moneda}")
    r.append(f"GARANTIE (rambursabila la predare): {_bani(v['garantie'])} {moneda}")
    r.append("=" * 58)

    if economie_totala or valoare_incluse:
        r.append("")
        r.append("ECONOMIE FATA DE TARIFUL DE LISTA:")
        if economie_matching:
            r.append(
                f"    Zile lipite de alte inchirieri: {_bani(economie_matching)} {moneda}"
            )
        if valoare_durata:
            r.append(f"    Discount de durata: {_bani(valoare_durata)} {moneda}")
        if valoare_early:
            r.append(f"    Rezervare din timp: {_bani(valoare_early)} {moneda}")
        if valoare_incluse:
            r.append(f"    Dotari incluse fara cost: {_bani(valoare_incluse)} {moneda}")
        r.append(
            f"    TOTAL ECONOMISIT: {_bani(economie_totala + valoare_incluse)} {moneda} "
            f"(fata de {_bani(subtotal_fara_matching + cost_km + cost_extras + taxa_curatenie + valoare_incluse)} "
            f"{moneda} la tarif intreg)"
        )

    return "\n".join(r)
