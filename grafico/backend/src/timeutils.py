def time_str_to_minutes(time_str: str) -> float:
    hours, minutes, seconds = (int(part) for part in time_str.split(":"))
    return hours * 60 + minutes + seconds / 60


def minutes_to_time_str(total_minutes: float) -> str:
    total_seconds = round(total_minutes * 60)
    total_seconds %= 24 * 60 * 60
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
