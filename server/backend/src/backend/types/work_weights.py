"""What each kind of work weighs in the plans VODLoft's tasks report their progress by, in one unit, so that the
steps of one task and the parts of an action made of several tasks count against each other fairly, also while a
step cannot measure itself."""

NUMBER_EPISODE = 0.05
"""Giving one episode its new number: a quick change, all in one write."""
MOVE_FILE = 1.0
"""Moving one downloaded file to its new name."""
REWRITE_FILE = 1.0
"""Writing one file's metadata again."""
LIST_VIDEO = 0.2
"""Listing one video of a new collection, when it is first indexed."""
DEFAULT = 1.0
"""Work whose size is not known in advance."""
