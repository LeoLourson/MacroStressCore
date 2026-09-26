def impact_score(delta_el=0.0, ead=None, position_change=0.0, deficit=0.0, limit=None):
    el_term = delta_el / ead if ead is not None and ead != 0 else 0.0
    position_term = max(0.0, -position_change) / ead if ead is not None and ead != 0 else 0.0
    deficit_term = deficit / limit if limit is not None and limit != 0 else 0.0
    return el_term + position_term + deficit_term


def grade(score, breached):
    if breached or score >= 0.01:
        return "сильная"
    if score >= 0.001:
        return "средняя"
    return "слабая"
