
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

# The following are only used during script code execution, and could
# be moved to two.* somewhere.

class SymbolError(LookupError):
    """Failure to find a symbol, when executing script code.
    """
    pass

class ExecRunawayException(Exception):
    """Raised when a script seems to run on for too long, or too deep.
    """
    pass

class ExecSandboxException(Exception):
    """Raised when a script tries to access Python functionality that
    we don't permit.
    """
    pass

class ExecutionException(Exception):
    """Internal code-flow exceptions in the script interpreter.
    """
    pass

class ReturnException(ExecutionException):
    def __init__(self, returnvalue):
        self.returnvalue = returnvalue

class LoopBodyException(ExecutionException):
    """Base class for Break and Continue.
    """
    statement = '???'

class BreakException(LoopBodyException):
    statement = 'break'

class ContinueException(LoopBodyException):
    statement = 'continue'
