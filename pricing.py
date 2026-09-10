RATES = {
    "claude-sonnet": {"input": 3.00, "cache_read": 0.30, "cache_create": 3.75, "output": 15.00},
    "claude-opus":   {"input": 15.00, "cache_read": 1.50, "cache_create": 18.75, "output": 75.00},
    "claude-haiku":  {"input": 0.80, "cache_read": 0.08, "cache_create": 1.00, "output": 4.00},
    "k3":            {"input": 0.70, "cache_read": 0.10, "cache_create": 0.70, "output": 2.00},
    "gemini":        {"input": 1.25, "cache_read": 0.30, "cache_create": 1.25, "output": 5.00}
}

DEFAULT_RATE = {"input": 2.00, "cache_read": 0.20, "cache_create": 2.50, "output": 10.00}

def get_rates_for_model(model_name: str):
    if not model_name:
        return DEFAULT_RATE
    model_lower = model_name.lower()
    for key, rate in RATES.items():
        if key in model_lower:
            return rate
    return DEFAULT_RATE

def calculate_cost_and_savings(model: str, prompt_tokens: int, cache_read_tokens: int, cache_create_tokens: int, output_tokens: int):
    rates = get_rates_for_model(model)
    
    cost_input = (prompt_tokens / 1_000_000.0) * rates["input"]
    cost_cache_read = (cache_read_tokens / 1_000_000.0) * rates["cache_read"]
    cost_cache_create = (cache_create_tokens / 1_000_000.0) * rates["cache_create"]
    cost_output = (output_tokens / 1_000_000.0) * rates["output"]
    
    actual_cost = cost_input + cost_cache_read + cost_cache_create + cost_output
    
    # Cost if cache read tokens were billed as full input tokens
    non_cached_input_cost = ((prompt_tokens + cache_read_tokens) / 1_000_000.0) * rates["input"] + cost_output
    savings = max(0.0, non_cached_input_cost - actual_cost)
    
    total_input = prompt_tokens + cache_read_tokens
    hit_ratio = (cache_read_tokens / total_input) if total_input > 0 else 0.0
    
    return round(actual_cost, 6), round(savings, 6), round(hit_ratio, 4)
