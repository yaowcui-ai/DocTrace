import pytest


def test_rate_limit_opens_circuit_instead_of_spending_more_requests():
    from app.experiment_budget import ProviderBudget
    budget = ProviderBudget(max_attempts=4, min_interval=30)
    assert budget.reserve(now=0) == 0
    budget.observe(429)
    with pytest.raises(RuntimeError, match='rate_limited'):
        budget.reserve(now=600)


def test_pacing_and_budget_are_explicit():
    from app.experiment_budget import ProviderBudget
    budget = ProviderBudget(max_attempts=2, min_interval=30)
    assert budget.reserve(now=1) == 0
    budget.observe(200)
    assert budget.reserve(now=11) == 20
    with pytest.raises(RuntimeError, match='budget_exhausted'):
        budget.reserve(now=100)
