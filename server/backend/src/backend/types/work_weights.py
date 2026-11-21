"""What each kind of work weighs in the plans VODLoft's tasks report their progress by, in one unit, so that the
steps of one task and the parts of an action made of several tasks count against each other fairly, also while a
step cannot measure itself."""

NUMBER_EPISODE = 1.0
"""Giving one episode its new number, all in one write: about as long as moving one file."""
MOVE_FILE = 1.0
"""Moving one downloaded file to its new name."""
REWRITE_FILE = 18.0
"""Writing one file's metadata again: the file is written anew, so it takes far longer than moving it."""
LIST_VIDEO = 0.2
"""Listing one video of a new collection, when it is first indexed."""
DEFAULT = 1.0
"""Work whose size is not known in advance."""
