# QA Agent — Management flotă & închiriere autorulote

Tema Cursului 2 — *AI Agent Development*.
Un agent conversațional care răspunde la întrebări despre flota de autorulote,
disponibilitate, prețuri și scadențe tehnice — folosind **tools reale**, nu ghicit.

## Cele 4 livrabile ale temei

| # | Cerință | Unde se vede în cod |
|---|---------|---------------------|
| 1 | Tools cu Pydantic + `@register_tool` + `ToolWrapper` | `tools/` |
| 2 | Prompts în YAML + Jinja2 cu `PromptRegistry` | `prompts/` |
| 3 | Agent QA care leagă LLM + tools + prompts | `agent.py` |
| 4 | ReAct loop (Think→Act→Observe) | `agent.py` → `react_loop()` + `execute_tool()` (S6.4), `execute_all_tools()` în paralel (S6.5) |

## Instalare (o singură dată)

### Windows

```bash
py -3.11 -m venv .venv
```

Activare (PowerShell):
```bash
.venv\Scripts\Activate.ps1
```

Instalare pachete:
```bash
py -3.11 -m pip install -r requirements.txt
```

### macOS

Python-ul din macOS e prea vechi (3.9), iar pachetele cer minimum 3.10.
Folosim `uv`, care aduce singur Python 3.11, fără parolă de administrator:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Mediul virtual stă **în afara** folderului OneDrive, ca să nu se sincronizeze
și să nu îl strice pe cel de Windows (`.venv`):

```bash
~/.local/bin/uv venv --python 3.11 ~/.venvs/qa-agent-autorulote
VIRTUAL_ENV=~/.venvs/qa-agent-autorulote ~/.local/bin/uv pip install -r requirements.txt
```

Activare (în fiecare terminal nou):
```bash
source ~/.venvs/qa-agent-autorulote/bin/activate
```

## Configurare

Windows:
```bash
copy .env.example .env
```

macOS:
```bash
cp .env.example .env
```

Apoi deschide `.env` și completează. Pentru început nu ai nevoie de nicio cheie:
cu `MODELE_ACTIVE=ollama/qwen2.5:3b` merge local, gratuit (cere Ollama pornit, vezi mai jos).

## Pornire Ollama (providerul de dezvoltare)

Din folderul `share_lectia1` (dezarhivat din cursul 1), cu Docker pornit:
```bash
docker-compose up -d
```

## Rulare

Windows:
```bash
py -3.11 main.py
```

macOS (cu mediul activat):
```bash
python main.py
```

## Teste

```bash
pytest
```

136 de teste, sub 2 secunde, fără rețea și fără cheie de API. Instalare:

```bash
VIRTUAL_ENV=~/.venvs/qa-agent-autorulote uv pip install -r requirements-dev.txt
```

| Fișier | Ce acoperă |
|---|---|
| `tests/test_perioada.py` | zile vs nopți, treceri peste lună/an, an bisect |
| `tests/test_calendar.py` | sezoane, buffer, ferestre libere, statusuri, ancore |
| `tests/test_datastore.py` | tarife lipsă, statusuri necunoscute, documente, validare |
| `tests/test_ofertare.py` | durată minimă, discounturi în cascadă, rotunjiri, km |
| `tests/test_tools.py` | registry, catalog, cele 4 erori din S6.6, disponibilitate, matching |
| `tests/test_agent_react.py` | bucla ReAct cu un model fals: paralel, timeout, circuit breaker, buget |

Două reguli de construcție:

- **Testele nu ating `data/`.** Fixture-ul `date_test` face o copie a JSON-urilor
  într-un folder temporar și îndreaptă `datastore` către ea (`tests/conftest.py`).
- **Bucla ReAct se testează cu un model fals**, un obiect cu `.invoke()` care
  întoarce `AIMessage`. Fără rețea, fără costuri, rezultate identice la fiecare rulare.

## Reguli de business: unde stau și cum eșuează

- **Perioada** e un singur tip, `tools/perioada.py`. Partenerii facturează zile
  sau nopți; `PerioadaInchiriere` e singurul loc care traduce între date
  calendaristice și unități facturabile. Disponibilitate, matching și ofertare
  primesc același obiect, deci nu mai pot înțelege altceva din aceleași date.
- **Fail closed**: un tarif lipsă sau un sezon nedefinit opresc oferta cu
  `EROARE DE CONFIGURARE`, în loc să producă o zi la preț 0. Un status de
  rezervare necunoscut blochează calendarul, ca să nu apară dubla rezervare.
- **Validare la pornire**: `datastore.valideaza_configurarea()` rulează la
  fiecare pornire și la `/reload`, și verifică tarifele pe sezoane, statusurile
  rezervărilor, extraopțiunile și partenerii. Problemele se afișează ca
  `PROBLEMA DE CONFIGURARE`, fără să oprească agentul.
- **Documentele** (ITP, RCA, rovinietă, CASCO) care expiră înainte de predare
  apar ca avertisment în disponibilitate și în deviz. Nu blochează închirierea:
  pot fi reînnoite până la preluare, iar agentul îi spune clientului.

## Streaming

Răspunsul final apare pe ecran pe măsură ce vine de la model, nu dintr-o dată la
final. Rundele în care agentul cere unelte **nu pot** curge: ca să știi ce unealtă
cere modelul, îți trebuie cererea întreagă. Deci ordinea e: runde de verificare
(vizibile cu `--verbose`), apoi răspunsul care se scrie sub ochii tăi.

`agent.react_loop(mesaj, pe_text=...)` primește o funcție apelată pentru fiecare
bucată de text. Fără ea, comportamentul e cel dinainte: un singur răspuns la final.

## Plasele de siguranță (S6.7)

Patru limite, toate reglabile din `.env`:

| Setare | Implicit | Ce oprește |
|---|---|---|
| `MAX_ITERATIONS` | 8 | câte runde Think→Act→Observe are voie o întrebare |
| `MAX_TOKENS_TURA` | 50000 | tokenii consumați de toată tura (costuri) |
| `TOOL_TIMEOUT` | 10 s | cât are voie să dureze o unealtă |
| `TOOL_MAX_ERORI` | 3 | după atâtea erori, unealta nu mai e apelată (circuit breaker) |
| `MAX_REPETARI` | 2 | de câte ori lasă modelul să ceară același lucru |
| `MAX_APELURI_BLOCATE` | 2 | de câte ori insistă cu o unealtă deja oprită |

Toate setările se citesc într-un singur loc, `config.py`, care e singurul fișier
care deschide `.env`. Restul codului folosește `config.X`, deci nu există praguri
scrise direct în cod.

La oricare dintre ele, agentul nu crapă: mai cere modelului un răspuns final,
fără unelte, din informațiile strânse până atunci (`_raspuns_final_fortat()`).
Răspunsul se încheie mereu cu o mențiune pentru client — informațiile pot fi
incomplete și nu s-au mai făcut verificări — adăugată de agent, nu de model,
din `prompts/qa_agent/limita_nota.yaml`. Clientul nu află niciodată de tokeni,
runde sau unelte.

## Modelele AI: active și inactive

Modelele se definesc în `.env`, ca `provider/nume_model`:

```
MODELE_ACTIVE=gemini/gemini-3.6-flash, gemini/gemini-3.8-flash
MODELE_INACTIVE=gemini/gemini-3.1-flash-lite, ollama/qwen2.5:3b
```

- **primul model activ** e cel cu care pornește agentul
- ca să pornești sau să oprești un model, îl muți dintr-o linie în alta și repornești agentul
- în CLI: `/modele` afișează lista cu stare și preț, `/model <nr sau nume>` comută pe alt model activ
- la pornire: `main.py --model gemini-3.8-flash`

Catalogul (prețuri, fabrica de modele) e în `modele.py`.

## Observabilitate cu LangSmith

1. Cont pe https://eu.smith.langchain.com (UE) sau https://smith.langchain.com (SUA).
2. Settings → API Keys → **Personal Access Token**.
3. În `.env`:

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_ENDPOINT=https://eu.api.smith.langchain.com   # doar pentru cont UE
```

4. În CLI, comanda `/trace` afișează linkul către ultimul răspuns.

Ce se trasează: apelurile LLM (automat, de LangChain), execuția fiecărei unelte
(`tools/wrapper.py`) și tura completă cu metadata — model, versiunea promptului,
`thread_id` al conversației (`agent.py`).
