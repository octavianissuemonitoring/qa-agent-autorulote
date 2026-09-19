"""
Prompt Registry - prompturile ca fisiere de configuratie (Lectia 2, S3.1-S3.8).

PROBLEMA (S3.1):
    Un prompt scris direct in cod e ingropat acolo. Nu poti sa-l modifici fara
    sa atingi codul, nu poti sa testezi doua variante, nu ai istoric, si nimeni
    din afara echipei tehnice nu poate contribui.

SOLUTIA (S3.2):
    Prompturile sunt CONFIGURATIE, nu cod. Configuratia traieste in fisiere.
    Un folder per agent, un fisier .yaml per prompt, Git pentru istorie.

CE CONTINE FISIERUL ASTA:
    PromptVariable   - o variabila declarata, cu validare
    PromptTemplate   - un prompt incarcat din YAML, imutabil (S3.5)
    PromptRegistry   - catalogul: incarca, valideaza, renderizeaza (S3.6)
    get_prompt_registry() - acces global, o singura incarcare (S3.7)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError

DIRECTOR_PROMPTURI = Path(__file__).resolve().parent

# StrictUndefined: daca templateul foloseste {{ o_variabila }} pe care nu i-am
# dat-o, Jinja2 arunca eroare in loc sa scrie un sir gol. Un prompt caruia ii
# lipseste o bucata e mai periculos decat unul care crapa - crapa o vezi.
_JINJA = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)


@dataclass(frozen=True)
class PromptVariable:
    """O variabila pe care templateul o asteapta."""

    nume: str
    descriere: str = ""
    obligatorie: bool = True
    implicit: Any = None


@dataclass(frozen=True)
class PromptTemplate:
    """
    Un prompt incarcat dintr-un fisier YAML.

    frozen=True (S3.5) inseamna ca obiectul e IMUTABIL: odata incarcat, nimeni
    nu-i mai poate schimba textul din greseala, la runtime. Daca vrei alt
    prompt, editezi YAML-ul si dai reload() - nu mutezi obiectul din memorie.
    """

    nume: str
    versiune: str
    prompt: str
    descriere: str = ""
    variabile: tuple[PromptVariable, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    cale: str = ""

    @property
    def obligatorii(self) -> list[str]:
        return [v.nume for v in self.variabile if v.obligatorie]


class PromptRegistry:
    """Catalogul de prompturi: incarca din disc, valideaza, renderizeaza."""

    def __init__(self, director: Path | str = DIRECTOR_PROMPTURI):
        self.director = Path(director)
        self._template_uri: dict[str, PromptTemplate] = {}
        self.reload()

    # -----------------------------------------------------------------
    # Incarcare
    # -----------------------------------------------------------------
    def reload(self) -> int:
        """
        Reciteste toate fisierele .yaml de pe disc (S3.8 - hot reload).

        In dezvoltare: editezi YAML-ul, chemi reload(), testezi. Iterare in
        secunde, fara sa repornesti agentul.
        """
        self._template_uri.clear()

        for cale in sorted(self.director.rglob("*.yaml")):
            date = yaml.safe_load(cale.read_text(encoding="utf-8")) or {}

            # --- campurile obligatorii (S3.3) ---
            lipsa = [c for c in ("name", "version", "prompt") if not date.get(c)]
            if lipsa:
                raise ValueError(
                    f"[{cale.name}] lipsesc campurile obligatorii: {lipsa}. "
                    f"Minimul unui prompt e name + version + prompt."
                )

            nume = date["name"]
            if nume in self._template_uri:
                raise ValueError(
                    f"[{cale.name}] promptul {nume!r} e deja definit in "
                    f"{self._template_uri[nume].cale}. Numele trebuie sa fie unic."
                )

            variabile = tuple(
                PromptVariable(
                    nume=v["name"],
                    descriere=v.get("description", ""),
                    obligatorie=v.get("required", True),
                    implicit=v.get("default"),
                )
                for v in (date.get("variables") or [])
            )

            # Verificam ca templateul e Jinja2 valid inca de la incarcare,
            # nu abia cand incercam sa-l folosim in fata utilizatorului.
            try:
                _JINJA.parse(date["prompt"])
            except TemplateSyntaxError as e:
                raise ValueError(
                    f"[{cale.name}] eroare de sintaxa Jinja2 la linia {e.lineno}: {e.message}"
                ) from e

            self._template_uri[nume] = PromptTemplate(
                nume=nume,
                versiune=str(date["version"]),
                prompt=date["prompt"],
                descriere=date.get("description", ""),
                variabile=variabile,
                metadata=date.get("metadata") or {},
                cale=str(cale.relative_to(self.director)),
            )

        return len(self._template_uri)

    # -----------------------------------------------------------------
    # Acces
    # -----------------------------------------------------------------
    def get(self, nume: str) -> PromptTemplate:
        template = self._template_uri.get(nume)
        if template is None:
            disponibile = ", ".join(sorted(self._template_uri)) or "(niciunul)"
            raise KeyError(f"Promptul {nume!r} nu exista. Disponibile: {disponibile}.")
        return template

    def list_templates(self) -> list[dict[str, str]]:
        """Catalogul, pentru inspectie si pentru comanda /prompts din CLI."""
        return [
            {
                "nume": t.nume,
                "versiune": t.versiune,
                "descriere": t.descriere,
                "variabile": ", ".join(v.nume for v in t.variabile) or "-",
                "fisier": t.cale,
            }
            for t in sorted(self._template_uri.values(), key=lambda x: x.nume)
        ]

    # -----------------------------------------------------------------
    # Randare
    # -----------------------------------------------------------------
    def render(self, nume: str, **valori: Any) -> str:
        """
        Valideaza variabilele, apoi aplica Jinja2.

        Doua verificari inainte de randare:
          - lipseste o variabila obligatorie -> eroare clara
          - s-a dat o variabila nedeclarata  -> eroare (prinde greselile de tipar)
        """
        template = self.get(nume)

        declarate = {v.nume: v for v in template.variabile}
        context: dict[str, Any] = {
            v.nume: v.implicit for v in template.variabile if v.implicit is not None
        }
        context.update(valori)

        necunoscute = set(valori) - set(declarate)
        if necunoscute:
            raise ValueError(
                f"Promptul {nume!r} nu declara variabilele: {sorted(necunoscute)}. "
                f"Declarate: {sorted(declarate)}. Verifica daca ai gresit numele."
            )

        lipsa = [n for n in template.obligatorii if n not in context]
        if lipsa:
            raise ValueError(
                f"Promptului {nume!r} ii lipsesc variabilele obligatorii: {lipsa}."
            )

        return _JINJA.from_string(template.prompt).render(**context).strip()


# ---------------------------------------------------------------------
# Acces global (S3.7 + Singleton, S4.6)
# ---------------------------------------------------------------------
# In Python, un modul se incarca o singura data per proces. O variabila la
# nivel de modul E deja un singleton - nu ne trebuie clase speciale.
_registry: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    """
    Returneaza registry-ul, incarcandu-l la prima cerere (lazy).

    Beneficii (S3.7): o singura citire a YAML-urilor, acces global consistent,
    usor de inlocuit cu un dublu in teste.
    """
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry
