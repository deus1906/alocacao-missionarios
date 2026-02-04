"""Configuration defaults for the allocation model."""

DEFAULT_WEIGHTS = [100, 80, 60, 45, 30, 15]
UNRANKED_PENALTY = -1000

MISSIONARIOS_SHEETS = ["Missionarios"]
VALENCIAS_SHEETS = ["Valencias"]

OUTPUT_SHEET = "Alocações"

OUTPUT_FALLBACK_COLUMNS = {
    "person": "Nome",
    "valencia": "Valencia",
    "rank": "Rank",
}
