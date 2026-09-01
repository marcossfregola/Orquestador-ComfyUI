from importlib import import_module
QThread = import_module("PySide6.QtCore").QThread
_widgets = import_module("PySide6.QtWidgets")
QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel,QListWidget,QTextEdit,QFileDialog = (_widgets.QMainWindow,_widgets.QWidget,_widgets.QVBoxLayout,_widgets.QHBoxLayout,_widgets.QLineEdit,_widgets.QPushButton,_widgets.QLabel,_widgets.QListWidget,_widgets.QTextEdit,_widgets.QFileDialog)
from .workers import OperationWorker
class MainWindow(QMainWindow):
    def __init__(self, facade):
        super().__init__(); self.facade=facade; self._thread=None; self._busy=False
        root=QWidget(); self.setCentralWidget(root); lay=QVBoxLayout(root)
        lay.addWidget(QLabel("Project / execution preparation")); row=QHBoxLayout(); self.project=QLineEdit(); self.project.setPlaceholderText("Project id"); row.addWidget(self.project); self.execution=QLineEdit(); self.execution.setPlaceholderText("Execution id"); row.addWidget(self.execution); self.initial=QLineEdit(); self.initial.setPlaceholderText("Initial image path"); row.addWidget(self.initial); self.preflight=QPushButton("Preflight"); row.addWidget(self.preflight); lay.addLayout(row)
        self.references=QListWidget(); self.references.setObjectName("h3ReferenceSlots"); lay.addWidget(QLabel("H3 reference slots (six paths, comma-separated)")); self.reference_input=QLineEdit(); self.reference_input.setObjectName("h3ReferenceInput"); lay.addWidget(self.reference_input); lay.addWidget(self.references)
        self.prompts=QTextEdit(); self.prompts.setPlaceholderText("One prompt per chunk (bounded by prepared execution)"); self.prompts.setObjectName("chunkPrompts"); lay.addWidget(self.prompts)
        self.parameters=QLabel("Supported parameters: provided by profile"); self.parameters.setObjectName("supportedParameters"); lay.addWidget(self.parameters)
        acts=QHBoxLayout(); self.start=QPushButton("Start chain"); self.resume=QPushButton("Resume / Recover"); self.retry=QPushButton("Retry"); self.cancel=QPushButton("Cancel pending"); self.assemble=QPushButton("Assemble MP4"); [acts.addWidget(x) for x in (self.start,self.resume,self.retry,self.cancel,self.assemble)]; lay.addLayout(acts)
        self.status=QLabel("Ready"); lay.addWidget(self.status); self.chunks=QListWidget(); lay.addWidget(self.chunks); self.log=QTextEdit(); self.log.setReadOnly(True); lay.addWidget(self.log)
        self.preflight.clicked.connect(self._prepare); self.start.clicked.connect(self._start_chain); self.resume.clicked.connect(lambda:self._run(lambda:self.facade.resume_execution(self.project.text().strip(), self.execution.text().strip()))); self.retry.clicked.connect(lambda:self._run(lambda:self.facade.retry_execution(self.project.text().strip(), self.execution.text().strip()))); self.cancel.clicked.connect(lambda:self._run(lambda:self.facade.cancel_pending(self.project.text().strip(), self.execution.text().strip()))); self.assemble.clicked.connect(self._assemble)
        self.refresh()
    def refresh(self): self.render(self.facade.refresh())
    def _inputs(self):
        prompts=[x.strip() for x in self.prompts.toPlainText().splitlines() if x.strip()]
        refs=[x.strip() for x in self.reference_input.text().split(',') if x.strip()] or [self.references.item(i).text() for i in range(self.references.count())]
        return dict(project_id=self.project.text(), execution_id=self.execution.text(), initial_image=self.initial.text(), prompts=prompts, references=refs)
    def _prepare(self): self._run(lambda:self.facade.prepare(**self._inputs()))
    def _start_chain(self): self._run(lambda:self.facade.start_chain(**self._inputs()))
    def render(self,s):
        self.status.setText(s.state + (": "+"; ".join(s.errors) if s.errors else "")); self.chunks.clear(); [self.chunks.addItem(f"Chunk {c.order}: {c.state}" + (f" [{c.attempt_ref}]" if c.attempt_ref else "") + (f" error={c.error}" if c.error else "") + (f" output={c.output}" if c.output else "") + (f" transition={c.transition}" if c.transition else "")) for c in s.chunks]; self.references.clear(); self.references.addItems(list(s.reference_slots)); self.parameters.setText("Supported parameters: " + (", ".join(s.supported_parameters) if s.supported_parameters else "none reported")); self.cancel.setEnabled(s.can_cancel and not self._busy); self.retry.setEnabled(s.can_retry and not self._busy)
    def _run(self,op):
        if self._busy: return
        self._busy=True; self._set_enabled(False); self._thread=QThread(); self._worker=OperationWorker(op); self._worker.moveToThread(self._thread); self._thread.started.connect(self._worker.run); self._worker.succeeded.connect(lambda r:self._done(r)); self._worker.failed.connect(lambda e:self.log.append(e)); self._worker.finished.connect(self._thread.quit); self._thread.finished.connect(self._cleanup); self._thread.start()
    def _done(self,r): self.render(r.snapshot); self.log.append(r.message or "Operation completed")
    def _cleanup(self):
        thread=self._thread; worker=self._worker; self._busy=False; self._set_enabled(True); self._thread=None
        if worker is not None: worker.deleteLater()
        if thread is not None: thread.deleteLater()
    def _set_enabled(self,v): [x.setEnabled(v) for x in (self.preflight,self.start,self.resume,self.retry,self.cancel,self.assemble)]
    def _assemble(self):
        p,_=QFileDialog.getSaveFileName(self,"Destination MP4",filter="MP4 (*.mp4)");
        if p: self._run(lambda:self.facade.assemble(p))
    def closeEvent(self,e):
        if self._busy: e.ignore(); self.status.setText("Operation active; wait for completion")
        else: e.accept()
