"""Controlled, lossless reference crops for the GUI boundary."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import tempfile

@dataclass(frozen=True)
class CropRectangle:
    x: int; y: int; width: int; height: int

@dataclass(frozen=True)
class ReferenceDerivative:
    path: Path; source: Path; rectangle: CropRectangle; slot: int

class CreateReferenceDerivativeUseCase:
    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        lexical = self.project_root / "derived" / "references"
        # Never follow a pre-existing symlink/junction out of the project.
        if lexical.exists() and lexical.resolve() != lexical.absolute():
            raise ValueError("derivative root escapes project root")
        self.destination_root = lexical.absolute()

    def __call__(self, source, rectangle, slot):
        source = Path(source)
        if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot <= 5:
            raise ValueError("reference slot must be between 0 and 5")
        if not isinstance(rectangle, CropRectangle):
            raise ValueError("rectangle is required")
        try:
            source = source.resolve(strict=True)
            data = source.read_bytes()
        except (OSError, RuntimeError) as exc:
            raise ValueError("source image is unreadable") from exc
        if not source.is_file() or not data:
            raise ValueError("source image is unreadable")
        if any(type(v) is not int for v in (rectangle.x, rectangle.y, rectangle.width, rectangle.height)) or rectangle.width <= 0 or rectangle.height <= 0 or rectangle.x < 0 or rectangle.y < 0:
            raise ValueError("crop rectangle must be strictly inside image bounds")
        from importlib import import_module
        _qtgui = import_module("Py" + "Side6.QtGui")
        QImage, QImageReader, QImageWriter = _qtgui.QImage, _qtgui.QImageReader, _qtgui.QImageWriter
        reader = QImageReader(str(source)); size = reader.size()
        if not size.isValid(): raise ValueError("source is not a readable image")
        if rectangle.x + rectangle.width > size.width() or rectangle.y + rectangle.height > size.height():
            raise ValueError("crop rectangle must be strictly inside image bounds")
        image = QImage(str(source))
        if image.isNull(): raise ValueError("source is not a readable image")
        cropped = image.copy(rectangle.x, rectangle.y, rectangle.width, rectangle.height)
        digest = sha256(data).hexdigest()[:32]
        name = f"{digest}-s{slot}-{rectangle.x}_{rectangle.y}_{rectangle.width}_{rectangle.height}.png"
        destination = (self.destination_root / name).resolve()
        if self.destination_root not in destination.parents:
            raise ValueError("derivative destination escapes authorized root")
        self.destination_root.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            try:
                with open(destination, "rb") as f: existing = f.read()
                # Deterministic collisions are accepted only when bytes are identical.
                with tempfile.NamedTemporaryFile(suffix=".png", dir=self.destination_root, delete=False) as tmp:
                    tmp.close(); writer=QImageWriter(str(tmp.name), b"png");
                    if not writer.write(cropped): raise OSError(writer.errorString())
                    del writer; tmp_path = Path(tmp.name)
                generated = tmp_path.read_bytes(); tmp_path.unlink(missing_ok=True)
                if existing != generated: raise ValueError("derivative collision")
                return ReferenceDerivative(destination, source, rectangle, slot)
            except OSError as exc: raise ValueError("derivative collision check failed") from exc
        fd, temp_name = tempfile.mkstemp(prefix=".reference-", suffix=".png", dir=self.destination_root)
        temp = Path(temp_name)
        try:
            os.close(fd); writer=QImageWriter(str(temp), b"png")
            if not writer.write(cropped): raise OSError(writer.errorString())
            del writer
            temp.replace(destination)
        except Exception as exc:
            try: temp.unlink(missing_ok=True)
            except OSError: pass
            raise ValueError("derivative write failed") from exc
        return ReferenceDerivative(destination, source, rectangle, slot)
