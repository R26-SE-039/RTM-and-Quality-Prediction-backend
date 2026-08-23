def safe_pct(covered: float, total: float) -> float:
    """Ratio as a 0-100 percentage; a metric with zero possible units (e.g.
    a file with no branches) is treated as fully covered, matching the
    convention coverage.py itself uses.
    """
    if total <= 0:
        return 100.0
    return round((covered / total) * 100, 2)


def overall_from(statement_pct: float, branch_pct: float) -> float:
    """'Overall coverage' is defined uniformly across both ecosystems as the
    average of statement and branch coverage, rather than trusting each
    tool's own differently-defined blended metric.
    """
    return round((statement_pct + branch_pct) / 2, 2)
