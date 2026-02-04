O ficheiro Excel deve ter **2 folhas** com as colunas abaixo.

Esta alocação de missionários a valências assume que um missionário fica **sempre** alocado à mesma valência.

## 1) Folha "Missionários" (obrigatória)

Colunas:

- `Nome`
- `Valência Fixa` (opcional): se quisermos predefinir uma valência em algum missionários (por exemplo, definir quem vai para o Teatro)
- `Rank1`, `Rank2`, `Rank3`, `Rank4`, ... (todas as colunas que começam por `Rank`): ordem de preferência de cada missionário. Para receberem os dados dos vossos missionários neste formato tabular a sugestão é criarem um Google Forms.

Exemplo:

| Nome | Valência Fixa | Rank1 | Rank2 | Rank3 | Rank4 |
|------|----------------|-------|-------|-------|-------|
| João Silva | Teatro | Porta a Porta | Creche | Crianças | Idosos |
| Maria Santos |  | Crianças | Creche | Moral | Teatro |
| Pedro Oliveira |  | Fundação | Crianças | Porta a Porta | Idosos |

## 2) Folha "Valências" (obrigatória)

Colunas:

- `Valência`
- `Nº Missionários`: Número de missionários alocados a esta valência

Exemplo:

| Valência | Nº Missionários |
|---------|------------|
| Porta a Porta | 12 |
| Crianças | 12 |
| Portadores de deficiência | 3 |
| Idosos | 10 |

O valor total da coluna `Nº Missionários` tem de ser igual ao número de missionários na folha `Missionários`.


## Exemplo
