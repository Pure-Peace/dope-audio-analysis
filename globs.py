from config import DEJAVU_CONFIG
from dejavu import Dejavu
from objects import TaskFile


directory_scanning: bool = False
inqueue_files: dict[TaskFile] = {}
pending_files: dict[TaskFile] = {}
# create a Dejavu instance
djv: Dejavu = Dejavu(DEJAVU_CONFIG)
