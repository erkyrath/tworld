import datetime

def now():
    """Utility function: return "now" as an aware UTC datetime object.
    """
    return datetime.datetime.now(datetime.timezone.utc)
