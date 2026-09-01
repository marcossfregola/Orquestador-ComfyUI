from importlib import import_module
_qt = import_module("PySide6.QtCore")
QObject, Signal, Slot = _qt.QObject, _qt.Signal, _qt.Slot
class OperationWorker(QObject):
    succeeded=Signal(object); failed=Signal(str); finished=Signal()
    def __init__(self, operation, *args, **kwargs): super().__init__(); self.operation=operation; self.args=args; self.kwargs=kwargs
    @Slot()
    def run(self):
        try: self.succeeded.emit(self.operation(*self.args,**self.kwargs))
        except Exception as exc: self.failed.emit(str(exc))
        finally: self.finished.emit()
