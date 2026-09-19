"""
Tool: check_fleet_status - scadentele tehnice si de conformitate.

Spre deosebire de celelalte tool-uri, asta NU serveste clientul final, ci
operatorul de flota: ce expira in curand, ce vehicul trebuie scos din
circulatie, ce revizie se apropie.

Regula de calcul a reviziei: scadenta e la km SAU la data, care vine prima.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from tools import datastore
from tools.registry import register_tool

DOCUMENTE = {
    "itp_expira": "ITP",
    "rca_expira": "RCA",
    "casco_expira": "CASCO",
    "rovinieta_expira": "Rovinieta",
}


class FleetStatusParams(BaseModel):
    """Parametrii pentru tool-ul check_fleet_status."""

    vehicul_id: str | None = Field(
        default=None,
        description=(
            "Identificatorul unei autorulote anume (ex. 'GC-001'). "
            "Omite-l ca sa verifici toata flota."
        ),
    )
    zile_orizont: int = Field(
        default=30,
        ge=1,
        le=365,
        description=(
            "Peste cate zile in avans se cauta scadentele. Implicit 30. "
            "Foloseste 90 sau 180 pentru planificare pe termen mai lung."
        ),
    )


def _analizeaza(v: dict, m: dict, azi: date, orizont: int) -> tuple[list[str], list[str]]:
    """Returneaza (expirate, expira_curand) pentru un vehicul."""
    expirate: list[str] = []
    curand: list[str] = []

    for camp, eticheta in DOCUMENTE.items():
        try:
            scadenta = date.fromisoformat(m[camp])
        except (KeyError, ValueError):
            expirate.append(f"{eticheta}: data lipseste sau e invalida in fisa de mentenanta")
            continue

        zile = (scadenta - azi).days
        if zile < 0:
            expirate.append(f"{eticheta} EXPIRAT de {abs(zile)} zile (la {scadenta.isoformat()})")
        elif zile <= orizont:
            curand.append(f"{eticheta} expira in {zile} zile (la {scadenta.isoformat()})")

    # Revizie la kilometraj
    km_actuali = m.get("km_actuali", 0)
    km_scadenta = m.get("ultima_revizie_km", 0) + m.get("interval_revizie_km", 0)
    km_ramasi = km_scadenta - km_actuali
    if km_ramasi <= 0:
        expirate.append(f"REVIZIE depasita cu {abs(km_ramasi)} km (scadenta la {km_scadenta} km)")
    elif km_ramasi <= 2000:
        curand.append(f"Revizie la {km_ramasi} km (scadenta la {km_scadenta} km)")

    # Revizie la data
    try:
        revizie_data = date.fromisoformat(m["urmatoarea_revizie_data"])
        zile = (revizie_data - azi).days
        if zile < 0:
            expirate.append(f"REVIZIE depasita ca termen, cu {abs(zile)} zile")
        elif zile <= orizont:
            curand.append(f"Revizie programata in {zile} zile (la {revizie_data.isoformat()})")
    except (KeyError, ValueError):
        pass

    return expirate, curand


@register_tool
def check_fleet_status(params: FleetStatusParams) -> str:
    """Verifica starea tehnica si scadentele de conformitate ale flotei.

    Foloseste acest tool pentru intrebari operationale: ce expira in curand
    (ITP, RCA, CASCO, rovinieta), ce revizii se apropie, daca o autorulota e
    in regula pentru a fi inchiriata.

    Nu il folosi pentru intrebari comerciale ale clientilor despre pret sau
    disponibilitate - pentru acelea exista check_availability si
    calculate_quote.
    """
    azi = datetime.now(ZoneInfo("Europe/Bucharest")).date()

    if params.vehicul_id:
        v = datastore.vehicul(params.vehicul_id)
        if v is None:
            return f"EROARE: nu exista nicio autorulota cu identificatorul {params.vehicul_id!r}."
        vehicule = [v]
    else:
        vehicule = datastore.toate_vehiculele()

    cu_probleme: list[str] = []
    cu_scadente: list[str] = []
    in_regula: list[str] = []
    fara_fisa: list[str] = []

    for v in vehicule:
        m = datastore.mentenanta_vehiculului(v["id"])
        if m is None:
            fara_fisa.append(f"  {v['id']} - {v['nume_comercial']}")
            continue

        expirate, curand = _analizeaza(v, m, azi, params.zile_orizont)
        antet = f"  {v['id']} - {v['nume_comercial']} ({m.get('km_actuali', '?')} km)"

        if expirate:
            cu_probleme.append(antet)
            cu_probleme.extend(f"      X {x}" for x in expirate)
            cu_probleme.extend(f"      ! {x}" for x in curand)
        elif curand:
            cu_scadente.append(antet)
            cu_scadente.extend(f"      ! {x}" for x in curand)
        else:
            in_regula.append(f"  {v['id']} - {v['nume_comercial']}")

    r: list[str] = []
    r.append(
        f"STARE FLOTA la {azi.isoformat()} "
        f"({len(vehicule)} autorulote, orizont {params.zile_orizont} zile)"
    )
    r.append("")

    if cu_probleme:
        r.append("NECESITA ACTIUNE IMEDIATA - documente expirate sau revizie depasita:")
        r.extend(cu_probleme)
        r.append("")

    if cu_scadente:
        r.append(f"SCADENTE IN URMATOARELE {params.zile_orizont} DE ZILE:")
        r.extend(cu_scadente)
        r.append("")

    if in_regula:
        r.append(f"IN REGULA ({len(in_regula)}):")
        r.extend(in_regula)
        r.append("")

    if fara_fisa:
        r.append("FARA FISA DE MENTENANTA (nu pot fi verificate):")
        r.extend(fara_fisa)

    if not cu_probleme and not cu_scadente:
        r.append("Nicio scadenta in orizontul verificat.")

    return "\n".join(r).rstrip()
