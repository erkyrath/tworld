
class MessageException(Exception):
    """An exception that generally means "Fail, and display this text back
    to the user." This is used in various contexts in both tweb and tworld.
    """
    pass

class ErrorMessageException(MessageException):
    """An exception that means "Fail, and display this text back to the
    user as an error message."
    """
    pass

class SymbolError(LookupError):
    """Failure to find a symbol, when executing script code.
    """
    pass
