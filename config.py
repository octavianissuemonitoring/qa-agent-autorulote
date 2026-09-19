"""
Configuratia aplicatiei - un singur loc care citeste .env.

De ce un fisier separat:
    Daca fiecare modul ar chema os.getenv() pe cont propriu, ai avea valori
    implicite imprastiate prin tot codul si nu ai sti niciodata ce configuratie
    ruleaza de fapt. Asa, exista un singur raspuns la intrebarea "cu ce setari
    merge agentul acum" - si il poti si tipari.
"""

import logging
import os
import warnings
import sys

from dotenv import load_dotenv

# Citeste .env si pune valorile in os.environ.
# LangSmith se activeaza DOAR din variabile de mediu (slide S8.3): odata
# incarcate aici, LangChain le vede singur. Zero cod de tracing in agent.
load_dotenv()


def _text(cheie: str, implicit: str = "") -> str:
    return os.getenv(cheie, implicit).strip()


def _numar(cheie: str, implicit: int) -> int:
    try:
        return int(os.getenv(cheie, implicit))
    except (TypeError, ValueError):
        return implicit


def _zecimal(cheie: str, implicit: float) -> float:
    try:
        return float(os.getenv(cheie, implicit))
    except (TypeError, ValueError):
        return implicit


# --- Modelele AI -----------------------------------------------------
# Listele se interpreteaza in modele.py. Aici doar le citim ca text.
#   MODELE_ACTIVE   - pot fi folosite; primul e cel implicit
#   MODELE_INACTIVE - definite, dar oprite
MODELE_ACTIVE = _text("MODELE_ACTIVE")
MODELE_INACTIVE = _text("MODELE_INACTIVE")

# Compatibilitate cu varianta veche a .env (un singur PROVIDER + model):
# daca lista noua lipseste, o construim din variabilele vechi.
if not MODELE_ACTIVE:
    _provider_vechi = _text("PROVIDER", "gemini").lower()
    _model_vechi = (
        _text("GEMINI_MODEL", "gemini-3.6-flash")
        if _provider_vechi == "gemini"
        else _text("OLLAMA_MODEL", "qwen2.5:3b")
    )
    MODELE_ACTIVE = f"{_provider_vechi}/{_model_vechi}"

# --- Conexiuni per provider ------------------------------------------
GOOGLE_API_KEY = _text("GOOGLE_API_KEY")
OLLAMA_BASE_URL = _text("OLLAMA_BASE_URL", "http://localhost:11434")

# --- Parametri de generare -------------------------------------------
TEMPERATURE = _zecimal("TEMPERATURE", 0.0)
MAX_TOKENS = _numar("MAX_TOKENS", 2048)

# --- ReAct: cele 4 plase de siguranta din S6.7 -----------------------
# 1. cate runde GANDESTE->ACTIONEAZA->OBSERVA are voie o tura
MAX_ITERATIONS = _numar("MAX_ITERATIONS", 8)
# 2. plafon de tokeni pe TOATA tura (intrare + iesire), pentru costuri.
#    MAX_TOKENS de mai sus limiteaza un singur raspuns; asta limiteaza sirul.
MAX_TOKENS_TURA = _numar("MAX_TOKENS_TURA", 50_000)
# 3. cat are voie sa dureze UN tool. Acum uneltele citesc JSON local si
#    dureaza sub o milisecunda, dar la primul API extern conteaza.
TOOL_TIMEOUT = _zecimal("TOOL_TIMEOUT", 10.0)
# 4. circuit breaker: dupa atatea erori intr-o tura, tool-ul nu mai e apelat
TOOL_MAX_ERORI = _numar("TOOL_MAX_ERORI", 3)

# --- Identitatea agentului (ajunge in system prompt prin Jinja2) ------
NUME_COMPANIE = _text("NUME_COMPANIE", "CamperHub")
NUME_AGENT = _text("NUME_AGENT", "Ruta")
CANAL_CONTACT = _text("CANAL_CONTACT", "echipa de rezervari")

# --- Observability (LangSmith, S8.3) ---------------------------------
# Biblioteca langsmith accepta doua familii de nume: LANGCHAIN_* (cele din
# curs) si LANGSMITH_* (cele din documentatia noua). Le citim pe amandoua,
# ca sa mearga orice ai copia de pe site.
LANGCHAIN_TRACING = (
    _text("LANGCHAIN_TRACING_V2") or _text("LANGSMITH_TRACING") or "false"
).lower() == "true"
LANGSMITH_API_KEY = _text("LANGCHAIN_API_KEY") or _text("LANGSMITH_API_KEY")
LANGCHAIN_PROJECT = (
    _text("LANGCHAIN_PROJECT") or _text("LANGSMITH_PROJECT") or "qa-agent-autorulote-dev"
)
# Regiunea contului: SUA (implicit) sau UE. Un cont creat pe eu.smith.langchain.com
# NU functioneaza cu adresa din SUA - raspunde cu 401, ca si cum cheia ar fi gresita.
LANGSMITH_ENDPOINT = (
    _text("LANGCHAIN_ENDPOINT") or _text("LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com"
)


def descrie(model_curent=None) -> str:
    """Configuratia activa, pentru afisare la pornire si pentru /config."""
    import modele  # import local: modele.py importa config, evitam cercul

    model = model_curent or modele.implicit()
    active = modele.active()

    if model is None:
        linie_model = "model: NICIUNUL ACTIV"
    else:
        linie_model = f"model: {model.id}"
        if model.provider == "gemini":
            linie_model += f" | GOOGLE_API_KEY: {'prezenta' if GOOGLE_API_KEY else 'LIPSA'}"
        else:
            linie_model += f" | server: {OLLAMA_BASE_URL}"

    if LANGCHAIN_TRACING:
        regiune = "UE" if ".eu." in LANGSMITH_ENDPOINT or "eu.api" in LANGSMITH_ENDPOINT else "SUA"
        tracing = f"LangSmith ON | proiect: {LANGCHAIN_PROJECT} | regiune: {regiune}"
    else:
        tracing = "LangSmith OFF"

    temp = f"{TEMPERATURE}"
    if model is not None and model.temperatura_ignorata:
        temp += " (ignorata - modelul are parametri de generare ficsi)"

    return (
        f"{linie_model}\n"
        f"modele active: {len(active)} din {len(modele.catalog())} definite (/modele)\n"
        f"temperature: {temp} | max_tokens: {MAX_TOKENS} | "
        f"max_iteratii ReAct: {MAX_ITERATIONS}\n"
        f"limite tura: {MAX_TOKENS_TURA} tokeni | tool: {TOOL_TIMEOUT}s, "
        f"max {TOOL_MAX_ERORI} erori\n"
        f"{tracing}"
    )


def verifica() -> list[str]:
    """Problemele de configuratie care ar face agentul sa nu porneasca."""
    import modele

    probleme = modele.probleme()
    if LANGCHAIN_TRACING and not LANGSMITH_API_KEY:
        probleme.append(
            "LANGCHAIN_TRACING_V2=true dar LANGCHAIN_API_KEY lipseste din .env. "
            "Genereaza o cheie pe https://smith.langchain.com -> Settings -> API Keys, "
            "sau pune LANGCHAIN_TRACING_V2=false."
        )
    return probleme


def pregateste_consola() -> None:
    """
    Windows scrie implicit in consola cu codificarea cp1252, care nu stie
    diacritice. Fara linia asta, un raspuns cu 'ă' opreste programul.
    """
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    # Unele modele Gemini (3.x) au parametri de generare FICSI si avertizeaza
    # la fiecare apel ca ignora `temperature`. Informatia e utila, dar repetata
    # de zeci de ori ineaca afisarea rationamentului. O oprim aici si o spunem
    # o singura data, in descrie().
    warnings.filterwarnings(
        "ignore", message=".*uses fixed sampling defaults.*", category=UserWarning
    )

    # Biblioteca Google scrie in consola sfaturi interne ("automatic function
    # calling...") care nu privesc codul nostru - noi executam uneltele singuri.
    logging.getLogger("google_genai").setLevel(logging.ERROR)
