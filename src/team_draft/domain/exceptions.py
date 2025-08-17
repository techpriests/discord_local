"""
Domain Exceptions

Business rule violations and domain-specific errors.
"""


class DraftError(Exception):
    """Base exception for all draft-related errors"""
    pass


class InvalidDraftStateError(DraftError):
    """Raised when attempting an operation in an invalid draft state"""
    pass


class PlayerNotFoundError(DraftError):
    """Raised when trying to operate on a player that doesn't exist"""
    pass


class DraftFullError(DraftError):
    """Raised when trying to add a player to a full draft"""
    pass


class PlayerAlreadyExistsError(DraftError):
    """Raised when trying to add a player that's already in the draft"""
    pass


class InvalidPhaseTransitionError(DraftError):
    """Raised when attempting an invalid phase transition"""
    pass


class TeamFullError(DraftError):
    """Raised when trying to add a player to a full team"""
    pass


class InvalidTeamNumberError(DraftError):
    """Raised when using an invalid team number"""
    pass


class ServantNotAvailableError(DraftError):
    """Raised when trying to select an unavailable servant"""
    pass


class ServantAlreadySelectedError(DraftError):
    """Raised when trying to select a servant that's already taken"""
    pass


class InvalidCaptainError(DraftError):
    """Raised when trying to perform captain operations with invalid captain"""
    pass


class CaptainVotingError(DraftError):
    """Raised when captain voting operations fail"""
    pass


class TeamSelectionError(DraftError):
    """Raised when team selection operations fail"""
    pass


class ValidationError(DraftError):
    """Raised when validation fails"""
    pass
