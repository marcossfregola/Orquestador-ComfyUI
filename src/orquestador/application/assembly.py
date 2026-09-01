"""Application boundary for assembling completed chunk artifacts."""
from dataclasses import dataclass
from pathlib import Path
from ..adapters.assembly import AssemblyError

@dataclass(frozen=True)
class AssemblyResult:
    success: bool
    output: Path|None = None
    reason: str = ''

class AssembleExecutionUseCase:
    def __init__(self, assembler, trusted_root): self.assembler,self.trusted_root=assembler,Path(trusted_root).resolve()
    def execute(self, chunk_outputs, destination, *, reencode=False):
        try:
            dst=Path(destination)
            paths=[]
            for value in chunk_outputs:
                p=(self.trusted_root/value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
                p.relative_to(self.trusted_root); paths.append(p)
            out=(self.trusted_root/dst).resolve() if not dst.is_absolute() else dst.resolve(); out.relative_to(self.trusted_root)
            result=self.assembler.assemble(paths,out,reencode=reencode)
            return AssemblyResult(True,result)
        except Exception as exc: return AssemblyResult(False,reason=str(exc))
