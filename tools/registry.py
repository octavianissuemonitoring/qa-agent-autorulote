"""
Tool Registry - catalogul central de tool-uri (Lectia 2, slide S7.4).

IMPORTANT, regula de arhitectura din slide-ul S7.9:
    "registry.py nu stie de tools, tools stiu de registry"

Adica: fisierul asta NU importa niciun tool. Daca ar face-o, ar trebui
modificat de fiecare data cand adaugi un tool nou. Asa, ramane neatins
pentru totdeauna - tool-urile vin la el, nu invers.
"""

import inspect
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel

# ---------------------------------------------------------------------
# Catalogul propriu-zis: un simplu dictionar la nivel de modul.
#
# De ce merge ca "singleton" (slide S4.6): in Python, un modul se
# incarca O SINGURA DATA per proces. Oricine scrie
# "from tools.registry import TOOL_REGISTRY" primeste acelasi dictionar,
# nu o copie. Deci avem o singura sursa de adevar, fara clase complicate.
#
# Structura unei intrari:
#   "calculator": {
#       "functie":      <functia Python de apelat>,
#       "model_params": <clasa Pydantic care valideaza parametrii>,
#       "descriere":    <docstring-ul functiei, citit de LLM>,
#   }
# ---------------------------------------------------------------------
TOOL_REGISTRY: dict[str, dict[str, Any]] = {}


def register_tool(functie: Callable) -> Callable:
    """
    Decorator care inregistreaza automat o functie ca tool.

    Ce face, pe scurt:
      1. Verifica daca functia respecta contractul (3 validari mai jos)
      2. O adauga in TOOL_REGISTRY sub numele ei
      3. O returneaza NEMODIFICATA

    Punctul 3 e important: decoratorul nu schimba functia. O poti apela
    normal din Python, ca pe orice alta functie. El doar "o trece in
    catalog" in trecere.

    Folosire:
        @register_tool
        def calculator(params: CalculatorParams) -> str:
            '''Descrierea citita de LLM.'''
            ...
    """
    nume = functie.__name__

    # --- Validarea 1: nume unic ---------------------------------------
    # Doua tool-uri cu acelasi nume = LLM-ul nu stie pe care sa-l ceara.
    # Mai bine crapa acum, la pornire, decat sa dea rezultate gresite in
    # productie.
    if nume in TOOL_REGISTRY:
        raise ValueError(
            f"Tool-ul '{nume}' este deja inregistrat. "
            f"Fiecare tool trebuie sa aiba un nume unic."
        )

    # --- Validarea 2: docstring obligatoriu ---------------------------
    # Docstring-ul NU e documentatie pentru programator - e textul pe
    # baza caruia LLM-ul decide DACA sa apeleze tool-ul (slide S5.6).
    # Un tool fara descriere e un tool care nu va fi apelat niciodata.
    descriere = inspect.getdoc(functie)
    if not descriere:
        raise ValueError(
            f"Tool-ul '{nume}' nu are docstring. "
            f"Descrierea e obligatorie - LLM-ul o citeste ca sa decida "
            f"cand sa foloseasca tool-ul."
        )

    # --- Validarea 3: exact un parametru, de tip BaseModel ------------
    # Conventia noastra: fiecare tool primeste UN SINGUR argument, un
    # obiect Pydantic. Asa obtinem gratuit validarea si JSON Schema.
    semnatura = inspect.signature(functie)
    parametri = list(semnatura.parameters.values())

    if len(parametri) != 1:
        raise ValueError(
            f"Tool-ul '{nume}' are {len(parametri)} parametri. "
            f"Trebuie sa aiba exact unul, un model Pydantic."
        )

    # get_type_hints rezolva adnotarile chiar daca sunt scrise ca text
    # (ex: "def f(params: 'CalculatorParams')").
    adnotari = get_type_hints(functie)
    model_params = adnotari.get(parametri[0].name)

    if not (isinstance(model_params, type) and issubclass(model_params, BaseModel)):
        raise ValueError(
            f"Parametrul tool-ului '{nume}' trebuie sa fie o clasa Pydantic "
            f"(BaseModel). Primit: {model_params!r}"
        )

    # --- Inregistrarea ------------------------------------------------
    TOOL_REGISTRY[nume] = {
        "functie": functie,
        "model_params": model_params,
        "descriere": descriere,
    }

    return functie
