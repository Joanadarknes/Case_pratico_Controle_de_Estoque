# Controle de Estoque

Aplicação desenvolvida em Python para gerenciar produtos e movimentações de estoque entre os estados disponível, reservado e bloqueado. Possui um painel para consulta dos saldos e das movimentações, com regras de negócio e persistência centralizadas no backend.

## 1. Visão geral da solução

Cada produto possui identificação e quantidades total, disponível, reservada e bloqueada.

A aplicação permite realizar entradas, saídas, reservas, bloqueios, liberações e consultas. Um produto pode possuir múltiplas reservas e bloqueios, cada um com identificador próprio.

Saídas, reservas e bloqueios dependem de saldo disponível suficiente. Operações inválidas não devem alterar o estoque.

A consistência é mantida pela relação:

```text
total = disponível + reservado + bloqueado
```

## 2. Arquitetura e decisões técnicas

Estrutura do projeto:

- `app/main.py`: rotas da API e validações de entrada.
- `app/repository.py`: consultas SQL, persistência e operações de estoque.
- `app/errors.py`: tratamento de erros das regras de negócio.
- `frontend/`: interface em HTML, CSS e JavaScript.
- `tests/`: testes automatizados.

**Tecnologias e decisões:**

- **Python e FastAPI:** implementação do backend e da API.
- **SQLite:** banco relacional escolhido pela simplicidade de execução local.
- **SQL direto:** consultas sem utilização de ORM.
- **Transações:** operações que envolvem leitura, validação e alteração do saldo utilizam `BEGIN IMMEDIATE` na mesma conexão e transação, evitando inconsistências em operações concorrentes.
- **Cálculo de saldo:** a disponibilidade é calculada descontando as reservas e os bloqueios ativos do total.

O `product_id` funciona como chave primária e código editável. Sua alteração atualiza as referências associadas aos compromissos na mesma transação.

## 3. Premissas e limitações

- As quantidades são números inteiros positivos.
- Um produto começa com saldo zero.
- A reserva não representa confirmação de venda ou expedição.
- A exclusão exige confirmação no painel e remove definitivamente o produto e seus registros associados, eliminando o histórico.
- A aplicação não possui autenticação, autorização, auditoria por usuário, paginação ou telemetria.

**Melhorias para produção:**

- Separar o identificador interno do código editável.
- Adotar exclusão lógica para preservar o histórico.
- Implementar autenticação, autorização e auditoria.
- Adicionar monitoramento e métricas.
- Utilizar migrações de banco versionadas.
- Avaliar PostgreSQL em cenários com múltiplas instâncias ou maior volume de operações concorrentes.

## 4. Como executar

**Requisito:** Python 3.10 ou superior.

No terminal, a partir da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

A aplicação disponibiliza o backend e o frontend no mesmo servidor.

- **Painel:** http://127.0.0.1:8000/
- **Documentação da API:** http://127.0.0.1:8000/docs

O banco é criado em `data/inventory.db`. Seu caminho pode ser alterado pela variável de ambiente `INVENTORY_DATABASE`.

Para encerrar, utilize `Ctrl+C`.

## 5. Testes automatizados

Os testes utilizam Pytest e um banco temporário. São **22 casos**, considerando os cenários parametrizados.

A cobertura contempla:

- Entradas, saídas e cálculo de saldos.
- Saldo insuficiente e quantidades inválidas.
- Múltiplas reservas e bloqueios.
- Liberação e prevenção de liberações duplicadas.
- Produtos e compromissos inexistentes.
- Duplicidade e alteração de códigos.
- Exclusão e remoção de registros associados.
- Persistência e migração de banco legado.
- Fechamento de conexões.
- Concorrência entre reservas.

O teste de concorrência verifica se apenas uma operação é aceita quando duas reservas simultâneas ultrapassam o saldo disponível.

Para executar:

```powershell
python -m pytest -v
```

## 6. Uso de inteligência artificial

O ChatGPT foi utilizado pontualmente como apoio durante o desenvolvimento.

### Principais prompts utilizados

- "Qual estrutura de arquitetura e organização de código seria adequada para esse projeto em Python?"
- "Quais cenários de teste são importantes para verificar a consistência das movimentações de estoque?"

**Onde a IA mais ajudou:** na avaliação da organização do projeto e na identificação de cenários relevantes para validar a consistência do estoque.

**Sugestão modificada:** uma sugestão inicial foi impedir a exclusão de produtos com saldo ou compromissos associados. Optei por permitir a exclusão mediante confirmação explícita, considerando a necessidade de corrigir cadastros no escopo do case.

**Limitação identificada:** durante a revisão, identifiquei uma divergência entre a confirmação de exclusão no painel e uma validação antiga do backend. Corrigi o comportamento e acrescentei testes para esse fluxo.

## 7. Visão de engenharia

1. **Consistência transacional:** garante que leitura, validação e movimentação ocorram de forma coordenada.
2. **Regras de negócio explícitas:** evitam operações inválidas e estados inconsistentes.
3. **Identificadores individuais:** permitem consultar e liberar corretamente cada reserva ou bloqueio.
4. **Testes de falha e concorrência:** verificam a integridade do estoque diante de erros e operações simultâneas.
5. **Evolução com rastreabilidade:** permite preservar o histórico e acompanhar as movimentações em uma futura utilização em produção.