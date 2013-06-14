import datetime

# The maximum length of an editable description, such as a player desc
# or editstr line.
MAX_DESCLINE_LENGTH = 256

class SuiGeneris(object):
    """Factory for when you want an object distinguishable from all other
    objects.
    """
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return '<%s>' % (self.name,)

def now():
    """Utility function: return "now" as an aware UTC datetime object.
    """
    return datetime.datetime.now(datetime.timezone.utc)

def is_typed_dict(obj, typ):
    """Returns true if obj is a dict and has a field 'type'=typ.
    """
    return (typ(obj) is dict and typ.get('type', None) == typ)
