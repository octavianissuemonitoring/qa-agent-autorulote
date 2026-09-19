"""
Catalogul de modele AI - REGISTRY + FACTORY (Lectia 2, S4.2 si S4.4).

Ce modele exista si care sunt pornite se decide din .env, nu din cod:

    MODELE_ACTIVE=gemini/gemini-3.6-flash, gemini/gemini-3.8-flash
    MODELE_INACTIVE=gemini/gemini-3.1-flash-lite, ollama/qwen2.5:3b

Reguli:
  - fiecare model se scrie ca  provider/nume_model
  - PRIMUL model activ e cel implicit, cu care porneste agentul
  - ca sa opresti un model, il muti din MODELE_ACTIVE in MODELE_INACTIVE
  - modelele inactive raman vizibile (comanda /modele), dar nu pot fi folosite

De ce provider/ explicit si nu ghicit din nume: un model Ollama se poate numi
oricum ("gemma", "gemini-local"...). Prefixul spune fara echivoc cine il ruleaza.
"""

from dataclasses import dataclass
from typing import Callable

from langchain_core.language_models.chat_models import BaseChatModel

import config

PROVIDERI = ("gemini", "ollama")

# ---------------------------------------------------------------------
# Preturi cunoscute, USD per 1 milion de tokeni: (intrare, iesire).
# Sursa: https://ai.google.dev/gemini-api/docs/pricing, citit la 2026-09-19.
# ATENTIE: la 3.6 / 3.7 / 3.8 Flash pretul se DUBLEAZA de la 1 ianuarie 2027.
# Un model care lipseste de aici functioneaza normal, doar ca nu i se poate
# calcula costul. Modelele Ollama ruleaza local si nu costa nimic per token.
# ---------------------------------------------------------------------
PRETURI: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}


@dataclass(frozen=True)
class ModelAI:
    """Un model din catalog. frozen=True: odata citit din .env, nu se mai schimba."""

    provider: str
    nume: str
    activ: bool

    @property
    def id(self) -> str:
        return f"{self.provider}/{self.nume}"

    @property
    def pret(self) -> tuple[float, float] | None:
        if self.provider == "ollama":
            return (0.0, 0.0)
        return PRETURI.get(self.nume)

    @property
    def temperatura_ignorata(self) -> bool:
        """Modelele Gemini 3.x isi fixeaza singure parametrii de generare."""
        return self.provider == "gemini" and self.nume.startswith("gemini-3")

    def cost_usd(self, tokeni_intrare: int, tokeni_iesire: int) -> float | None:
        if self.pret is None:
            return None
        p_in, p_out = self.pret
        return tokeni_intrare / 1_000_000 * p_in + tokeni_iesire / 1_000_000 * p_out


# ---------------------------------------------------------------------
# Citirea catalogului din .env
# ---------------------------------------------------------------------
def _parseaza(text: str, activ: bool) -> tuple[list[ModelAI], list[str]]:
    """Transforma 'gemini/a, ollama/b' in obiecte ModelAI. Intoarce si erorile."""
    modele, erori = [], []
    for bucata in text.split(","):
        bucata = bucata.strip()
        if not bucata:
            continue
        if "/" not in bucata:
            erori.append(
                f"'{bucata}' nu are provider. Scrie-l ca provider/model, "
                f"ex: gemini/{bucata} sau ollama/{bucata}"
            )
            continue
        provider, nume = bucata.split("/", 1)
        provider = provider.strip().lower()
        if provider not in PROVIDERI:
            erori.append(f"'{bucata}': provider necunoscut '{provider}'. Acceptati: {', '.join(PROVIDERI)}")
            continue
        modele.append(ModelAI(provider=provider, nume=nume.strip(), activ=activ))
    return modele, erori


def _citeste() -> tuple[list[ModelAI], list[str]]:
    active, erori_a = _parseaza(config.MODELE_ACTIVE, activ=True)
    inactive, erori_i = _parseaza(config.MODELE_INACTIVE, activ=False)

    # Acelasi model in ambele liste: castiga "activ", dar semnalam.
    id_active = {m.id for m in active}
    dubluri = [m.id for m in inactive if m.id in id_active]
    inactive = [m for m in inactive if m.id not in id_active]
    erori = erori_a + erori_i + [
        f"'{d}' apare si in MODELE_ACTIVE, si in MODELE_INACTIVE - il consider activ" for d in dubluri
    ]
    return active + inactive, erori


def catalog() -> list[ModelAI]:
    """Toate modelele definite, intai cele active (in ordinea din .env)."""
    return _citeste()[0]


def active() -> list[ModelAI]:
    return [m for m in catalog() if m.activ]


def implicit() -> ModelAI | None:
    """Primul model activ - cel cu care porneste agentul."""
    lista = active()
    return lista[0] if lista else None


def gaseste(text: str) -> ModelAI | None:
    """
    Cauta un model dupa: numarul din /modele ("2"), id complet
    ("gemini/gemini-3.8-flash") sau doar nume ("gemini-3.8-flash").
    """
    text = text.strip()
    toate = catalog()
    if text.isdigit():
        index = int(text) - 1
        return toate[index] if 0 <= index < len(toate) else None
    for m in toate:
        if text.lower() in (m.id.lower(), m.nume.lower()):
            return m
    return None


def probleme() -> list[str]:
    """Erorile de configurare care impiedica pornirea agentului."""
    lista = list(_citeste()[1])
    act = active()
    if not act:
        lista.append(
            "Niciun model activ. In .env pune cel putin unul in MODELE_ACTIVE, "
            "ex: MODELE_ACTIVE=gemini/gemini-3.6-flash"
        )
    if any(m.provider == "gemini" for m in act) and not config.GOOGLE_API_KEY:
        lista.append(
            "Ai modele Gemini active, dar GOOGLE_API_KEY lipseste din .env. "
            "Cheie gratuita: https://aistudio.google.com/apikey"
        )
    return lista


# ---------------------------------------------------------------------
# FACTORY (S4.4): din descrierea modelului -> obiectul LangChain gata de folosit
# ---------------------------------------------------------------------
def creeaza_llm(model: ModelAI) -> BaseChatModel:
    """
    Un dictionar de lambda-uri, un provider pe intrare. Adaugi un provider
    nou = adaugi o intrare aici si il treci in PROVIDERI. Restul aplicatiei
    nu afla niciodata ce clasa concreta ruleaza.
    """
    # Importuri locale: nu incarcam biblioteca unui provider pe care nu-l folosim.
    def _gemini() -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model.nume,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=config.TEMPERATURE,
            max_output_tokens=config.MAX_TOKENS,
        )

    def _ollama() -> BaseChatModel:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model.nume,
            base_url=config.OLLAMA_BASE_URL,
            temperature=config.TEMPERATURE,
        )

    fabrici: dict[str, Callable[[], BaseChatModel]] = {
        "gemini": _gemini,
        "ollama": _ollama,
    }
    return fabrici[model.provider]()
