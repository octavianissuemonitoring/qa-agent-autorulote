"""
Tool: calculator - aritmetica exacta.

De ce exista (Lectia 2, slide S6.1):
    LLM-urile PREZIC token-uri, nu calculeaza. La 1847 * 394 un model
    raspunde 727.618 in loc de 727.718 - plauzibil, dar gresit.
    Regula din curs: daca raspunsul gresit are consecinte (financiare,
    tehnice, legale) -> folosesti tool.

Pentru noi consecinta e financiara: preturi de inchiriere. Deci calculul
nu ajunge niciodata in seama LLM-ului.
"""

import ast
import operator

from pydantic import BaseModel, Field

from tools.registry import register_tool


# =====================================================================
# PASUL 1 din S7.3: parametrii, ca model Pydantic
# =====================================================================
class CalculatorParams(BaseModel):
    """Parametrii pentru tool-ul calculator."""

    # Field(description=...) NU e un comentariu pentru programator.
    # Textul asta ajunge in JSON Schema si e citit de LLM ca sa stie
    # CE sa puna in parametru. Il scrii pentru model, nu pentru coleg.
    expression: str = Field(
        description=(
            "Expresie aritmetica de evaluat, scrisa in notatie Python. "
            "Operatori permisi: + - * / // % ** si paranteze. "
            "Exemple valide: '4500 + 150 + 280', '4930 * 0.19', "
            "'(135 * 7) * 1.19'. "
            "NU accepta text, nume de variabile sau functii."
        )
    )


# =====================================================================
# Evaluare SIGURA
# =====================================================================
# Nu folosim eval() pe textul primit de la LLM. eval() executa orice cod
# Python - inclusiv stergere de fisiere. Iar textul vine de la un model
# care poate fi pacalit de utilizator (prompt injection).
#
# In loc de asta: parsam expresia intr-un arbore sintactic si acceptam
# doar nodurile din lista alba de mai jos. Orice altceva -> refuzat.
_OPERATORI_PERMISI = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _evalueaza(nod: ast.AST) -> float:
    """Parcurge recursiv arborele si calculeaza doar nodurile permise."""
    if isinstance(nod, ast.Expression):
        return _evalueaza(nod.body)

    if isinstance(nod, ast.Constant):
        if isinstance(nod.value, (int, float)):
            return nod.value
        raise ValueError(f"Valoare nepermisa: {nod.value!r}")

    if isinstance(nod, ast.BinOp):
        tip = type(nod.op)
        if tip not in _OPERATORI_PERMISI:
            raise ValueError(f"Operator nepermis: {tip.__name__}")
        return _OPERATORI_PERMISI[tip](_evalueaza(nod.left), _evalueaza(nod.right))

    if isinstance(nod, ast.UnaryOp):
        tip = type(nod.op)
        if tip not in _OPERATORI_PERMISI:
            raise ValueError(f"Operator nepermis: {tip.__name__}")
        return _OPERATORI_PERMISI[tip](_evalueaza(nod.operand))

    raise ValueError(f"Element nepermis in expresie: {type(nod).__name__}")


# =====================================================================
# PASUL 2 din S7.4: functia, inregistrata cu decoratorul
# =====================================================================
@register_tool
def calculator(params: CalculatorParams) -> str:
    """Efectueaza calcule aritmetice exacte.

    Foloseste acest tool ORI DE CATE ORI trebuie sa calculezi ceva:
    sume, inmultiri, procente, TVA, medii, diferente. Nu calcula niciodata
    singur - modelele lingvistice gresesc la aritmetica.

    Primeste o expresie in notatie Python si returneaza rezultatul exact.
    Exemple de folosire: numarul de zile x tariful pe zi, aplicarea TVA de
    19%, scaderea unui discount procentual.
    """
    try:
        arbore = ast.parse(params.expression, mode="eval")
        rezultat = _evalueaza(arbore)
    except ValueError as e:
        return f"Expresie respinsa: {e}"
    except SyntaxError:
        return (
            f"Expresie invalida sintactic: '{params.expression}'. "
            f"Scrie doar numere, operatori (+ - * / ** %) si paranteze."
        )
    except ZeroDivisionError:
        return "Eroare: impartire la zero."

    # Rotunjim la 4 zecimale ca sa evitam cozile de tip 0.30000000000000004
    # (cum reprezinta calculatoarele numerele zecimale).
    if isinstance(rezultat, float):
        rezultat = round(rezultat, 4)
        if rezultat.is_integer():
            rezultat = int(rezultat)

    return str(rezultat)
