"""Generic immutable workflow-profile identity; no backend or profile facts."""
from dataclasses import dataclass
@dataclass(frozen=True, slots=True)
class WorkflowProfile:
    name: str
    version: str
    def __post_init__(self):
        if not isinstance(self.name,str) or not self.name or not isinstance(self.version,str) or not self.version:
            raise ValueError('profile name and version are required')
