"""
QAAgent - agentul conversational (livrabilele 3 si 4 ale temei).

Doua straturi, construite unul peste altul:

  chat()       Lectia 1: conversatie cu istoric, fara unelte.
               [system] + istoric + mesaj -> llm.invoke() -> text

  react_loop() Lectia 2: acelasi lucru, dar cu unelte, in bucla
               GANDESTE -> ACTIONEAZA -> OBSERVA -> repeta

Trei piese din curs se intalnesc aici:
  Factory  (S4.4) - modele.creeaza_llm() construieste orice model activ din .env
  Registry (S3.6) - system prompt-ul vine din YAML, nu din cod
  ReAct    (S6.2) - bucla de rationament cu unelte
"""

import uuid
from datetime import datetime
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from langchain_core.language_models.chat_models import BaseChatModel
from langsmith import trace
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

import config
import modele
from modele import ModelAI
from prompts import get_prompt_registry
from tools import ToolWrapper


def text_din(raspuns: BaseMessage) -> str:
    """
    Extrage textul dintr-un raspuns al modelului.

    De ce e nevoie de o functie si nu de `.content` direct:
        In LangChain 0.x, `.content` era mereu un sir de caractere.
        In 1.x, modelele moderne returneaza o LISTA de blocuri:

            [{'type': 'text', 'text': 'Autorulota are 6 locuri...',
              'extras': {'signature': '...'}}]

        Blocurile pot fi text, imagini, sau urme de rationament. Noua ne
        trebuie doar textul. Functia trateaza ambele forme, ca acelasi cod
        sa mearga si pe Ollama (sir), si pe Gemini (lista).
    """
    continut = raspuns.content

    if isinstance(continut, str):
        return continut

    if isinstance(continut, list):
        bucati = []
        for bloc in continut:
            if isinstance(bloc, str):
                bucati.append(bloc)
            elif isinstance(bloc, dict) and bloc.get("type") == "text":
                bucati.append(bloc.get("text", ""))
        return "\n".join(b for b in bucati if b).strip()

    return str(continut)


class QAAgent:
    """Agent conversational cu istoric, unelte si bucla ReAct."""

    def __init__(
        self,
        model: str | None = None,
        max_iteratii: int | None = None,
        verbose: bool = False,
    ):
        """
        model: numele unui model ACTIV din .env ("gemini-3.8-flash",
               "gemini/gemini-3.8-flash" sau numarul din /modele).
               Omis -> primul model din MODELE_ACTIVE.
        """
        self.max_iteratii = max_iteratii or config.MAX_ITERATIONS
        self.verbose = verbose
        self.istoric: list[BaseMessage] = []

        # Identificatorul conversatiei. LangSmith grupeaza dupa el toate
        # mesajele unei discutii in vederea "Threads" - vezi conversatia
        # intreaga, nu raspunsuri izolate. Se reinnoieste la /reset.
        self.conversatie_id = str(uuid.uuid4())
        self.ultimul_run_id: str | None = None

        self.schimba_model(model)

    # -----------------------------------------------------------------
    # FACTORY PATTERN (S4.4) - delegat catre catalogul din modele.py
    # -----------------------------------------------------------------
    def schimba_model(self, cerere: str | None = None) -> ModelAI:
        """
        Alege un model din catalog si il pregateste pentru lucru.

        Se foloseste si la pornire, si la comutarea din mijlocul conversatiei
        (/model in CLI). Istoricul ramane: aceeasi discutie continua pe alt
        model - demonstratia practica a Factory Pattern-ului.
        """
        if cerere is None:
            ales = modele.implicit()
            if ales is None:
                raise ValueError("Niciun model activ in .env (MODELE_ACTIVE).")
        else:
            ales = modele.gaseste(cerere)
            if ales is None:
                disponibile = ", ".join(m.nume for m in modele.active())
                raise ValueError(f"Modelul '{cerere}' nu e definit in .env. Active: {disponibile}.")
            if not ales.activ:
                raise ValueError(
                    f"Modelul '{ales.id}' e INACTIV. Muta-l in MODELE_ACTIVE din .env "
                    f"si reporneste agentul ca sa-l poti folosi."
                )

        self._foloseste(ales)
        return ales

    def _foloseste(self, model: ModelAI) -> None:
        """Construieste modelul prin Factory si ii ataseaza uneltele."""
        self.model_ai = model
        self.llm: BaseChatModel = modele.creeaza_llm(model)
        # bind_tools ataseaza catalogul de unelte la model. De aici incolo,
        # modelul POATE cere unelte - dar nu le executa el (slide S5.2).
        self.llm_cu_unelte = self.llm.bind_tools(ToolWrapper.catalog())

    @property
    def provider(self) -> str:
        return self.model_ai.provider

    @property
    def model(self) -> str:
        return self.model_ai.nume

    # -----------------------------------------------------------------
    # PROMPT REGISTRY (S3.6)
    # -----------------------------------------------------------------
    def _system_prompt(self, cu_react: bool = True) -> SystemMessage:
        """
        Compune promptul de sistem din YAML-uri, la FIECARE apel.

        De ce la fiecare apel si nu o data la pornire: `data_curenta` trebuie
        sa fie corecta. Un agent pornit ieri ar calcula gresit discountul de
        early booking daca ar tine minte data de la pornire.
        """
        registry = get_prompt_registry()
        azi = datetime.now(ZoneInfo("Europe/Bucharest")).date().isoformat()

        text = registry.render(
            "qa_agent_system",
            data_curenta=azi,
            catalog_tools=ToolWrapper.rezumat(),
            nume_companie=config.NUME_COMPANIE,
            nume_agent=config.NUME_AGENT,
            canal_contact=config.CANAL_CONTACT,
        )

        if cu_react:
            text += "\n\n" + registry.render(
                "qa_agent_react", max_iteratii=self.max_iteratii
            )

        return SystemMessage(content=text)

    # -----------------------------------------------------------------
    # Afisare pedagogica
    # -----------------------------------------------------------------
    def _spune(self, eticheta: str, text: str) -> None:
        if self.verbose:
            print(f"  [{eticheta}] {text}", flush=True)

    # -----------------------------------------------------------------
    # LECTIA 1: conversatie simpla, cu istoric, FARA unelte
    # -----------------------------------------------------------------
    def chat(self, mesaj: str, foloseste_istoric: bool = True) -> str:
        """
        Trimite un mesaj si primeste raspunsul complet.

        foloseste_istoric=False demonstreaza ca LLM-urile sunt STATELESS
        (slide 63): fara istoric, al doilea mesaj nu stie nimic despre primul.
        """
        mesaj_user = HumanMessage(content=mesaj)
        istoric = self.istoric if foloseste_istoric else []
        mesaje = [self._system_prompt(cu_react=False), *istoric, mesaj_user]

        raspuns = self.llm.invoke(mesaje)
        text = text_din(raspuns)

        if foloseste_istoric:
            self.istoric.append(mesaj_user)
            self.istoric.append(AIMessage(content=text))

        return text

    def stream(self, mesaj: str) -> Iterator[str]:
        """Aceeasi conversatie, dar cu raspunsul afisat pe masura ce vine."""
        mesaj_user = HumanMessage(content=mesaj)
        mesaje = [self._system_prompt(cu_react=False), *self.istoric, mesaj_user]

        complet = ""
        for bucata in self.llm.stream(mesaje):
            text = text_din(bucata)
            if not text:
                continue
            complet += text
            yield text

        # Istoricul se actualizeaza DUPA ce streamul s-a terminat (slide 66).
        self.istoric.append(mesaj_user)
        self.istoric.append(AIMessage(content=complet))

    # -----------------------------------------------------------------
    # LECTIA 2: bucla ReAct cu unelte (S6.2 - S6.7)
    # -----------------------------------------------------------------
    def react_loop(self, mesaj: str) -> str:
        """
        O tura completa de conversatie, inregistrata ca UN SINGUR trace (S8).

        Fara acest bloc, LangSmith ar vedea fiecare apel catre LLM ca o rulare
        separata, fara legatura intre ele. Cu el, o intrebare a clientului =
        un trace, iar inauntru apar in ordine toate rundele: LLM -> unealta ->
        LLM -> unealta -> raspuns. Exact arborele din slide-ul S8.4.

        Metadata (S8.8) raspunde la intrebarile pe care ti le vei pune cand
        ceva merge prost: ce model a raspuns? ce versiune de prompt era activa?
        din ce conversatie face parte mesajul?
        """
        registry = get_prompt_registry()
        self._statistici = {"runde": 0, "apeluri_unelte": 0}
        # Tokenii de intrare si de iesire se numara SEPARAT: providerii ii
        # taxeaza diferit (la Gemini, iesirea e de ~5 ori mai scumpa).
        self._tokeni = {"tokeni_intrare": 0, "tokeni_iesire": 0}

        with trace(
            name="qa_agent_tura",
            run_type="chain",
            inputs={"mesaj": mesaj},
            tags=["qa-agent", self.provider],
            metadata={
                "thread_id": self.conversatie_id,
                "provider": self.provider,
                "model": self.model_ai.id,
                "prompt_system_versiune": registry.get("qa_agent_system").versiune,
                "prompt_react_versiune": registry.get("qa_agent_react").versiune,
                "max_iteratii": self.max_iteratii,
            },
        ) as run:
            raspuns = self._react_loop_intern(mesaj)
            self._statistici.update(self._tokeni)
            run.end(outputs={"raspuns": raspuns, **self._statistici})
            # Retinem adresa trace-ului, ca sa-l putem regasi exact in LangSmith
            # (verifica_langsmith.py si comanda /trace din CLI).
            self.ultimul_run_id = str(run.id)
            return raspuns

    def _react_loop_intern(self, mesaj: str) -> str:
        """
        GANDESTE -> ACTIONEAZA -> OBSERVA, pana la raspunsul final.

        Regula de aur (S5.2): modelul CERE unelte, aplicatia le EXECUTA.
        Tot ce se executa trece prin ToolWrapper.call(), unde e validat.
        """
        mesaj_user = HumanMessage(content=mesaj)
        mesaje: list[BaseMessage] = [
            self._system_prompt(cu_react=True),
            *self.istoric,
            mesaj_user,
        ]

        apeluri_totale = 0

        # Protectie anti-bucla (S6.7).
        # Modelele mici cer uneori aceeasi unealta, cu aceiasi parametri, la
        # nesfarsit: primesc raspunsul si nu recunosc ca il au deja. Retinem
        # semnatura fiecarui apel; la repetare nu mai executam unealta, ci ii
        # spunem modelului ca rezultatul e deja in conversatie.
        semnaturi_vazute: set[str] = set()
        repetari = 0

        for iteratie in range(1, self.max_iteratii + 1):
            self._spune("GANDESTE", f"runda {iteratie}/{self.max_iteratii}")

            raspuns: AIMessage = self.llm_cu_unelte.invoke(mesaje)
            self._numara_tokeni(raspuns)
            mesaje.append(raspuns)

            apeluri = getattr(raspuns, "tool_calls", None) or []
            self._statistici = {
                "runde": iteratie,
                "apeluri_unelte": apeluri_totale + len(apeluri),
            }

            # --- Fara cereri de unelte => avem raspunsul final -------------
            if not apeluri:
                self._spune("RASPUNDE", f"dupa {iteratie} runde, {apeluri_totale} apeluri de unelte")
                text = text_din(raspuns)
                self.istoric.append(mesaj_user)
                self.istoric.append(AIMessage(content=text))
                return text

            # --- Executam TOATE uneltele cerute in aceasta runda (S6.5) ----
            self._spune("ACTIONEAZA", f"{len(apeluri)} unelte cerute in aceasta runda")

            for apel in apeluri:
                nume = apel.get("name", "")
                argumente = apel.get("args", {}) or {}
                apeluri_totale += 1

                # Semnatura apelului: nume + parametri, cu cheile sortate, ca
                # {'a':1,'b':2} si {'b':2,'a':1} sa fie recunoscute ca identice.
                # Parametrii lasati None nu conteaza - modelul ii pune inconstant.
                relevanti = {k: v for k, v in sorted(argumente.items()) if v is not None}
                semnatura = f"{nume}:{relevanti}"

                if semnatura in semnaturi_vazute:
                    repetari += 1
                    self._spune("  !!", f"{nume} cerut din nou cu aceiasi parametri")
                    rezultat = (
                        f"Ai apelat deja '{nume}' cu exact acesti parametri in aceasta "
                        f"conversatie, iar rezultatul este mai sus. Nu il cere din nou: "
                        f"foloseste informatia pe care o ai si formuleaza raspunsul final "
                        f"pentru client."
                    )
                else:
                    semnaturi_vazute.add(semnatura)
                    self._spune("  ->", f"{nume}({relevanti})")
                    rezultat = ToolWrapper.call(nume, argumente)

                self._spune(
                    "OBSERVA",
                    f"{nume} -> {rezultat[:120]}{'...' if len(rezultat) > 120 else ''}",
                )

                # ToolMessage trebuie legat de cerere prin tool_call_id (S5.5).
                # Fara el, modelul nu stie care rezultat raspunde carei cereri
                # atunci cand a cerut mai multe unelte odata.
                mesaje.append(
                    ToolMessage(content=rezultat, tool_call_id=apel.get("id", nume))
                )

            # --- Iesire fortata din bucla ---------------------------------
            # Daca modelul a repetat de doua ori, nu se mai desprinde singur.
            # Il apelam o ultima data FARA unelte: neavand ce sa ceara, e
            # obligat sa formuleze raspunsul din ce a strans deja.
            if repetari >= 2:
                self._spune("FORTEAZA", "modelul se repeta - cer raspunsul final fara unelte")
                final = self.llm.invoke(
                    mesaje
                    + [
                        SystemMessage(
                            content=(
                                "Ai toate informatiile necesare mai sus. Formuleaza ACUM "
                                "raspunsul final pentru client, in limbaj natural. Nu mai "
                                "cere nicio unealta."
                            )
                        )
                    ]
                )
                self._numara_tokeni(final)
                text = text_din(final)
                self.istoric.append(mesaj_user)
                self.istoric.append(AIMessage(content=text))
                return text

        # --- Plasa de siguranta: s-au terminat rundele (S6.7) --------------
        self._spune("STOP", f"limita de {self.max_iteratii} runde atinsa")
        text = (
            f"Nu am reusit sa ajung la un raspuns complet in {self.max_iteratii} runde de "
            f"verificari ({apeluri_totale} consultari). Te rog reformuleaza intrebarea sau "
            f"imparte-o in intrebari mai mici."
        )
        self.istoric.append(mesaj_user)
        self.istoric.append(AIMessage(content=text))
        return text

    def _numara_tokeni(self, raspuns: BaseMessage) -> None:
        """Aduna tokenii raportati de provider pentru un apel la model."""
        uz = getattr(raspuns, "usage_metadata", None) or {}
        self._tokeni["tokeni_intrare"] += uz.get("input_tokens", 0) or 0
        self._tokeni["tokeni_iesire"] += uz.get("output_tokens", 0) or 0

    # -----------------------------------------------------------------
    # Istoric
    # -----------------------------------------------------------------
    def get_history(self) -> list[dict[str, Any]]:
        """Istoricul, in forma serializabila (pentru afisare sau salvare)."""
        roluri = {"human": "user", "ai": "assistant", "system": "system"}
        return [
            {"rol": roluri.get(m.type, m.type), "continut": m.content}
            for m in self.istoric
        ]

    def clear_history(self) -> None:
        """Reset complet al conversatiei."""
        self.istoric = []
        # Conversatie noua -> thread nou in LangSmith.
        self.conversatie_id = str(uuid.uuid4())

