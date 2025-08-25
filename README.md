# Conversational Agents — Restaurante Score

Sistema multiagente (AutoGen) que lê avaliações de restaurantes, extrai escores de **comida** e **atendimento** e calcula a **nota final (0..10)**. Fluxo: `data_fetch_agent → review_analysis_agent → score_agent` via `initiate_chats`, com **I/O em JSON** entre os agentes.

> **Dataset:** `restaurantes.txt`
>
> **Entrada (NL):** perguntas como _“Qual é a avaliação média do Bob's?”_
>
> **Saída (CLI):** `A avaliação média do <nome> é <nota>.`

---

## Requisitos

- **Python 3.10+** (testado em 3.12)
- **requirements.txt** (instalação automática via Makefile)
- Chave de API da OpenAI (`OPENAI_API_KEY`)

### Dependências (requirements.txt)
```
pyautogen>=0.2.0,<0.3.0
openai>=1.35.0
python-dotenv>=1.0.1
```
> ⚠️ O aviso `flaml.automl is not available` pode aparecer e pode ser ignorado.

---

## Setup Rápido (Makefile)

```bash
# 1) Criar venv e instalar deps a partir do requirements.txt
make install

# 2) Configure sua chave
## 2a) Export direto (Unix/macOS)
export OPENAI_API_KEY="sua_chave_aqui"

## 2b) ou Windows PowerShell
$Env:OPENAI_API_KEY = "sua_chave_aqui"

# 3) Rodar um exemplo
make run QUERY="Qual é a avaliação média do Bob's?"

# 4) Rodar a suíte de testes públicos
make test
```

### Alvos disponíveis
- `make venv` – cria `.venv`
- `make install` – instala deps de `requirements.txt`
- `make run QUERY='...'` – executa `main.py` com sua consulta
- `make test` – executa `teste.py`
- `make clean` – limpeza de artefatos e `runtime-log.txt`
- `make distclean` – remove o ambiente virtual

---

## Execução Manual (sem Makefile)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt

# Defina a chave
export OPENAI_API_KEY="sua_chave_aqui" 

# Executar diretamente
python3 main.py "Qual é a avaliação média do Bob's?"
```

### Rodar os testes manualmente

```bash
python3 teste.py
```

Saída esperada (quando tudo ok):

```
Teste 1 Passou. Esperado:  3.79 Consulta:  Qual é a avaliação média do Bob's?
Teste 2 Passou. Esperado:  6.19 Consulta:  Qual é a avaliação média do Paris 6?
Teste 3 Passou. Esperado:  4.64 Consulta:  Quão bom é o restaurante KFC?
Teste 4 Passou. Esperado:  4.64 Consulta:  Qual é a avaliação média do China in Box?
4/4 Testes Passaram
```

---

## Exemplos de Uso

### 1) Bob's
```bash
make run QUERY="Qual é a avaliação média do Bob's?"
# A avaliação média do Bob's é 3.790.
```

### 2) Paris 6
```bash
make run QUERY="Qual é a avaliação média do Paris 6?"
# A avaliação média do Paris 6 é 6.190.
```

### 3) KFC
```bash
make run QUERY="Quão bom é o restaurante KFC?"
# A avaliação média do KFC é 4.640.
```

### 4) China in Box
```bash
make run QUERY="Qual é a avaliação média do China in Box?"
# A avaliação média do China in Box é 4.640.
```

> **Restaurante não encontrado:** o sistema imprime `Não encontrei avaliações para <nome>.` e encerra.

---

## Estrutura do Repositório

```
.
├── main.py            # pipeline multiagente (initiate_chats, JSON-only)
├── restaurantes.txt   # dataset
├── teste.py           # testes públicos (importa de solucao.py)
├── requirements.txt   # dependências de runtime
├── Makefile           # automações (venv, install, run, test...)
├── README.md          # instruções
├── LICENSE            # licença do projeto
├── .gitignore         # sug.: incluir .venv/, __pycache__/, runtime-log.txt
└── runtime-log.txt    # arquivo temporário criado pelos testes (pode ser ignorado no Git)
```

---

## Notas Técnicas

- **Agentes:** `data_fetch_agent`, `review_analysis_agent`, `score_agent`.
- **Ferramentas registradas:**
  - `fetch_restaurant_data(restaurant_name) -> {nome: [frases]}`
  - `analyze_reviews(review_sentences) -> {food_scores: [...], customer_service_scores: [...]}`
  - `calculate_overall_score(restaurant_name, food_scores, customer_service_scores) -> {nome: nota}`
- **Escala de adjetivos:** exatamente a do enunciado; flexões (feminino/plural) são geradas em tempo de execução para *matching*.
- **Fallbacks:** se não houver frases, o fluxo é interrompido; se uma dimensão não tiver adjetivo, assume-se 3 (neutro).

---

## Solução de Problemas

- **`OPENAI_API_KEY` não definido** – defina a variável de ambiente.
- **Aviso `flaml.automl`** – pode ser ignorado.
- **`Function <tool> not found` no AutoGen** – confirme que as ferramentas estão registradas **tanto** no agente especializado quanto no `entrypoint_agent`.
- **Modelo** – por padrão usa `gpt-4o-mini`. Se quiser trocar, altere em `main.py` a `llm_config`.

---

## Licença
Consulte o arquivo `LICENSE`. 

