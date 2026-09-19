"""
ToolWrapper - punctul UNIC de contact cu tool-urile (Lectia 2, slide S7.6).

Doua metode, doua directii:

    catalog()  ->  spre LLM:  "astea sunt tool-urile pe care le ai"
    call()     ->  de la LLM: "executa tool-ul X cu parametrii Y"

Tot ce intra si iese din tool-uri trece prin aici. De asta putem
valida, loga si controla totul intr-un singur loc (slide S5.2:
"LLM cere, APP-ul executa").
"""

from typing import Any

from langsmith import trace
from pydantic import ValidationError

from tools.registry import TOOL_REGISTRY


def _simplifica_optional(camp: dict[str, Any]) -> None:
    """
    Aplatizeaza `anyOf: [{tip}, {"type": "null"}]` in `{tip}`.

    De ce e nevoie:
        Pentru un camp optional (ex. `tip: str | None`), Pydantic genereaza
        o schema cu `anyOf`. Anthropic si OpenAI o accepta; API-ul Gemini o
        respinge sau o interpreteaza gresit.

        Cum campul e oricum optional (nu apare in `required`), varianta "null"
        nu aduce informatie. O stergem si pastram tipul propriu-zis - schema
        devine mai simpla SI merge pe toti providerii.

    Exact genul de diferenta intre provideri despre care vorbeste slide-ul
    S5.4. Uniformizarea o facem noi, o data, aici.
    """
    variante = camp.get("anyOf")
    if not variante:
        return

    ne_nule = [v for v in variante if v.get("type") != "null"]
    if len(ne_nule) != 1:
        return  # uniune reala de tipuri - o lasam asa cum e

    camp.pop("anyOf")
    descriere = camp.get("description")
    camp.update(ne_nule[0])
    camp.pop("title", None)
    if descriere:
        camp["description"] = descriere


class ToolWrapper:
    """Executor si catalog pentru tool-urile inregistrate."""

    # -----------------------------------------------------------------
    # call(): punctul de intrare, cu observabilitate
    # -----------------------------------------------------------------
    @staticmethod
    def call(nume: str, parametri: dict[str, Any]) -> str:
        """
        Executa un tool si inregistreaza executia in LangSmith (S8).

        De ce e nevoie de cod aici, desi LangSmith e "zero cod" (S8.3):
            LangChain isi traseaza SINGUR doar ce face el - apelurile catre LLM.
            Uneltele noastre nu sunt executate de LangChain, ci de noi, aici.
            Fara blocul `trace`, in LangSmith ai vedea ca modelul a CERUT
            calculate_quote, dar nu si ce a primit inapoi. Exact bucata de care
            ai nevoie cand depanezi un deviz gresit.

        Cand tracing-ul e oprit (LANGCHAIN_TRACING_V2=false), `trace` nu trimite
        nimic nicaieri - costul e neglijabil.
        """
        with trace(
            name=nume or "tool_necunoscut",
            run_type="tool",
            inputs={"parametri": parametri},
            tags=["tool"],
        ) as run:
            rezultat = ToolWrapper._executa(nume, parametri)

            # Erorile de unealta devin ROSII in interfata LangSmith, ca sa le
            # gasesti dintr-o privire intr-o lista de sute de rulari (S8.9).
            eroare = rezultat if rezultat.startswith("EROARE") else None
            run.end(outputs={"rezultat": rezultat}, error=eroare)
            return rezultat

    # -----------------------------------------------------------------
    # _executa(): Lookup -> Validate -> Execute -> Validate output -> Return
    # -----------------------------------------------------------------
    @staticmethod
    def _executa(nume: str, parametri: dict[str, Any]) -> str:
        """
        Executa un tool inregistrat si returneaza rezultatul ca text.

        PRINCIPIU CHEIE (slide S6.6): metoda asta nu arunca NICIODATA
        exceptii catre apelant. Orice problema se intoarce ca mesaj
        descriptiv, in text.

        De ce? Pentru ca rezultatul ajunge inapoi la LLM. Un stack trace
        Python nu-i spune nimic unui model; "Vehiculul GC-099 nu exista
        in flota" ii spune sa reformuleze. Erorile sunt informatie pentru
        agent, nu accidente.
        """
        # --- 1. LOOKUP: exista tool-ul cerut? -------------------------
        # LLM-urile halucineaza uneori nume de tool-uri care nu exista.
        tool = TOOL_REGISTRY.get(nume)
        if tool is None:
            disponibile = ", ".join(sorted(TOOL_REGISTRY)) or "(niciunul)"
            return (
                f"EROARE: nu exista niciun tool numit '{nume}'. "
                f"Tool-uri disponibile: {disponibile}."
            )

        # --- 2. VALIDATE: Pydantic verifica parametrii ----------------
        # Aici se opresc parametrii inventati, tipurile gresite si
        # campurile obligatorii lipsa - INAINTE sa ruleze ceva.
        try:
            params_validati = tool["model_params"](**parametri)
        except ValidationError as e:
            probleme = []
            for err in e.errors():
                camp = ".".join(str(p) for p in err["loc"]) or "(radacina)"
                probleme.append(f"{camp}: {err['msg']}")
            return (
                f"EROARE de validare la tool-ul '{nume}': "
                + "; ".join(probleme)
                + ". Corecteaza parametrii si incearca din nou."
            )
        except TypeError as e:
            return f"EROARE: parametri in format gresit pentru '{nume}': {e}"

        # --- 3. EXECUTE: rulam functia ------------------------------
        try:
            rezultat = tool["functie"](params_validati)
        except Exception as e:
            # Plasa de siguranta: un tool care crapa nu are voie sa
            # omoare agentul. Ii spunem LLM-ului ce s-a intamplat.
            return f"EROARE la executia tool-ului '{nume}': {type(e).__name__}: {e}"

        # --- 4. VALIDATE OUTPUT: rezultatul are sens? ---------------
        # S6.6, "Rezultat invalid": un tool care intoarce None sau text gol
        # nu a crapat, dar nici nu i-a dat LLM-ului nimic. Fara verificarea
        # asta, modelul ar primi textul 'None' sau '' si ar putea inventa
        # raspunsul. Ii spunem clar ca informatia lipseste.
        if rezultat is None or not str(rezultat).strip():
            return (
                f"EROARE: tool-ul '{nume}' a returnat un rezultat gol. "
                f"Nu ai primit nicio informatie - nu presupune un raspuns. "
                f"Incearca alti parametri sau spune-i clientului ca informatia "
                f"nu este disponibila momentan."
            )

        # --- 5. RETURN: mereu text ----------------------------------
        # LLM-ul primeste text, nu obiecte Python.
        return rezultat if isinstance(rezultat, str) else str(rezultat)

    # -----------------------------------------------------------------
    # catalog(): JSON Schema generat AUTOMAT din modelele Pydantic
    # -----------------------------------------------------------------
    @staticmethod
    def catalog() -> list[dict[str, Any]]:
        """
        Returneaza definitiile tool-urilor in formatul standard pe care
        il inteleg LangChain si toti providerii.

        Zero cod scris de mana: .model_json_schema() genereaza schema din
        clasa Pydantic. Adaugi un camp in model -> apare automat in
        catalog -> LLM-ul il stie. Asta e beneficiul din slide-ul S7.5.
        """
        definitii = []

        for nume, tool in TOOL_REGISTRY.items():
            schema = tool["model_params"].model_json_schema()

            # Curatam zgomotul pe care Pydantic il pune pentru oameni,
            # dar care nu ajuta modelul si consuma tokeni degeaba.
            schema.pop("title", None)
            for camp in schema.get("properties", {}).values():
                camp.pop("title", None)
                _simplifica_optional(camp)

            definitii.append(
                {
                    "type": "function",
                    "function": {
                        "name": nume,
                        "description": tool["descriere"],
                        "parameters": schema,
                    },
                }
            )

        return definitii

    # -----------------------------------------------------------------
    # Mici utilitare
    # -----------------------------------------------------------------
    @staticmethod
    def nume_tooluri() -> list[str]:
        """Lista numelor inregistrate - utila pentru comanda /tools din CLI."""
        return sorted(TOOL_REGISTRY)

    @staticmethod
    def rezumat() -> str:
        """
        Rezumat citibil al tool-urilor: nume + prima linie din docstring.
        Il vom injecta in system prompt prin Jinja2 la Pas 4.
        """
        linii = []
        for nume in sorted(TOOL_REGISTRY):
            prima_linie = TOOL_REGISTRY[nume]["descriere"].split("\n")[0]
            linii.append(f"- {nume}: {prima_linie}")
        return "\n".join(linii)
