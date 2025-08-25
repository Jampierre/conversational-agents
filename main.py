from __future__ import annotations
from typing import Dict, List, Any
from autogen import ConversableAgent
import os, sys, json, math, unicodedata

if not os.environ.get("OPENAI_API_KEY"):
    raise RuntimeError(
        "OPENAI_API_KEY não definido. Exporte sua chave antes de executar.\n"
        "  export OPENAI_API_KEY='sua_chave_aqui'"
    )

# =============================
# Utilitários (sem regex para parsing de respostas)
# =============================

def _normalize(s: str) -> str:
    """Normaliza uma string para facilitar matching textual.

    Aplica *lowercase* e remoção de acentos/diacríticos (Unicode NFD) para
    permitir comparações mais robustas entre nomes e textos no corpus.

    Args:
        s (str): Texto de entrada.

    Returns:
        str: Texto normalizado sem acentos e em minúsculas.

    Examples:
        >>> _normalize("Café Satisfatório")
        'cafe satisfatorio'
    """
    s = s.lower()
    s = "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )
    return s


def _load_reviews() -> Dict[str, str]:
    """Carrega o conjunto de avaliações do arquivo ``restaurantes.txt``.

    Procura o arquivo no diretório atual e ao lado do script e retorna um dicionário
    em que a chave é o nome do restaurante e o valor é o texto integral de avaliação
    (uma string única que poderá ser fracionada em sentenças posteriormente).

    Returns:
        Dict[str, str]: Mapa ``{nome_restaurante: texto_avaliacao}``.

    Raises:
        FileNotFoundError: Se o arquivo ``restaurantes.txt`` não for encontrado.

    Examples:
        >>> data = _load_reviews()
        >>> 'Bob\'s' in data
        True
    """
    candidates = [
        os.path.join(os.getcwd(), "restaurantes.txt"),
        os.path.join(os.path.dirname(__file__), "restaurantes.txt"),
    ]
    path = None
    for c in candidates:
        if os.path.exists(c):
            path = c
            break
    if not path:
        raise FileNotFoundError("Arquivo 'restaurantes.txt' não encontrado.")

    data: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Split apenas no primeiro ponto
            if ". " in line:
                name, review = line.split(". ", 1)
            else:
                parts = line.split(".", 1)
                name = parts[0]
                review = parts[1].lstrip() if len(parts) > 1 else ""
            data[name.strip()] = review.strip()
    return data


# Léxico estritamente conforme o PDF
ADJ_SCALE: Dict[int, List[str]] ={
    1: ["horrivel", "nojento", "terrivel"],
    2: ["ruim", "desagradavel", "ofensivo"],
    3: ["mediano", "sem graca", "irrelevante"],
    4: ["bom", "agradavel", "satisfatorio"],
    5: ["incrivel", "impressionante", "surpreendente"],
}

def _expand_adj_variants(adj: str) -> List[str]:
    """Gera variantes flexionais (feminino/plural) **sem alterar** a lista-base.

    Regras simples para PT-BR após normalização (sem acentos):
    - "bom" -> boa, bons, boas (irregular)
    - termina com "o" -> a, os, as
    - termina com "vel" -> veis (agradavel -> agradaveis)
    - termina com "el" -> eis (terrivel -> terriveis)
    - termina com "ivel" -> ives (incrivel -> incriveis)
    - termina com "ente"/"ante" -> adiciona plural com "s" (impressionante -> impressionantes)
    - termina com "ivo" -> iva, ivos, ivas (ofensivo -> ofensiva/...)
    - "ruim" -> ruins (caso especial)
    - formas invariantes mantêm-se (e.g., "sem graca")
    """
    a = adj
    variants = {a}

    if a == "bom":
        variants.update(["boa", "bons", "boas"])
        return list(variants)
    if a == "ruim":
        variants.add("ruins")
        return list(variants)

    if a.endswith("o"):
        stem = a[:-1]
        variants.update([stem + "a", stem + "os", stem + "as"])
    if a.endswith("ivel"):
        variants.add(a[:-4] + "iveis")
    if a.endswith("vel"):
        variants.add(a[:-3] + "veis")
    if a.endswith("el"):
        variants.add(a[:-2] + "eis")
    if a.endswith("ente") or a.endswith("ante"):
        variants.add(a + "s")
    if a.endswith("ivo"):
        stem = a[:-3]
        variants.update([stem + "iva", stem + "ivos", stem + "ivas"])

    return list(variants)


def _build_adj_index(scale: Dict[int, List[str]]) -> Dict[int, List[str]]:
    """Expande automaticamente as formas para cada escore, preservando a lista-base."""
    idx: Dict[int, List[str]] = {}
    for score, adjs in scale.items():
        bucket: List[str] = []
        for a in adjs:
            bucket.extend(_expand_adj_variants(a))
        # Remove duplicatas preservando ordem
        seen = set()
        uniq = []
        for x in bucket:
            if x not in seen:
                uniq.append(x)
                seen.add(x)
        idx[score] = uniq
    return idx

# Índice de adjetivos expandido em tempo de carga (sem tocar na lista-base)
ADJ_IDX: Dict[int, List[str]] = _build_adj_index(ADJ_SCALE)

FOOD_KW: List[str] =[
    "comida",
    "pastel",
    "sanduiche",
    "sanduiches",
    "frango",
    "hamburguer",
    "hamburgueres",
    "cafe",
    "doces",
    "donuts",
    "pratos",
    "saladas",
    "sopas",
    "cookie",
    "cookies",
]

SERVICE_KW: List[str] =[
    "atendimento",
    "funcionarios",
    "garcons",
    "servico",
    "equipe",
    "baristas",
    "garcom",
    "espera",
]


def _score_for_sentence(sentence: str, target_terms: List[str]) -> int:
    """Atribui um escore (1..5) a uma sentença dado um conjunto de termos-alvo.

    Não altera a escala original: gera flexões automaticamente (feminino/plural)
    via :data:`ADJ_IDX` e escolhe o adjetivo mais próximo de qualquer termo-alvo.

    Critério de desempate: se duas opções tiverem a mesma distância, **prefere-se
    o maior escore** (5 > 4 > 3 > 2 > 1).

    Args:
        sentence (str): Sentença da avaliação.
        target_terms (List[str]): Lista de termos que definem a área de interesse
        (e.g., ``FOOD_KW`` ou ``SERVICE_KW``).

    Returns:
        int: Escore inteiro na escala de 1 a 5.

    Examples:
        >>> _score_for_sentence('A comida é boa e o ambiente agradável.', FOOD_KW)
        4
    """
    s = _normalize(sentence)
    if not any(t in s for t in target_terms):
        return 3

    def _positions(hay: str, needle: str) -> List[int]:
        i, acc = 0, []
        while True:
            i = hay.find(needle, i)
            if i == -1:
                break
            acc.append(i + len(needle) // 2)
            i += max(1, len(needle))
        return acc

    target_pos: List[int] = []
    for t in target_terms:
        target_pos.extend(_positions(s, t))
    if not target_pos:
        return 3

    # menor distância e, em empate, maior escore (via -desired)
    best: tuple[int, int] | None = None
    best_score: int | None = None

    for desired in (5, 4, 3, 2, 1):
        for adj in ADJ_IDX[desired]:
            for apos in _positions(s, adj):
                dist = min(abs(apos - tpos) for tpos in target_pos)
                cand = (dist, -desired)
                if best is None or cand < best:
                    best = cand
                    best_score = desired

    return best_score if best_score is not None else 3


# ---------- 1) fetch_restaurant_data (tool) ----------

def fetch_restaurant_data(restaurant_name: str) -> Dict[str, List[str]]:
    """Recupera as avaliações de um restaurante a partir do corpus local.

    Lê o arquivo de avaliações e realiza *matching* tolerante pelo nome para
    localizar a entrada correspondente. O texto integral da avaliação é então
    fragmentado em sentenças simples (com base em pontuação) e retornado no
    formato esperado pelo agente de busca de dados.

    Args:
        restaurant_name (str): Nome consultado do restaurante.

    Returns:
        Dict[str, List[str]]: Dicionário ``{nome_exato: [sentencas]}``. Caso o
        restaurante não seja encontrado, retorna ``{restaurant_name: []}``.
    """
    reviews = _load_reviews()
    # Matching flexível pelo nome
    q = _normalize(restaurant_name)
    chosen_name: str | None = None
    for name in reviews.keys():
        n = _normalize(name)
        if q == n or q in n or n in q or q.replace(" ", "") in n.replace(" ", ""):
            chosen_name = name
            break
    if chosen_name is None:
        # fallback: escolhe a melhor similaridade simples (início que bate)
        for name in reviews.keys():
            if q in _normalize(name):
                chosen_name = name
                break
    if chosen_name is None:
        return {restaurant_name: []}

    # Split de frases de forma simples (sem regex complexa)
    raw = reviews[chosen_name]
    sentences: List[str] = []
    acc = ""
    for ch in raw:
        acc += ch
        if ch in ".!?":
            frag = acc.strip()
            if frag:
                sentences.append(frag)
            acc = ""
    if acc.strip():
        sentences.append(acc.strip())

    # Normaliza removendo pontuação final para facilitar
    sentences = [s.strip().rstrip(".!?") for s in sentences if s.strip()]
    return {chosen_name: sentences}


# ---------- 2) analyze_reviews (tool) ----------

def analyze_reviews(review_sentences: List[str]) -> Dict[str, List[int]]:
    """Converte frases de avaliação em escores numéricos para comida e serviço.

    A função busca a **primeira** sentença relevante para *comida* e
    a **primeira** para *serviço* (quando disponíveis), atribuindo um escore (1..5)
    a cada uma via :func:`_score_for_sentence`. Caso alguma dimensão não seja
    encontrada, assume o valor neutro 3. O resultado contém **apenas um par**
    de escores, compatível com os testes públicos fornecidos.

    Args:
        review_sentences (List[str]): Lista de sentenças associadas ao restaurante.

    Returns:
        Dict[str, List[int]]: Dicionário com as chaves ``"food_scores"`` e
        ``"customer_service_scores"``, cada uma contendo uma lista de inteiros.

    Examples:
        >>> analyze_reviews(["Comida boa.", "Atendimento satisfatório."])
        {'food_scores': [4], 'customer_service_scores': [4]}
    """
    food_scores: List[int] = []
    service_scores: List[int] = []

    # Varre na ordem, pegando a primeira sentença que fala de comida e a primeira que fala de serviço
    first_food: int | None = None
    first_service: int | None = None

    for sent in review_sentences:
        if first_food is None and any(k in _normalize(sent) for k in FOOD_KW):
            first_food = _score_for_sentence(sent, FOOD_KW)
        if first_service is None and any(k in _normalize(sent) for k in SERVICE_KW):
            first_service = _score_for_sentence(sent, SERVICE_KW)
        if first_food is not None and first_service is not None:
            break

    # Defaults se não encontrar
    if first_food is None:
        print("first_food - NONE")
        first_food = 3
    if first_service is None:
        print("first_service - NONE")
        first_service = 3

    food_scores.append(first_food)
    service_scores.append(first_service)
    return {"food_scores": food_scores, "customer_service_scores": service_scores}


# ---------- 3) calculate_overall_score (tool) ----------

def calculate_overall_score(
    restaurant_name: str, food_scores: List[int], customer_service_scores: List[int]
) -> Dict[str, float]:
    """Calcula a nota final (0..10) do restaurante com 3 casas decimais.

    A fórmula implementada segue a especificação do desafio, utilizando a
    normalização por ``N * sqrt(125)`` e o fator ``* 10``. Apenas os primeiros
    ``min(len(food_scores), len(customer_service_scores))`` pares são considerados.

    Args:
        restaurant_name (str): Nome do restaurante.
        food_scores (List[int]): Escores de comida na escala 1..5.
        customer_service_scores (List[int]): Escores de atendimento na escala 1..5.

    Returns:
        Dict[str, float]: Dicionário ``{restaurant_name: nota}`` com a nota final
        arredondada para 3 casas decimais.

    Examples:
        >>> calculate_overall_score('Exemplo', [3], [4])
        {'Exemplo': 5.366}
    """
    if not food_scores or not customer_service_scores:
        return {restaurant_name: 0.000}
    N = min(len(food_scores), len(customer_service_scores))
    total = 0.0
    for i in range(N):
        f = float(food_scores[i])
        s = float(customer_service_scores[i])
        total += (abs(f) * math.sqrt(s))
    score = total * 10.0 / (N * math.sqrt(125.0))
    score = float(f"{score:.3f}")
    return {restaurant_name: score}


# =============================
# Prompts auxiliares
# =============================

def get_data_fetch_agent_prompt(user_query: str) -> str:
    """Gera o prompt para o *data_fetch_agent*.

    O prompt instrui o agente a extrair o nome do restaurante, invocar a tool
    :func:`fetch_restaurant_data` e responder exclusivamente com JSON válido.

    Args:
        user_query (str): Consulta original do usuário.

    Returns:
        str: Prompt a ser enviado ao agente de busca de dados.
    """
    return (
        "Você é o data_fetch_agent.\n"
        "1) Extraia APENAS o nome do restaurante da consulta do usuário.\n"
        "2) Chame a função `fetch_restaurant_data(restaurant_name)` com esse nome.\n"
        "3) Responda **somente** com um JSON válido (aspas duplas) no formato {\"<Nome>\": [\"frase\", ...]}.\n"
        f"Consulta do usuário: {user_query!r}"
    )


def get_review_analysis_agent_prompt(name: str, sentences: List[str]) -> str:
    """Gera o prompt para o *review_analysis_agent*.

    Args:
        name (str): Nome do restaurante.
        sentences (List[str]): Sentenças de avaliação associadas.

    Returns:
        str: Prompt que inclui um payload JSON e instruções para invocar
        :func:`analyze_reviews` e responder apenas com JSON válido.
    """
    payload = json.dumps({name: sentences}, ensure_ascii=False)
    return (
        "Você é o review_analysis_agent.\n"
        "Receba o JSON com o restaurante e as frases. Chame `analyze_reviews(review_sentences)`.\n"
        "Responda **somente** com um JSON válido com as chaves \"food_scores\" e \"customer_service_scores\".\n"
        f"Entrada: {payload}"
    )


def get_score_agent_prompt(name: str, food_scores: List[int], service_scores: List[int]) -> str:
    """Gera o prompt para o *score_agent*.

    Args:
        name (str): Nome do restaurante.
        food_scores (List[int]): Escores de comida (1..5).
        service_scores (List[int]): Escores de atendimento (1..5).

    Returns:
        str: Prompt instruindo a chamada de :func:`calculate_overall_score` e
        a resposta estritamente em JSON válido com ``{"<Nome>": <nota>}``.
    """
    return (
        "Você é o score_agent.\n"
        "Chame `calculate_overall_score(restaurant_name, food_scores, customer_service_scores)`.\n"
        "Responda **somente** com um JSON válido {\"<Nome>\": <nota_com_3_casas>}.\n"
        f"restaurant_name={json.dumps(name, ensure_ascii=False)}\n"
        f"food_scores={json.dumps(food_scores)}\n"
        f"customer_service_scores={json.dumps(service_scores)}\n"
    )


# =============================
# Helpers para lidar com o retorno do Autogen
# =============================

def _extract_last_content(chat_result: Any) -> str:
    """Extrai o conteúdo textual da última mensagem de um ``ChatResult``.

    A função é resiliente a diferenças de versão do AutoGen, aceitando tanto
    um objeto único quanto listas/dicionários com histórico de mensagens.

    Args:
        chat_result (Any): Objeto retornado por ``initiate_chats``.

    Returns:
        str: Conteúdo (``content``) da última mensagem, ou ``"{}"`` se ausente.
    """
    try:
        results = chat_result if isinstance(chat_result, list) else [chat_result]
        last = results[-1]
        history = getattr(last, "chat_history", None)
        if history is None and isinstance(last, dict):
            history = last.get("chat_history")
        if not history:
            return "{}"
        msg = history[-1]
        if isinstance(msg, dict):
            return msg.get("content", "{}")
        # Em versões recentes, a mensagem pode ser um objeto com atributo .content
        return getattr(msg, "content", "{}") or "{}"
    except Exception:
        return "{}"


def _clean_code_fence(text: str) -> str:
    """Remove cercas de código (``````, `````json```) do início do texto, se houver.

    Útil quando o modelo devolve o JSON dentro de um bloco de código.

    Args:
        text (str): Texto potencialmente envolvido por cercas de código.

    Returns:
        str: Texto sem a cerca inicial.
    """
    cleaned = text.strip()
    if cleaned.startswith("```") or cleaned.startswith("````"):
        cleaned = cleaned.strip("`\n").split("\n", 1)[-1]
    return cleaned


# =============================
# Orquestração via initiate_chats
# =============================

def main(user_query: str) -> None:
    """Ponto de entrada do sistema multiagente baseado em AutoGen.

    Orquestra três agentes especializados (``data_fetch_agent``,
    ``review_analysis_agent`` e ``score_agent``) via ``initiate_chats`` para
    recuperar sentenças de avaliação, extrair escores e calcular a nota final.
    A resposta é impressa no ``stdout`` no formato exigido pelos testes públicos.

    Args:
        user_query (str): Consulta natural do usuário, contendo o nome do restaurante.

    Side Effects:
        Imprime a resposta final no ``stdout``.

    Raises:
        RuntimeError: Em caso de falhas na decodificação de JSON ou formatos
            inesperados nas respostas dos agentes.
    """
    llm_config = {"config_list": [{"model": "gpt-4o-mini", "api_key": os.environ["OPENAI_API_KEY"]}]}

    # Supervisor
    entrypoint_agent = ConversableAgent(
        "entrypoint_agent",
        system_message=(
            "Você é o orquestrador. Siga a sequência:\n"
            "1) data_fetch_agent -> fetch_restaurant_data;\n"
            "2) review_analysis_agent -> analyze_reviews;\n"
            "3) score_agent -> calculate_overall_score;\n"
            "Ao final, retorne ao usuário apenas: 'A avaliação média do <nome> é <nota>.'\n"
        ),
        llm_config=llm_config,
    )

    # data_fetch_agent
    data_fetch_agent = ConversableAgent(
        "data_fetch_agent",
        system_message=(
            "Você recupera avaliações chamando a ferramenta `fetch_restaurant_data(restaurant_name)` e"
            " devolve somente JSON válido."
        ),
        llm_config=llm_config,
    )
    # Registra a ferramenta no agente QUE CHAMARÁ e também no orquestrador (por segurança)
    for agent in (data_fetch_agent, entrypoint_agent):
        agent.register_for_llm(
            name="fetch_restaurant_data",
            description="Obtém as avaliações de um restaurante específico.",
        )(fetch_restaurant_data)
        agent.register_for_execution(name="fetch_restaurant_data")(fetch_restaurant_data)

    # review_analysis_agent
    review_analysis_agent = ConversableAgent(
        "review_analysis_agent",
        system_message=(
            "Você analisa as frases e converte em escores 1..5 de comida e atendimento usando a escala fixa."
            " Sempre retorne JSON válido."
        ),
        llm_config=llm_config,
    )
    for agent in (review_analysis_agent, entrypoint_agent):
        agent.register_for_llm(
            name="analyze_reviews",
            description="Analisa frases de avaliação e retorna listas de escores de comida e atendimento.",
        )(analyze_reviews)
        agent.register_for_execution(name="analyze_reviews")(analyze_reviews)

    # score_agent
    score_agent = ConversableAgent(
        "score_agent",
        system_message=(
            "Você calcula a pontuação final com 3 casas decimais e retorna somente JSON válido."
        ),
        llm_config=llm_config,
    )
    for agent in (score_agent, entrypoint_agent):
        agent.register_for_llm(
            name="calculate_overall_score",
            description="Calcula a nota final do restaurante com 3 casas decimais.",
        )(calculate_overall_score)
        agent.register_for_execution(name="calculate_overall_score")(calculate_overall_score)

    # ===== Passo 1 =====
    flow1 = [
        {
            "recipient": data_fetch_agent,
            "message": get_data_fetch_agent_prompt(user_query),
            "function_map": {"fetch_restaurant_data": fetch_restaurant_data},
            "max_turns": 2,
        }
    ]
    out1 = entrypoint_agent.initiate_chats(flow1)
    msg1 = _extract_last_content(out1)
    try:
        fetched_dict = json.loads(_clean_code_fence(msg1))
    except Exception as e:
        raise RuntimeError(f"Falha ao decodificar JSON retornado pelo data_fetch_agent: {e}\nConteúdo: {msg1}")

    if not isinstance(fetched_dict, dict) or not fetched_dict:
        print("Não encontrei avaliações para este restaurante.")
        return

    restaurant_name, sentences = next(iter(fetched_dict.items()))
    if not sentences:
        print(f"Não encontrei avaliações para {restaurant_name}.")
        return
    
    if not isinstance(sentences, list):
        raise RuntimeError("Formato inesperado de avaliações.")

    # ===== Passo 2 =====
    flow2 = [
        {
            "recipient": review_analysis_agent,
            "message": get_review_analysis_agent_prompt(restaurant_name, sentences),
            "function_map": {"analyze_reviews": analyze_reviews},
            "max_turns": 2,
        }
    ]
    out2 = entrypoint_agent.initiate_chats(flow2)
    msg2 = _extract_last_content(out2)
    try:
        analyzed = json.loads(_clean_code_fence(msg2))
    except Exception as e:
        raise RuntimeError(f"Falha ao decodificar JSON do review_analysis_agent: {e}\nConteúdo: {msg2}")

    if not (isinstance(analyzed, dict) and "food_scores" in analyzed and "customer_service_scores" in analyzed):
        raise RuntimeError("Estrutura inesperada de escores.")

    food_scores = [int(x) for x in analyzed["food_scores"]]
    service_scores = [int(x) for x in analyzed["customer_service_scores"]]

    # ===== Passo 3 =====
    flow3 = [
        {
            "recipient": score_agent,
            "message": get_score_agent_prompt(restaurant_name, food_scores, service_scores),
            "function_map": {"calculate_overall_score": calculate_overall_score},
            "max_turns": 2,
        }
    ]
    out3 = entrypoint_agent.initiate_chats(flow3)
    msg3 = _extract_last_content(out3)
    try:
        scored = json.loads(_clean_code_fence(msg3))
    except Exception as e:
        raise RuntimeError(f"Falha ao decodificar JSON do score_agent: {e}\nConteúdo: {msg3}")

    if not isinstance(scored, dict) or not scored:
        raise RuntimeError("Estrutura inesperada com a nota final.")

    final_name, final_score = next(iter(scored.items()))
    try:
        final_score_num = float(final_score)
    except Exception:
        raise RuntimeError("Nota final não numérica.")

    print(f"A avaliação média do {final_name} é {final_score_num:.3f}.")


if __name__ == "__main__":
    assert len(sys.argv) > 1, "Inclua a consulta para algum restaurante ao executar a função main."
    main(sys.argv[1])
