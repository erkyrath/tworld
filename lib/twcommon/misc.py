import datetime

# The maximum length of an editable description, such as a player desc
# or editstr line.
MAX_DESCLINE_LENGTH = 256

def now():
    """Utility function: return "now" as an aware UTC datetime object.
    """
    return datetime.datetime.now(datetime.timezone.utc)
