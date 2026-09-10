from importlib import import_module
from pathlib import Path
QThread = import_module("PySide6.QtCore").QThread
_widgets = import_module("PySide6.QtWidgets")
QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel,QListWidget,QTextEdit,QFileDialog,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox = (_widgets.QMainWindow,_widgets.QWidget,_widgets.QVBoxLayout,_widgets.QHBoxLayout,_widgets.QLineEdit,_widgets.QPushButton,_widgets.QLabel,_widgets.QListWidget,_widgets.QTextEdit,_widgets.QFileDialog,_widgets.QComboBox,_widgets.QSpinBox,_widgets.QDoubleSpinBox,_widgets.QCheckBox)
_gui=import_module("PySide6.QtGui"); QPixmap = _gui.QPixmap; QCursor = _gui.QCursor
QImage=_gui.QImage
_core=import_module("PySide6.QtCore"); QRect=_core.QRect; Qt=_core.Qt; Slot=_core.Slot
QDialog,QDialogButtonBox,QScrollArea,QRubberBand,QFrame = _widgets.QDialog,_widgets.QDialogButtonBox,_widgets.QScrollArea,_widgets.QRubberBand,_widgets.QFrame
QSizePolicy = _widgets.QSizePolicy
from .workers import OperationWorker
from ..domain.config import DEFAULT_MEGAPIXELS, DEFAULT_LENGTH, DEFAULT_STEPS, DEFAULT_FPS, DEFAULT_REF_IMAGE_SIZE, DEFAULT_ALSO_REF_FIRST_FRAME, SUPPORTED_REF_IMAGE_SIZES
from ..application.create_reference_derivative import CreateReferenceDerivativeUseCase, CropRectangle
from .preferences import PreferencesDialog, resolve_folder, INPUT_KEY, OUTPUT_KEY

class _CropDialog(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent); self.setWindowTitle("Crop reference")
        self.image=QImage(path); self.label=QLabel(); self.label.setAlignment(Qt.AlignCenter); self.pixmap=QPixmap(path).scaled(640,480,Qt.KeepAspectRatio,Qt.SmoothTransformation); self.label.setPixmap(self.pixmap); self.label.setCursor(QCursor(Qt.CrossCursor)); self.label.setToolTip("Drag a rectangle, then Confirm")
        self.label.mousePressEvent=self._press; self.label.mouseMoveEvent=self._move; self.label.mouseReleaseEvent=self._release
        self.rubber=QRubberBand(QRubberBand.Rectangle,self.label)
        self.handles=[]
        for corner in range(4):
            h=QFrame(self.label); h.setFixedSize(8,8); h.setStyleSheet("background:#ffffff;border:1px solid #202020;"); h.hide(); self.handles.append(h)
        self.start=self.end=None; self.moving=False; self.move_offset=None; self.ratio=QComboBox(); self.ratio.addItems(["Manual","1:1","4:3","3:4","16:9","9:16"]); self.ratio.currentIndexChanged.connect(self._ratio_changed)
        box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); self.ok=box.button(QDialogButtonBox.Ok); self.ok.setEnabled(False); box.accepted.connect(self._confirm); box.rejected.connect(self.reject)
        l=QVBoxLayout(self); l.addWidget(self.ratio); l.addWidget(self.label); l.addWidget(box)
    def _ratio_value(self):
        return None if self.ratio.currentText()=="Manual" else tuple(map(float,self.ratio.currentText().split(":")))
    def _ratio_changed(self):
        if self.start is not None: self._move_point(self.end)
        self._update_handles()
    def _clamp_point(self,p):
        pm=self.pixmap; ox=(self.label.width()-pm.width())//2; oy=(self.label.height()-pm.height())//2
        return type(p)(max(ox,min(ox+pm.width(),p.x())), max(oy,min(oy+pm.height(),p.y())))
    def _move_point(self,p):
        self.end=self._clamp_point(p); a=self._clamp_point(self.start); b=self.end; dx,dy=b.x()-a.x(),b.y()-a.y(); rw=self._ratio_value()
        if rw and dx and dy:
            aw,ah=abs(dx),abs(dy); target=rw[0]/rw[1]
            if aw/ah > target: aw=round(ah*target)
            else: ah=round(aw/target)
            pm=self.pixmap; ox=(self.label.width()-pm.width())//2; oy=(self.label.height()-pm.height())//2
            maxw=(ox+pm.width()-a.x()) if dx>0 else (a.x()-ox); maxh=(oy+pm.height()-a.y()) if dy>0 else (a.y()-oy)
            scale=min(1.0, maxw/max(1,aw), maxh/max(1,ah)); aw=max(1,round(aw*scale)); ah=max(1,round(ah*scale))
            self.end=type(b)(a.x()+(aw if dx>0 else -aw),a.y()+(ah if dy>0 else -ah)); self.end=self._clamp_point(self.end)
        self.rubber.setGeometry(QRect(a,self.end).normalized()); self.ok.setEnabled(self.rubber.width()>0 and self.rubber.height()>0); self._update_handles()
    def _update_handles(self):
        r=self.rubber.geometry().normalized()
        valid=r.width() >= 8 and r.height() >= 8 and self.ok.isEnabled()
        pts=((r.left(),r.top()),(r.right(),r.top()),(r.left(),r.bottom()),(r.right(),r.bottom()))
        for h,(x,y) in zip(self.handles,pts):
            h.setGeometry(x-4,y-4,8,8); h.setVisible(valid)
    def _handle_at(self,p):
        r=self.rubber.geometry().normalized()
        if not (self.ok.isEnabled() and r.width() >= 8 and r.height() >= 8): return -1
        for i,(x,y) in enumerate(((r.left(),r.top()),(r.right(),r.top()),(r.left(),r.bottom()),(r.right(),r.bottom()))):
            if QRect(x-7,y-7,14,14).contains(p): return i
        return -1
    def _resize(self,p):
        r=self.rubber.geometry().normalized(); p=self._clamp_point(p); i=self.resize_handle
        anchor=(r.right(),r.bottom()) if i==0 else (r.left(),r.bottom()) if i==1 else (r.right(),r.top()) if i==2 else (r.left(),r.top())
        ax,ay=anchor; minsz=12; rw=self._ratio_value(); x,y=p.x(),p.y()
        if i in (0,2): x=min(x,ax-minsz)
        else: x=max(x,ax+minsz)
        if i in (0,1): y=min(y,ay-minsz)
        else: y=max(y,ay+minsz)
        if rw:
            target=rw[0]/rw[1]; w,h=abs(x-ax),abs(y-ay)
            if w/h > target: w=round(h*target)
            else: h=round(w/target)
            w=max(minsz,w); h=max(minsz,h)
            # fit anchored rectangle to image bounds
            pm=self.pixmap; ox=(self.label.width()-pm.width())//2; oy=(self.label.height()-pm.height())//2
            w=min(w, pm.width()); h=min(h,pm.height());
            if w/h > target: w=round(h*target)
            else: h=round(w/target)
            x=ax-w if i in (0,2) else ax+w; y=ay-h if i in (0,1) else ay+h
        nr=QRect(type(p)(x,y),type(p)(ax,ay)).normalized(); pm=self.pixmap; ox=(self.label.width()-pm.width())//2; oy=(self.label.height()-pm.height())//2
        if nr.left()<ox: nr.moveLeft(ox)
        if nr.top()<oy: nr.moveTop(oy)
        if nr.right()>ox+pm.width(): nr.moveRight(ox+pm.width())
        if nr.bottom()>oy+pm.height(): nr.moveBottom(oy+pm.height())
        self.start=nr.topLeft(); self.end=nr.bottomRight(); self.rubber.setGeometry(nr); self._update_handles()
    def _press(self,e):
        p=self._clamp_point(e.position().toPoint()); current=QRect(self.start,self.end).normalized() if self.start is not None and self.end is not None else QRect()
        hit=self._handle_at(p)
        if hit >= 0: self.resize_handle=hit; self.moving=False; self.label.setCursor(QCursor(Qt.SizeFDiagCursor if hit in (0,3) else Qt.SizeBDiagCursor)); return
        if current.isValid() and current.contains(p): self.moving=True; self.move_offset=p-current.topLeft(); self.label.setCursor(QCursor(Qt.SizeAllCursor)); return
        self.moving=False; self.resize_handle=-1; self.start=p; self.end=p; self.rubber.setGeometry(QRect(p,p)); self.rubber.show(); self.ok.setEnabled(False); self._update_handles()
    def _move(self,e):
        p=self._clamp_point(e.position().toPoint())
        if self.moving:
            r=QRect(self.start,self.end).normalized(); pm=self.pixmap; ox=(self.label.width()-pm.width())//2; oy=(self.label.height()-pm.height())//2; top=p-self.move_offset; top.setX(max(ox,min(top.x(),ox+pm.width()-r.width()))); top.setY(max(oy,min(top.y(),oy+pm.height()-r.height()))); r.moveTopLeft(top); self.start=r.topLeft(); self.end=r.bottomRight(); self.rubber.setGeometry(r); return
        if getattr(self,'resize_handle',-1) >= 0: self._resize(p); return
        if self.start is not None and self.rubber.geometry().width()>0:
            hit=self._handle_at(p)
            if hit >= 0: self.label.setCursor(QCursor(Qt.SizeFDiagCursor if hit in (0,3) else Qt.SizeBDiagCursor))
            elif self.rubber.geometry().contains(p): self.label.setCursor(QCursor(Qt.SizeAllCursor))
            else: self.label.setCursor(QCursor(Qt.CrossCursor))
        if self.start is not None and e.buttons(): self._move_point(p)
    def _release(self,e):
        self._move(e); self.moving=False; self.resize_handle=-1; self.move_offset=None; self.label.setCursor(QCursor(Qt.CrossCursor)); self._update_handles()
    def _confirm(self):
        if self.rectangle(): self.accept()
    def rectangle(self):
        if not self.start or not self.end: return None
        a,b=self.start,self.end; x,y=min(a.x(),b.x()),min(a.y(),b.y()); w,h=abs(a.x()-b.x()),abs(a.y()-b.y());
        pm=self.pixmap; ox=(self.label.width()-pm.width())//2; oy=(self.label.height()-pm.height())//2
        x=max(0,min(pm.width(),x-ox)); y=max(0,min(pm.height(),y-oy)); w=max(0,min(pm.width()-x,w)); h=max(0,min(pm.height()-y,h)); sx=self.image.width()/pm.width(); sy=self.image.height()/pm.height()
        return CropRectangle(round(x*sx),round(y*sy),round(w*sx),round(h*sy)) if w and h else None
class MainWindow(QMainWindow):
    def __init__(self, facade, project_root=None):
        super().__init__(); self.facade=facade; self.project_root=Path(project_root) if project_root is not None else Path.cwd(); self._thread=None; self._busy=False; self._prepared_key=None; self._prepared_selection=None; self._auth_can_start=False; self._auth_busy=False
        root=QWidget(); self.setCentralWidget(root); lay=QVBoxLayout(root)
        lay.addWidget(QLabel("Project / execution preparation")); row=QHBoxLayout(); self.project=QLineEdit(); self.project.setPlaceholderText("Project id"); row.addWidget(self.project); self.execution=QLineEdit(); self.execution.setPlaceholderText("Execution id"); row.addWidget(self.execution); self.preflight=QPushButton("Preflight"); self.prepare=QPushButton("Prepare"); row.addWidget(self.preflight); row.addWidget(self.prepare); lay.addLayout(row)
        initial_row=QHBoxLayout(); initial_row.addWidget(QLabel("Initial image path:")); self.initial=QLineEdit(); self.initial.setPlaceholderText("empty — choose an initial image"); self.initial.setMinimumWidth(300); initial_row.addWidget(self.initial, 1); self.initial_button=QPushButton("Choose initial…"); initial_row.addWidget(self.initial_button); lay.addLayout(initial_row)
        self.reference_labels=[]; lay.addWidget(QLabel("Visual references (effective order; maximum 6)"))
        self.references=QListWidget(); self.references.setObjectName("h3ReferenceSlots"); self.references.setVisible(False); lay.addWidget(self.references)
        self.reference_buttons=[]
        for i in range(6):
            label=QLabel(f"Reference {i+1}: empty"); label.setObjectName(f"referenceLabel{i+1}"); label.setMinimumHeight(72); label.setMaximumHeight(96); label.setMaximumWidth(620); label.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)); label.setWordWrap(False); self.reference_labels.append(label)
            row=QHBoxLayout(); row.addWidget(label); add=QPushButton("Add/Replace"); add.clicked.connect(lambda _=False,index=i:self._choose_reference(index)); rem=QPushButton("Remove"); rem.clicked.connect(lambda _=False,index=i:self.remove_reference(index)); crop=QPushButton("Crop"); crop.clicked.connect(lambda _=False,index=i:self.crop_reference(index)); [row.addWidget(x) for x in (add,rem,crop)]; lay.addLayout(row); self.reference_buttons.append(add)
        controls=QHBoxLayout(); self.chunk_count=QComboBox(); self.chunk_count.addItems(["2","3"]); controls.addWidget(QLabel("Chunks")); controls.addWidget(self.chunk_count)
        self.megapixels=QDoubleSpinBox(); self.megapixels.setRange(0.01,1000); self.megapixels.setDecimals(2); self.megapixels.setSingleStep(0.01); self.megapixels.setValue(DEFAULT_MEGAPIXELS); controls.addWidget(QLabel("Megapixels")); controls.addWidget(self.megapixels)
        self.length=QSpinBox(); self.length.setRange(1,100000); self.length.setSingleStep(DEFAULT_FPS); self.length.setValue(DEFAULT_LENGTH); controls.addWidget(QLabel("Length (frames; step = FPS)")); controls.addWidget(self.length)
        self.steps=QSpinBox(); self.steps.setRange(1,100000); self.steps.setValue(DEFAULT_STEPS); controls.addWidget(QLabel("Steps")); controls.addWidget(self.steps)
        self.fps=QSpinBox(); self.fps.setRange(1,1000); self.fps.setValue(DEFAULT_FPS); controls.addWidget(QLabel("FPS")); controls.addWidget(self.fps); self.fps.valueChanged.connect(self.length.setSingleStep); lay.addLayout(controls)
        h3_controls=QHBoxLayout(); h3_controls.addWidget(QLabel("Reference image size")); self.ref_image_size=QComboBox(); self.ref_image_size.addItems(sorted(SUPPORTED_REF_IMAGE_SIZES)); self.ref_image_size.setCurrentText(DEFAULT_REF_IMAGE_SIZE); h3_controls.addWidget(self.ref_image_size); self.also_ref_first_frame=QCheckBox("Also reference first frame"); self.also_ref_first_frame.setChecked(DEFAULT_ALSO_REF_FIRST_FRAME); h3_controls.addWidget(self.also_ref_first_frame); lay.addLayout(h3_controls)
        self.prompts=[]
        for i in range(3):
            lay.addWidget(QLabel(f"Prompt — Chunk {i+1}")); edit=QLineEdit(); edit.setObjectName(f"chunkPrompt{i+1}"); edit.setPlaceholderText(f"Prompt — Chunk {i+1}"); self.prompts.append(edit); lay.addWidget(edit)
        self.parameters=QLabel("Supported parameters: provided by profile"); self.parameters.setObjectName("supportedParameters"); lay.addWidget(self.parameters)
        acts=QHBoxLayout(); self.preferences=QPushButton("Preferences…"); self.preferences.clicked.connect(self._preferences); self.start=QPushButton("Start chain"); self.resume=QPushButton("Resume / Recover"); self.retry=QPushButton("Retry"); self.cancel=QPushButton("Cancel pending"); self.assemble=QPushButton("Assemble MP4"); [acts.addWidget(x) for x in (self.preferences,self.start,self.resume,self.retry,self.cancel,self.assemble)]; lay.addLayout(acts)
        self.status=QLabel("Ready"); lay.addWidget(self.status); self.chunks=QListWidget(); lay.addWidget(self.chunks); self.log=QTextEdit(); self.log.setReadOnly(True); lay.addWidget(self.log)
        self.initial_confirmation=QLabel("Initial image: empty — choose a file"); self.initial_confirmation.setObjectName("initialImagePreview"); lay.insertWidget(1,self.initial_confirmation)
        self.initial_button.clicked.connect(self._choose_initial); self.chunk_count.currentTextChanged.connect(lambda _ : (self._invalidate(), self._sync_prompt_visibility())); [w.textChanged.connect(self._invalidate) for w in (self.project,self.execution,self.initial)]; self.initial.textChanged.connect(self._update_initial_preview); [w.textChanged.connect(self._invalidate) for w in self.prompts]; [w.valueChanged.connect(self._invalidate) for w in (self.megapixels,self.length,self.steps,self.fps)]; self.ref_image_size.currentTextChanged.connect(self._invalidate); self.also_ref_first_frame.toggled.connect(self._invalidate); self.references.itemChanged.connect(lambda item: (self._update_reference_labels(), self._invalidate())); self.preflight.clicked.connect(self._preflight); self.prepare.clicked.connect(self._prepare); self.start.clicked.connect(self._start_chain); self.resume.clicked.connect(lambda:self._run(lambda:self.facade.resume_execution(self.project.text().strip(), self.execution.text().strip()))); self.retry.clicked.connect(lambda:self._run(lambda:self.facade.retry_execution(self.project.text().strip(), self.execution.text().strip()))); self.cancel.clicked.connect(lambda:self._run(lambda:self.facade.cancel_pending(self.project.text().strip(), self.execution.text().strip()))); self.assemble.clicked.connect(self._assemble); self._sync_prompt_visibility(); self.start.setEnabled(False)
        self.refresh()
    def refresh(self): self.render(self.facade.refresh())
    def _inputs(self):
        prompts=[self.prompts[i].text() for i in range(int(self.chunk_count.currentText()))]
        refs=[self.references.item(i).text().strip() for i in range(min(6,self.references.count())) if self.references.item(i) and self.references.item(i).text().strip()]
        return dict(project_id=self.project.text(), execution_id=self.execution.text(), initial_image=self.initial.text(), prompts=prompts, references=refs, chunk_count=int(self.chunk_count.currentText()), megapixels=self.megapixels.value(), length=self.length.value(), steps=self.steps.value(), fps=self.fps.value(), ref_image_size=self.ref_image_size.currentText(), also_ref_first_frame=self.also_ref_first_frame.isChecked())
    def _choose_initial(self):
        p,_=QFileDialog.getOpenFileName(self,"Initial image",resolve_folder(INPUT_KEY, project_root=self.project_root, initial_image=self.initial.text()));
        if p: self.initial.setText(p)
    def _update_initial_preview(self, path=""):
        path = path or self.initial.text()
        if path and QPixmap(path).isNull() is False:
            self.initial_confirmation.setText(f"Initial image: {Path(path).name}")
            self.initial_confirmation.setPixmap(QPixmap(path).scaled(180,120,Qt.KeepAspectRatio,Qt.SmoothTransformation))
            self.initial_confirmation.setToolTip(path)
        else: self.initial_confirmation.setText(f"Initial image: {path}" if path else "Initial image: empty — choose a file")
    def _choose_reference(self,index):
        p,_=QFileDialog.getOpenFileName(self,f"Reference slot {index+1}",resolve_folder(INPUT_KEY, project_root=self.project_root, initial_image=self.initial.text()));
        if p:
            while self.references.count() <= index: self.references.addItem("")
            self.references.item(index).setText(p)
            self._update_reference_labels()
    def crop_reference(self,index):
        item=self.references.item(index)
        if not item: return False
        dlg=_CropDialog(item.text(),self)
        if dlg.exec() == QDialog.Accepted and dlg.rectangle():
            try:
                out=CreateReferenceDerivativeUseCase(self.project_root)(item.text(),dlg.rectangle(),index).path
            except ValueError as exc: self.log.append(str(exc)); return False
            item.setText(str(out)); self._update_reference_labels(); self._invalidate(); return True
        return False
    def add_reference(self, path):
        if self.references.count() >= 6: return False
        self.references.addItem(str(path)); self._update_reference_labels(); self._invalidate(); return True
    def replace_reference(self, index, path):
        if not 0 <= index < self.references.count(): return False
        self.references.item(index).setText(str(path)); self._update_reference_labels(); self._invalidate(); return True
    def remove_reference(self, index):
        if not 0 <= index < self.references.count(): return False
        self.references.takeItem(index); self._update_reference_labels(); self._invalidate(); return True
    def _update_reference_labels(self):
        for i,label in enumerate(self.reference_labels):
            value=self.references.item(i).text() if self.references.item(i) else ""
            label.clear(); label.setText(f"Reference {i+1}: {value}" if value else f"Reference {i+1}: empty — choose a file")
            label.setToolTip(value)
            if value:
                pm=QPixmap(value)
                if not pm.isNull(): label.setPixmap(pm.scaled(120,72,Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def _sync_prompt_visibility(self):
        count=int(self.chunk_count.currentText())
        for i,e in enumerate(self.prompts): e.setVisible(i<count); e.setEnabled(i<count)
    def _preflight(self): self._run(lambda:self.facade.preflight(**self._inputs()), "preflight")
    def _prepare(self): self._run(lambda:self.facade.prepare(**self._inputs()), "prepare")
    def _start_chain(self):
        project_id, execution_id = self._prepared_selection or (self.project.text().strip(), self.execution.text().strip())
        self._run(lambda:self.facade.start_chain(project_id, execution_id), "start")
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
        self._operation_kind=kind; self._busy=True; self._set_enabled(False)
        self._thread=QThread(); self._worker=OperationWorker(op); self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self._on_worker_succeeded, Qt.QueuedConnection)
        self._worker.failed.connect(self._on_worker_failed, Qt.QueuedConnection)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._cleanup)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()
    @Slot(object)
    def _on_worker_succeeded(self,r):
        self._done(r)
    @Slot(str)
    def _on_worker_failed(self,error):
        self.log.append(error)
    @Slot(object)
    def _done(self,r):
        if r.success and self._operation_kind=="prepare":
            self._prepared_key=self._form_key()
            self._prepared_selection=(r.snapshot.project_id or self.project.text().strip(), r.snapshot.execution_id or self.execution.text().strip())
        self.render(r.snapshot)
        self.log.append(r.message or "Operation completed")
    @Slot()
    def _cleanup(self):
        self._busy=False; self._set_enabled(True); self._update_start(); self._worker=None; self._thread=None
    def _invalidate(self,*_): self._prepared_key=None; self._prepared_selection=None; self._update_start()
    def _set_enabled(self,v): [x.setEnabled(v) for x in (self.preflight,self.prepare,self.start,self.resume,self.retry,self.cancel,self.assemble)]
    def _assemble(self):
        p,_=QFileDialog.getSaveFileName(self,"Destination MP4",resolve_folder(OUTPUT_KEY, project_root=self.project_root),filter="MP4 (*.mp4)");
        if p:
            project_id = self.project.text().strip()
            execution_id = self.execution.text().strip()
            self._run(lambda:self.facade.assemble(project_id, execution_id, p))
    def _preferences(self):
        PreferencesDialog(self).exec()
    def closeEvent(self,e):
        if self._busy: e.ignore(); self.status.setText("Operation active; wait for completion")
        else: e.accept()
