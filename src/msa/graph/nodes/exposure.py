def run(state, *, context):
    found = context.agents.exposure.run(
        {
            "graph": state["graph"],
            "macro_parameters": state.get("macro_parameters") or {},
            "positions": state["portfolio_positions"],
            "as_of": state["as_of"],
            "horizon": state.get("horizon", 12),
            "snapshot_id": state["snapshot_id"],
            "base_currency": state.get("base_currency", "RUB"),
            "options": context.options,
        }
    )
    return {
        "positions": found["positions"],
        "reach": found["reach"],
        "prepared": found["prepared"],
        "diagnostics": found["diagnostics"],
        "unreached_exposures": found["unreached_exposures"],
    }
