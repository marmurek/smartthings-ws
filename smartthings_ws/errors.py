"""Errors the appliance layer raises, free of any transport vocabulary.

The API layer decides what these mean over HTTP or WebSocket.
"""


class ApplianceError(Exception):
    """Base class for everything this application raises deliberately"""


class ApplianceNotFound(ApplianceError):
    """No appliance is configured under the requested name"""


class ApplianceUnavailable(ApplianceError):
    """The appliance did not answer"""


class InvalidCommand(ApplianceError):
    """The request cannot be expressed as something the appliance understands"""


class CommandRejected(ApplianceError):
    """The appliance answered the command with an error.

    Laundry and ovens refuse most commands while Remote Control is disabled on
    the appliance's own panel.
    """
