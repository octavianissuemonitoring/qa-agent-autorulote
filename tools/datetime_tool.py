"""
Tool: get_current_datetime - data si ora curenta.

De ce exista (Lectia 2, slide S5.1):
    Un LLM nu stie ce zi e. Cunostintele lui se opresc la data de antrenare,
    iar ceasul nu face parte din model. Daca il intrebi "ce data e azi",
    inventeaza.

De ce ne trebuie noua, concret:
    - discountul de early booking se calculeaza fata de ziua curenta
    - "vreau autorulota luna viitoare" nu inseamna nimic fara un punct de reper
    - scadentele ITP/RCA se raporteaza la azi
"""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from tools.registry import register_tool

ZILE = [
    "luni", "marti", "miercuri", "joi", "vineri", "sambata", "duminica",
]
LUNI = [
    "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
    "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
]


class DateTimeParams(BaseModel):
    """Parametrii pentru tool-ul get_current_datetime."""

    fus_orar: str = Field(
        default="Europe/Bucharest",
        description=(
            "Fusul orar in format IANA, ex: 'Europe/Bucharest', 'Europe/Berlin'. "
            "Lasa valoarea implicita daca nu ti se cere altceva."
        ),
    )


@register_tool
def get_current_datetime(params: DateTimeParams) -> str:
    """Returneaza data si ora curenta.

    Foloseste acest tool ORI DE CATE ORI ai nevoie de ziua de azi: cand
    clientul spune "saptamana viitoare", "peste o luna", "in august", cand
    calculezi cate zile mai sunt pana la o rezervare, sau cand verifici daca
    o inchiriere se incadreaza la discountul de early booking.

    Nu presupune niciodata data curenta - nu o cunosti.
    """
    try:
        acum = datetime.now(ZoneInfo(params.fus_orar))
    except (ZoneInfoNotFoundError, ValueError):
        return (
            f"EROARE: fusul orar {params.fus_orar!r} nu exista. "
            f"Foloseste un identificator IANA, ex. 'Europe/Bucharest'."
        )

    return (
        f"Data curenta: {acum.date().isoformat()} "
        f"({ZILE[acum.weekday()]}, {acum.day} {LUNI[acum.month - 1]} {acum.year})\n"
        f"Ora: {acum.strftime('%H:%M')} ({params.fus_orar})"
    )
