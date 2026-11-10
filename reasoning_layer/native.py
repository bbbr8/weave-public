"""Local reference execution; remote transport is absent from this distribution."""
from .core import reference_execute

class ReferenceBackend:
    name='reference'
    def run_many(self,items,folder):
        return {task['id']:reference_execute(task,program) for task,program in items}

class MacBackend:
    """Compatibility rejection for callers holding an old remote-backend name."""
    name='remote_unavailable'
    def run_many(self,items,folder):
        raise RuntimeError('Remote execution is unavailable; existing requests remain pinned. Use ReferenceBackend locally.')
    def recover(self,folder):
        raise RuntimeError('Remote recovery is unavailable in the local-only distribution')
