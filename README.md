# Estrutura do input.xlsx

O ficheiro `input.xlsx` deve ter **3 folhas** (a terceira é opcional) com as colunas abaixo.

## 1) Folha "Missionários" (obrigatória)

Colunas:

- `Nome`
- `Rank1`, `Rank2`, `Rank3`, `Rank4`, ... (todas as colunas que começam por `Rank`)

Exemplo real (do ficheiro atual):

| Nome | Rank1 | Rank2 | Rank3 | Rank4 |
|------|-------|-------|-------|-------|
| João Silva | Porta a Porta | SAD | Crianças | Idosos |
| Maria Santos | Crianças | SAD | Moral | Teatro |
| Pedro Oliveira | Portadores de deficiência | Crianças | Porta a Porta | Idosos |

## 2) Folha "Valências" (obrigatória)

Colunas:

- `Valência`
- `Nº Missionários`

Exemplo real (do ficheiro atual):

| Valência | Nº Missionários |
|---------|------------|
| Porta a Porta | 12 |
| Crianças | 12 |
| Portadores de deficiência | 3 |
| Idosos | 10 |

## 3) Folha "Alocações Fixas" (opcional)

Colunas:

- `Nome`
- `Valência`

Exemplo real (do ficheiro atual):

| Nome | Valência |
|------|----------|
| João Silva | Teatro |
| Maria Santos | Idosos |
| Pedro Oliveira | Crianças |

## Nota rápida sobre nomes

Os nomes das folhas e colunas podem estar com ou sem acentos/maiúsculas, desde que correspondam a estes títulos.
