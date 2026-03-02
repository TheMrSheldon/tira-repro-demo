import sys
import functools
from contextlib import ContextDecorator
from types import ModuleType
from typing import Optional

from tirex_tracker import register_metadata

class CallStats:
    def __init__(self):
        self.calls = []

    def record(self, args, kwargs, result=None, exception=None):
        self.calls.append({
            "args": args,
            "kwargs": kwargs,
            "result": result,
            "exception": exception,
        })

    def get_stats(self):
        return self.calls


class TrackInvocations(ContextDecorator):
    def __init__(self, target_func):
        self.target_func = target_func
        self.stats = CallStats()

        self.owner: Optional[ModuleType] = None # The owning module or class
        self.attr_name = None
        self.original = None

    def _resolve_owner(self):
        module = sys.modules[self.target_func.__module__]
        
        # abc.def.geh -> ["abc", "def", "geh"]
        parts = self.target_func.__qualname__.split(".")
        
        # Resolve owner (abc.def)
        owner = module
        for part in parts[:-1]:
            owner = getattr(owner, part)
        self.owner = owner
        # Store member name: "geh"
        self.attr_name = parts[-1]

    def __enter__(self):
        self._resolve_owner()

        self.original = getattr(self.owner, self.attr_name)

        # Detect descriptor type
        if isinstance(self.original, classmethod) or isinstance(self.original, staticmethod):
            func = self.original.__func__
        else:
            func = self.original

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                self.stats.record(args, kwargs, result=result)
                return result
            except Exception as e:
                self.stats.record(args, kwargs, exception=e)
                raise

        # Re-wrap appropriately
        if isinstance(self.original, classmethod):
            wrapped = classmethod(wrapper)
        elif isinstance(self.original, staticmethod):
            wrapped = staticmethod(wrapper)
        else:
            wrapped = wrapper

        setattr(self.owner, self.attr_name, wrapped)
        return self.stats

    def __exit__(self, exc_type, exc, tb):
        setattr(self.owner, self.attr_name, self.original)
        return False



class TrackIRDatasets(ContextDecorator):
    
    def __init__(self) -> None:
        import ir_datasets
        self._patch = TrackInvocations(ir_datasets.load)
        self._stats: Optional[CallStats] = None

    def __enter__(self) -> None:
        self._stats = self._patch.__enter__()
    
    def __exit__(self, exc_type, exc, tb):
        assert self._stats is not None
        self._patch.__exit__(exc_type, exc, tb)

        def to_metadata(call: dict[str, str]) -> dict:
            variant = call["args"][0]
            collection, _ = call["args"][0].split("/", 1)
            # TODO: we could also return the following fields when ir_datasets has an API to geth them (with example):
            # - "source": "https://ciir.cs.umass.edu/downloads/Antique/"
            # - "qrels": "https://ciir.cs.umass.edu/downloads/Antique/antique-test.qrel"
            # - "topics": "https://ciir.cs.umass.edu/downloads/Antique/antique-collection.txt"
            return {"ir_datasets": f"https://ir-datasets.com/{collection}#{variant}"}
        
        register_metadata({"data": {"datasets": [to_metadata(call) for call in self._stats.get_stats()]}})
        return False