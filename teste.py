import sys, os
import re
import json
from main import main 
from typing import List

class TerminalColors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    RESET = '\033[0m'

def suppress_prints() -> None:
    sys.stdout = open(os.devnull, 'w')

def restore_prints() -> None:
    sys.stdout = sys.__stdout__

def contains_num_with_tolerance(text: str, pattern: float, tolerance: float=0) -> bool:
    # Nota: o teste só corresponderá a números que tenham 3 ou mais casas decimais.
    nums = re.findall(r'\d*\.\d{3}', text)
    nums = [float(num) for num in nums]
    pattern_matches = [num for num in nums if abs(num - pattern) <= tolerance]
    return len(pattern_matches) >= 1
    
def public_tests():
    queries = [
    "Qual é a avaliação média do Bob's?",
    "Qual é a avaliação média do Paris 6?",
    "Quão bom é o restaurante KFC?",
    "Qual é a avaliação média do China in Box?",
    ]
    query_results = [3.79, 6.19, 4.64, 4.64]
    tolerances = [0.2, 0.2, 0.2, 0.15]
    contents = []
    
    for query in queries:
        with open("runtime-log.txt", "w") as f:
            sys.stdout = f
            main(query)
        with open("runtime-log.txt", "r") as f:
            contents.append(f.read())
            
    restore_prints()
    num_passed = 0
    for i, content in enumerate(contents):
        if not contains_num_with_tolerance(content, query_results[i], tolerance=tolerances[i]):
            print(TerminalColors.RED + f"Teste {i+1} Falhou." + TerminalColors.RESET, "Esperado: ", query_results[i], "Consulta: ", queries[i])
        else:
            print(TerminalColors.GREEN + f"Teste {i+1} Passou." + TerminalColors.RESET, "Esperado: ", query_results[i], "Consulta: ", queries[i])
            num_passed += 1
            
    print(f"{num_passed}/{len(queries)} Testes Passaram")

public_tests()
