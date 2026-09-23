"""Gera conversas sinteticas com PII falsa para testar o pipeline inteiro."""
import json
from pathlib import Path

BASE = 1750000000
conv = [
    {
        "contato_nome": "Maria Souza",
        "contact_id": "5511999887766",
        "operador": "recepcao_1",
        "mensagens": [
            {"ts": BASE, "de": "paciente", "texto": "Oi, boa tarde! Gostaria de saber o valor do botox. Meu telefone é (11) 99988-7766 e meu email maria.souza@gmail.com", "tem_midia": False},
            {"ts": BASE + 900, "de": "clinica", "texto": "Olá Maria! Tudo bem? Aqui é a recepção da clínica. Antes do valor, posso entender sua queixa? A Dra. Ana faz avaliação personalizada. Botox a partir de R$ 1.200,00.", "tem_midia": False},
            {"ts": BASE + 1200, "de": "paciente", "texto": "Achei um pouco caro... e tenho medo de ficar com dor", "tem_midia": False},
            {"ts": BASE + 1500, "de": "clinica", "texto": "Entendo perfeitamente, Maria. O Dr. Ricardo usa técnica suave e a avaliação define o protocolo. Posso agendar para terça às 14:00?", "tem_midia": False},
            {"ts": BASE + 1800, "de": "paciente", "texto": "Pode agendar sim, confirmado!", "tem_midia": False},
        ],
    },
    {
        "contato_nome": "João Pereira",
        "contact_id": "5521988776655",
        "operador": "recepcao_2",
        "mensagens": [
            {"ts": BASE, "de": "paciente", "texto": "Olá, queria saber horário disponível para limpeza de pele", "tem_midia": False},
            {"ts": BASE + 14400, "de": "clinica", "texto": "Boa noite, valor R$ 250", "tem_midia": False},
            {"ts": BASE + 15000, "de": "paciente", "texto": "Vou pensar, obrigado, mas achei salgado", "tem_midia": False},
        ],
    },
    {
        "contato_nome": "Ana Lima",
        "contact_id": "5531977665544",
        "operador": "recepcao_1",
        "mensagens": [
            {"ts": BASE, "de": "paciente", "texto": "tô querendo preenchimento labial, quanto custa?", "tem_midia": True},
            {"ts": BASE + 300, "de": "clinica", "texto": "Oi! A avaliação com a Dra. Ana define o melhor protocolo. Preenchimento a partir de R$ 1.800,00. Quer agendar?", "tem_midia": False},
            {"ts": BASE + 600, "de": "paciente", "texto": "Vou ver com meu marido e te falo", "tem_midia": False},
        ],
    },
]

p = Path("sintetico.jsonl")
with p.open("w") as f:
    for c in conv:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")
print(f"gerado {p} com {len(conv)} conversas")
