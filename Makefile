PY       ?= python3
VENV     ?= .venv
PYBIN    := $(VENV)/bin/python
PIP      := $(VENV)/bin/pip

.PHONY: venv install run test prepare-tests clean distclean

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

# Executa a suíte de testes públicos
# Uso: make test  (requer OPENAI_API_KEY)
test:
	@[ -n "$$OPENAI_API_KEY" ] || (echo "ERROR: defina OPENAI_API_KEY" && exit 1)
	$(PYBIN) teste.py

# Executa o main com uma consulta natural
# Uso: make run QUERY="Qual é a avaliação média do Bob's?"
run:
	@[ -n "$$OPENAI_API_KEY" ] || (echo "ERROR: defina OPENAI_API_KEY" && exit 1)
	@[ -n "$(QUERY)" ] || (echo "Uso: make run QUERY='sua pergunta'" && exit 2)
	$(PYBIN) main.py "$(QUERY)"

# Limpezas básicas
clean:
	rm -rf __pycache__ .pytest_cache .cache runtime-log.txt

# Limpeza pesada (remove o ambiente virtual)
distclean: 
	rm -rf $(VENV)
