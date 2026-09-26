def collect_branch_results(current, update):
    """Position branches accumulate into one round; None opens a new round empty."""
    if update is None:
        return []
    return (current or []) + list(update)


def merge_extensions(current, update):
    """Each agent owns its namespace; parallel agents write to different keys."""
    if update is None:
        return {}
    merged = dict(current or {})
    for agent_id, value in update.items():
        merged[agent_id] = value
    return merged
