from pathlib import Path
from importlib import import_module

QSettings = import_module("PySide6.QtCore").QSettings
_w = import_module("PySide6.QtWidgets")
QDialog, QLineEdit, QPushButton, QFileDialog, QDialogButtonBox, QFormLayout, QHBoxLayout = (_w.QDialog,_w.QLineEdit,_w.QPushButton,_w.QFileDialog,_w.QDialogButtonBox,_w.QFormLayout,_w.QHBoxLayout)

ORG, APP = "OrquestadorComfyUI", "Orquestador"
INPUT_KEY, OUTPUT_KEY = "defaultImageFolder", "defaultVideoFolder"

def settings(): return QSettings(ORG, APP)
def _saved(key): return str(settings().value(key, "") or "")
def _valid_dir(value):
    p = Path(value).expanduser()
    return p.resolve() if p.exists() and p.is_dir() else None
def resolve_folder(key, *, project_root=None, initial_image=None):
    candidates = [_valid_dir(_saved(key))]
    if key == INPUT_KEY: candidates.append(_valid_dir(Path(initial_image).parent if initial_image else ""))
    if project_root is not None: candidates.append(_valid_dir(project_root))
    candidates.extend([_valid_dir(Path.cwd()), _valid_dir(Path.home())])
    return str(next((p for p in candidates if p), Path.cwd()))

class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Preferences")
        self.image = QLineEdit(_saved(INPUT_KEY)); self.video = QLineEdit(_saved(OUTPUT_KEY))
        form = QFormLayout(self)
        for label, edit in (("Default image folder", self.image), ("Default video folder", self.video)):
            row=QHBoxLayout(); row.addWidget(edit); b=QPushButton("Browse"); b.clicked.connect(lambda _=False,e=edit:self._browse(e)); row.addWidget(b); c=QPushButton("Clear / Use default"); c.clicked.connect(edit.clear); row.addWidget(c); form.addRow(label, row)
        box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); box.accepted.connect(self._save); box.rejected.connect(self.reject); form.addRow(box)
    def _browse(self, edit):
        p=QFileDialog.getExistingDirectory(self, "Choose folder", edit.text() or str(Path.home()))
        if p: edit.setText(str(Path(p).expanduser().resolve()))
    def _save(self):
        s=settings()
        for key, edit in ((INPUT_KEY,self.image),(OUTPUT_KEY,self.video)):
            p=Path(edit.text()).expanduser() if edit.text().strip() else None
            s.setValue(key, str(p.resolve()) if p else "")
        s.sync(); self.accept()
