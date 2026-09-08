from importlib import import_module
QThread = import_module("PySide6.QtCore").QThread
_widgets = import_module("PySide6.QtWidgets")
QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel,QListWidget,QTextEdit,QFileDialog,QComboBox,QSpinBox,QDoubleSpinBox = (_widgets.QMainWindow,_widgets.QWidget,_widgets.QVBoxLayout,_widgets.QHBoxLayout,_widgets.QLineEdit,_widgets.QPushButton,_widgets.QLabel,_widgets.QListWidget,_widgets.QTextEdit,_widgets.QFileDialog,_widgets.QComboBox,_widgets.QSpinBox,_widgets.QDoubleSpinBox)
from .workers import OperationWorker
from ..domain.config import DEFAULT_MEGAPIXELS, DEFAULT_LENGTH, DEFAULT_STEPS, DEFAULT_FPS
class MainWindow(QMainWindow):
    def __init__(self, facade):
        super().__init__(); self.facade=facade; self._thread=None; self._busy=False; self._prepared_key=None; self._auth_can_start=False; self._auth_busy=False
        root=QWidget(); self.setCentralWidget(root); lay=QVBoxLayout(root)
        lay.addWidget(QLabel("Project / execution preparation")); row=QHBoxLayout(); self.project=QLineEdit(); self.project.setPlaceholderText("Project id"); row.addWidget(self.project); self.execution=QLineEdit(); self.execution.setPlaceholderText("Execution id"); row.addWidget(self.execution); row.addWidget(QLabel("Initial image:")); self.initial=QLineEdit(); self.initial.setPlaceholderText("empty — choose an initial image"); row.addWidget(self.initial); self.initial_button=QPushButton("Choose initial…"); row.addWidget(self.initial_button); self.preflight=QPushButton("Preflight"); self.prepare=QPushButton("Prepare"); row.addWidget(self.preflight); row.addWidget(self.prepare); lay.addLayout(row)
        self.reference_labels=[]
        lay.addWidget(QLabel("H3 reference slots (six deterministic paths)"))
        self.references=QListWidget(); self.references.setObjectName("h3ReferenceSlots"); self.references.setVisible(False); lay.addWidget(self.references)
        for i in range(6):
            label=QLabel(f"Reference {i+1}: empty — choose a file")
            label.setObjectName(f"referenceLabel{i+1}"); self.reference_labels.append(label); lay.addWidget(label)
        self.reference_buttons=[]
        for i in range(6):
            b=QPushButton(f"Choose reference {i+1}…"); b.clicked.connect(lambda _=False, index=i: self._choose_reference(index)); self.reference_buttons.append(b); lay.addWidget(b)
        controls=QHBoxLayout(); self.chunk_count=QComboBox(); self.chunk_count.addItems(["2","3"]); controls.addWidget(QLabel("Chunks")); controls.addWidget(self.chunk_count)
        self.megapixels=QDoubleSpinBox(); self.megapixels.setRange(0.01,1000); self.megapixels.setDecimals(2); self.megapixels.setSingleStep(0.01); self.megapixels.setValue(DEFAULT_MEGAPIXELS); controls.addWidget(QLabel("Megapixels")); controls.addWidget(self.megapixels)
        self.length=QSpinBox(); self.length.setRange(1,100000); self.length.setSingleStep(DEFAULT_FPS); self.length.setValue(DEFAULT_LENGTH); controls.addWidget(QLabel("Length (frames; step = FPS)")); controls.addWidget(self.length)
        self.steps=QSpinBox(); self.steps.setRange(1,100000); self.steps.setValue(DEFAULT_STEPS); controls.addWidget(QLabel("Steps")); controls.addWidget(self.steps)
        self.fps=QSpinBox(); self.fps.setRange(1,1000); self.fps.setValue(DEFAULT_FPS); controls.addWidget(QLabel("FPS")); controls.addWidget(self.fps); self.fps.valueChanged.connect(self.length.setSingleStep); lay.addLayout(controls)
        self.prompts=[]
        for i in range(3):
            edit=QLineEdit(); edit.setObjectName(f"chunkPrompt{i+1}"); edit.setPlaceholderText(f"Prompt for chunk {i+1}"); self.prompts.append(edit); lay.addWidget(edit)
        self.parameters=QLabel("Supported parameters: provided by profile"); self.parameters.setObjectName("supportedParameters"); lay.addWidget(self.parameters)
        acts=QHBoxLayout(); self.start=QPushButton("Start chain"); self.resume=QPushButton("Resume / Recover"); self.retry=QPushButton("Retry"); self.cancel=QPushButton("Cancel pending"); self.assemble=QPushButton("Assemble MP4"); [acts.addWidget(x) for x in (self.start,self.resume,self.retry,self.cancel,self.assemble)]; lay.addLayout(acts)
        self.status=QLabel("Ready"); lay.addWidget(self.status); self.chunks=QListWidget(); lay.addWidget(self.chunks); self.log=QTextEdit(); self.log.setReadOnly(True); lay.addWidget(self.log)
        self.initial_confirmation=QLabel("Initial image: empty — choose a file"); lay.insertWidget(1,self.initial_confirmation)
        self.initial_button.clicked.connect(self._choose_initial); self.chunk_count.currentTextChanged.connect(lambda _ : (self._invalidate(), self._sync_prompt_visibility())); [w.textChanged.connect(self._invalidate) for w in (self.project,self.execution,self.initial)]; self.initial.textChanged.connect(lambda p: self.initial_confirmation.setText(f"Initial image: {p}" if p else "Initial image: empty — choose a file")); [w.textChanged.connect(self._invalidate) for w in self.prompts]; [w.valueChanged.connect(self._invalidate) for w in (self.megapixels,self.length,self.steps,self.fps)]; self.references.itemChanged.connect(lambda item: (self._update_reference_labels(), self._invalidate())); self.preflight.clicked.connect(self._preflight); self.prepare.clicked.connect(self._prepare); self.start.clicked.connect(self._start_chain); self.resume.clicked.connect(lambda:self._run(lambda:self.facade.resume_execution(self.project.text().strip(), self.execution.text().strip()))); self.retry.clicked.connect(lambda:self._run(lambda:self.facade.retry_execution(self.project.text().strip(), self.execution.text().strip()))); self.cancel.clicked.connect(lambda:self._run(lambda:self.facade.cancel_pending(self.project.text().strip(), self.execution.text().strip()))); self.assemble.clicked.connect(self._assemble); self._sync_prompt_visibility(); self.start.setEnabled(False)
        self.refresh()
    def refresh(self): self.render(self.facade.refresh())
    def _inputs(self):
        prompts=[self.prompts[i].text() for i in range(int(self.chunk_count.currentText()))]
        refs=[self.references.item(i).text().strip() for i in range(min(6,self.references.count())) if self.references.item(i) and self.references.item(i).text().strip()]
        return dict(project_id=self.project.text(), execution_id=self.execution.text(), initial_image=self.initial.text(), prompts=prompts, references=refs, chunk_count=int(self.chunk_count.currentText()), megapixels=self.megapixels.value(), length=self.length.value(), steps=self.steps.value(), fps=self.fps.value())
    def _choose_initial(self):
        p,_=QFileDialog.getOpenFileName(self,"Initial image");
        if p: self.initial.setText(p)
    def _choose_reference(self,index):
        p,_=QFileDialog.getOpenFileName(self,f"Reference slot {index+1}");
        if p:
            while self.references.count() <= index: self.references.addItem("")
            self.references.item(index).setText(p)
            self._update_reference_labels()
    def _update_reference_labels(self):
        for i,label in enumerate(self.reference_labels):
            value=self.references.item(i).text() if self.references.item(i) else ""
            label.setText(f"Reference {i+1}: {value}" if value else f"Reference {i+1}: empty — choose a file")
    def _sync_prompt_visibility(self):
        count=int(self.chunk_count.currentText())
        for i,e in enumerate(self.prompts): e.setVisible(i<count); e.setEnabled(i<count)
    def _preflight(self): self._run(lambda:self.facade.preflight(**self._inputs()), "preflight")
    def _prepare(self): self._run(lambda:self.facade.prepare(**self._inputs()), "prepare")
    def _start_chain(self): self._run(lambda:self.facade.start_chain(**self._inputs()), "start")
    def _form_key(self):
        x=self._inputs(); return tuple((k, tuple(v) if isinstance(v,list) else v) for k,v in x.items())
    def _update_start(self): self.start.setEnabled(bool(self._auth_can_start and not self._auth_busy and not self._busy and self._prepared_key is not None and self._form_key()==self._prepared_key))
    def render(self,s):
        self._auth_can_start = bool(s.can_start); self._auth_busy = bool(s.busy)
        self.status.setText(s.state + (": "+"; ".join(s.errors) if s.errors else "")); self.chunks.clear(); [self.chunks.addItem(f"Chunk {c.order}: {c.state}" + (f" [{c.attempt_ref}]" if c.attempt_ref else "") + (f" error={c.error}" if c.error else "") + (f" output={c.output}" if c.output else "") + (f" transition={c.transition}" if c.transition else "")) for c in s.chunks];
        if s.reference_slots:
            self.references.clear(); self.references.addItems(list(s.reference_slots))
        self._update_reference_labels()
        self.parameters.setText("Supported parameters: " + (", ".join(s.supported_parameters) if s.supported_parameters else "none reported")); self.cancel.setEnabled(s.can_cancel and not self._busy); self.retry.setEnabled(s.can_retry and not self._busy); self._update_start()
    def _run(self,op,kind="other"):
        if self._busy: return
        self._operation_kind=kind; self._busy=True; self._set_enabled(False); self._thread=QThread(); self._worker=OperationWorker(op); self._worker.moveToThread(self._thread); self._thread.started.connect(self._worker.run); self._worker.succeeded.connect(lambda r:self._done(r)); self._worker.failed.connect(lambda e:self.log.append(e)); self._worker.finished.connect(self._thread.quit); self._thread.finished.connect(self._cleanup); self._thread.start()
    def _done(self,r):
        if r.success and self._operation_kind=="prepare": self._prepared_key=self._form_key()
        self.render(r.snapshot)
        self.log.append(r.message or "Operation completed")
    def _cleanup(self):
        thread=self._thread; worker=self._worker; self._busy=False; self._set_enabled(True); self._update_start(); self._thread=None
        if worker is not None: worker.deleteLater()
        if thread is not None: thread.deleteLater()
    def _invalidate(self,*_): self._prepared_key=None; self._update_start()
    def _set_enabled(self,v): [x.setEnabled(v) for x in (self.preflight,self.prepare,self.start,self.resume,self.retry,self.cancel,self.assemble)]
    def _assemble(self):
        p,_=QFileDialog.getSaveFileName(self,"Destination MP4",filter="MP4 (*.mp4)");
        if p: self._run(lambda:self.facade.assemble(p))
    def closeEvent(self,e):
        if self._busy: e.ignore(); self.status.setText("Operation active; wait for completion")
        else: e.accept()
