from pricing import calculate_cost_and_savings, get_rates_for_model

def test_claude_sonnet_pricing():
    # 1M input ($3.00), 1M cache read ($0.30), 1M output ($15.00)
    cost, savings, hit_ratio = calculate_cost_and_savings(
        model="claude-sonnet-5",
        prompt_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_create_tokens=0,
        output_tokens=1_000_000
    )
    # Cost = $3.00 (in) + $0.30 (cache read) + $15.00 (out) = $18.30
    # Without cache, 2M input would be $6.00 + $15.00 = $21.00. Savings = $2.70
    assert round(cost, 2) == 18.30
    assert round(savings, 2) == 2.70
    assert round(hit_ratio, 2) == 0.50

def test_kimi_pricing():
    cost, savings, hit_ratio = calculate_cost_and_savings(
        model="k3-256k",
        prompt_tokens=1_000_000,
        cache_read_tokens=0,
        cache_create_tokens=0,
        output_tokens=1_000_000
    )
    # k3 rates: in 0.70, out 2.00 -> 2.70
    assert round(cost, 2) == 2.70
    assert round(savings, 2) == 0.00
    assert hit_ratio == 0.0
