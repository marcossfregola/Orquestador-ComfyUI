from importlib import import_module
from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import uuid4
from pathlib import Path
QThread = import_module("PySide6.QtCore").QThread
_widgets = import_module("PySide6.QtWidgets")
QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel,QListWidget,QTextEdit,QFileDialog,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QTabWidget,QGridLayout = (_widgets.QMainWindow,_widgets.QWidget,_widgets.QVBoxLayout,_widgets.QHBoxLayout,_widgets.QLineEdit,_widgets.QPushButton,_widgets.QLabel,_widgets.QListWidget,_widgets.QTextEdit,_widgets.QFileDialog,_widgets.QComboBox,_widgets.QSpinBox,_widgets.QDoubleSpinBox,_widgets.QCheckBox,_widgets.QTabWidget,_widgets.QGridLayout)
_gui=import_module("PySide6.QtGui"); QPixmap = _gui.QPixmap; QCursor = _gui.QCursor
QImage=_gui.QImage
_core=import_module("PySide6.QtCore"); QRect=_core.QRect; Qt=_core.Qt; Slot=_core.Slot; QTimer=_core.QTimer
QDialog,QDialogButtonBox,QScrollArea,QRubberBand,QFrame,QGroupBox,QFormLayout = _widgets.QDialog,_widgets.QDialogButtonBox,_widgets.QScrollArea,_widgets.QRubberBand,_widgets.QFrame,_widgets.QGroupBox,_widgets.QFormLayout
QSizePolicy = _widgets.QSizePolicy
# Compact reference preview bounding box, shared by the label geometry and
# the rendered pixmap so the effective preview cannot silently shrink.
REFERENCE_PREVIEW_WIDTH, REFERENCE_PREVIEW_HEIGHT = 220, 150
class _ChunkSpinBox(QSpinBox):
    def setCurrentText(self, text): self.setValue(int(text))

@dataclass
class ChunkDraft:
    draft_id: str = field(default_factory=lambda: uuid4().hex)
    prompt: str = ""
    overrides: dict = field(default_factory=dict)

@dataclass(frozen=True)
class PreparedIdentity:
    form_key: tuple
    selection: tuple
from .workers import OperationWorker
from ..domain.config import DEFAULT_MEGAPIXELS, DEFAULT_LENGTH, DEFAULT_STEPS, DEFAULT_FPS, DEFAULT_REF_IMAGE_SIZE, DEFAULT_ALSO_REF_FIRST_FRAME, SUPPORTED_REF_IMAGE_SIZES
from ..application.create_reference_derivative import CreateReferenceDerivativeUseCase, CropRectangle
from ..application.gui_facade import OperationResult
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
        self.start=self.end=None; self.moving=False; self.move_offset=None; self.resize_anchor=None; self.resize_handle=-1; self.ratio=QComboBox(); self.ratio.addItems(["Manual","1:1","4:3","3:4","16:9","9:16"]); self.ratio.currentIndexChanged.connect(self._ratio_changed)
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
        p=self._clamp_point(p); i=self.resize_handle
        if self.resize_anchor is None: return
        ax,ay=self.resize_anchor; minsz=12; sx=-1 if i in (0,2) else 1; sy=-1 if i in (0,1) else 1
        pm=self.pixmap; ox=(self.label.width()-pm.width())//2; oy=(self.label.height()-pm.height())//2
        max_w=max(minsz, (ax-ox) if sx<0 else (ox+pm.width()-ax)); max_h=max(minsz, (ay-oy) if sy<0 else (oy+pm.height()-ay))
        w=max(minsz, (ax-p.x()) if sx<0 else (p.x()-ax)); h=max(minsz, (ay-p.y()) if sy<0 else (p.y()-ay)); rw=self._ratio_value()
        if rw:
            ratio=rw[0]/rw[1]; scale=min(w/ratio,h,max_w/ratio,max_h); w=max(minsz,round(scale*ratio)); h=max(minsz,round(scale))
            # Integer construction above preserves the requested ratio within
            # one pixel while the single scale is already bounded by both axes.
        w=min(w,max_w); h=min(h,max_h)
        nr=QRect(type(p)(ax+sx*w,ay+sy*h),type(p)(ax,ay)).normalized()
        self.start=nr.topLeft(); self.end=nr.bottomRight(); self.rubber.setGeometry(nr); self._update_handles()
    def _press(self,e):
        p=self._clamp_point(e.position().toPoint()); current=QRect(self.start,self.end).normalized() if self.start is not None and self.end is not None else QRect()
        hit=self._handle_at(p)
        if hit >= 0:
            self.resize_handle=hit; r=QRect(self.start,self.end).normalized(); self.resize_anchor=((r.right(),r.bottom()) if hit==0 else (r.left(),r.bottom()) if hit==1 else (r.right(),r.top()) if hit==2 else (r.left(),r.top())); self.moving=False; self.label.setCursor(QCursor(Qt.SizeFDiagCursor if hit in (0,3) else Qt.SizeBDiagCursor)); return
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
        self._move(e); self.moving=False; self.resize_handle=-1; self.resize_anchor=None; self.move_offset=None; self.label.setCursor(QCursor(Qt.CrossCursor)); self._update_handles()
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
        super().__init__(); self.facade=facade; self._last_snapshot=None; self.project_root=Path(project_root) if project_root is not None else Path.cwd(); self._thread=None; self._worker=None; self._retired_threads=[]; self._retired_workers=[]; self._closing=False; self._busy=False; self._prepared_key=None; self._prepared_selection=None; self._prepared_identity=None; self._auth_can_start=False; self._auth_busy=False
        root=QWidget(); self.setCentralWidget(root); root_lay=QVBoxLayout(root)
        self.tabs=QTabWidget(); self.tabs.setObjectName("mainTabs"); root_lay.addWidget(self.tabs)
        main_page=QWidget(); self.tabs.addTab(main_page,"Principal"); lay=QVBoxLayout(main_page)
        references_page=QWidget(); self.tabs.addTab(references_page,"Referencias")
        references_page_lay=QVBoxLayout(references_page)
        references_page_lay.addWidget(QLabel("Visual references (effective order; maximum 6)"))
        self.reference_scroll_area=QScrollArea(); self.reference_scroll_area.setObjectName("referenceScrollArea"); self.reference_scroll_area.setWidgetResizable(True); self.reference_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        reference_host=QWidget(); self.reference_grid=QGridLayout(reference_host); self.reference_grid.setContentsMargins(4,4,4,4); self.reference_grid.setHorizontalSpacing(12); self.reference_grid.setVerticalSpacing(12); self.reference_grid.setAlignment(Qt.AlignTop); self.reference_scroll_area.setWidget(reference_host); references_page_lay.addWidget(self.reference_scroll_area,1)
        lay.addWidget(QLabel("Project / execution preparation")); row=QHBoxLayout(); self.project=QLineEdit(); self.project.setPlaceholderText("Project id"); row.addWidget(self.project); self.execution=QLineEdit(); self.execution.setPlaceholderText("Execution id"); row.addWidget(self.execution); self.preflight=QPushButton("Preflight"); self.prepare=QPushButton("Prepare"); row.addWidget(self.preflight); row.addWidget(self.prepare); lay.addLayout(row)
        initial_row=QHBoxLayout(); initial_row.addWidget(QLabel("Initial image path:")); self.initial=QLineEdit(); self.initial.setPlaceholderText("empty — choose an initial image"); self.initial.setMinimumWidth(300); initial_row.addWidget(self.initial, 1); self.initial_button=QPushButton("Choose initial…"); initial_row.addWidget(self.initial_button); lay.addLayout(initial_row)
        self.reference_labels=[]
        self.references=QListWidget(); self.references.setObjectName("h3ReferenceSlots"); self.references.setVisible(False); lay.addWidget(self.references)
        self.reference_buttons=[]
        for i in range(6):
            label=QLabel(f"Reference {i+1}: empty"); label.setObjectName(f"referenceLabel{i+1}"); label.setMinimumSize(REFERENCE_PREVIEW_WIDTH,REFERENCE_PREVIEW_HEIGHT); label.setMaximumSize(REFERENCE_PREVIEW_WIDTH,REFERENCE_PREVIEW_HEIGHT); label.setAlignment(Qt.AlignCenter); label.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)); label.setWordWrap(False); self.reference_labels.append(label)
            card=QWidget(); card.setObjectName(f"referenceCard{i+1}"); card.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)); card_lay=QVBoxLayout(card); card_lay.setContentsMargins(6,6,6,6); card_lay.setSpacing(6); card_lay.addWidget(label); add=QPushButton("Add/Replace"); add.clicked.connect(lambda _=False,index=i:self._choose_reference(index)); rem=QPushButton("Remove"); rem.clicked.connect(lambda _=False,index=i:self.remove_reference(index)); crop=QPushButton("Crop"); crop.clicked.connect(lambda _=False,index=i:self.crop_reference(index)); button_row=QHBoxLayout(); button_row.setSpacing(6); [button_row.addWidget(x) for x in (add,rem,crop)]; card_lay.addLayout(button_row); self.reference_grid.addWidget(card,i//2,i%2,Qt.AlignTop); self.reference_grid.setColumnStretch(i%2,1); self.reference_buttons.append(add)
        self.chunk_count=_ChunkSpinBox(); self.chunk_count.setRange(2, 2147483647); self.chunk_count.setValue(2)
        self.add_chunk_button=QPushButton("Add chunk"); self.remove_chunk_button=QPushButton("Remove chunk"); self.move_up_button=QPushButton("Move Up"); self.move_down_button=QPushButton("Move Down"); self.duplicate_button=QPushButton("Duplicate")
        self.megapixels=QDoubleSpinBox(); self.megapixels.setRange(0.01,1000); self.megapixels.setDecimals(2); self.megapixels.setSingleStep(0.01); self.megapixels.setValue(DEFAULT_MEGAPIXELS)
        self.length=QSpinBox(); self.length.setRange(1,100000); self.length.setSingleStep(DEFAULT_FPS); self.length.setValue(DEFAULT_LENGTH)
        self.steps=QSpinBox(); self.steps.setRange(1,100000); self.steps.setValue(DEFAULT_STEPS)
        self.fps=QSpinBox(); self.fps.setRange(1,1000); self.fps.setValue(DEFAULT_FPS); self.fps.valueChanged.connect(self.length.setSingleStep)
        chunks_page=QWidget(); self.tabs.addTab(chunks_page,"Chunks"); chunks_lay=QVBoxLayout(chunks_page)
        chunks_lay.addWidget(QLabel("General configuration"))
        controls=QHBoxLayout(); controls.addWidget(QLabel("Chunks")); controls.addWidget(self.chunk_count)
        [controls.addWidget(x) for x in (self.add_chunk_button,self.remove_chunk_button,self.move_up_button,self.move_down_button,self.duplicate_button)]
        for label, x in (("Megapixels",self.megapixels),("Length / Frames",self.length),("Steps",self.steps),("FPS",self.fps)):
            cell=QWidget(); cl=QVBoxLayout(cell); cl.setContentsMargins(2,0,2,0); cl.addWidget(QLabel(label)); cl.addWidget(x); controls.addWidget(cell)
        chunks_lay.addLayout(controls); h3_controls=QHBoxLayout(); h3_controls.addWidget(QLabel("Reference image size")); self.ref_image_size=QComboBox(); self.ref_image_size.addItems(sorted(SUPPORTED_REF_IMAGE_SIZES)); self.ref_image_size.setCurrentText(DEFAULT_REF_IMAGE_SIZE); h3_controls.addWidget(self.ref_image_size); self.also_ref_first_frame=QCheckBox("Also reference first frame"); self.also_ref_first_frame.setChecked(DEFAULT_ALSO_REF_FIRST_FRAME); h3_controls.addWidget(self.also_ref_first_frame); chunks_lay.addLayout(h3_controls)
        self.prompts=[]; self._sequence_ids=[]; self._drafts=[ChunkDraft(),ChunkDraft()]; self.chunk_tabs=QTabWidget(); self.chunk_tabs.setObjectName("chunkTabs"); self.chunk_tabs.setTabsClosable(False); self.chunk_tabs.setUsesScrollButtons(True); chunks_lay.addWidget(self.chunk_tabs,1)
        self.parameters=QLabel("Supported parameters: provided by profile"); self.parameters.setObjectName("supportedParameters"); chunks_lay.addWidget(self.parameters)
        override_row=QHBoxLayout(); override_row.addWidget(QLabel("Chunk override (approved H3 only)")); self.override_key=QComboBox(); self.override_key.setObjectName("chunkOverrideKey"); self.override_key.addItems(["prompt","megapixels","length","steps","fps","ref_image_size","also_ref_first_frame"]); override_row.addWidget(self.override_key); self.override_value=QLineEdit(); self.override_value.setObjectName("chunkOverrideValue"); override_row.addWidget(self.override_value); self.set_override_button=QPushButton("Set override"); self.clear_override_button=QPushButton("Restore inherited"); override_row.addWidget(self.set_override_button); override_row.addWidget(self.clear_override_button); chunks_lay.addLayout(override_row)
        self.provenance=QLabel("Effective values: select a chunk"); self.provenance.setObjectName("chunkProvenance"); self.provenance.setWordWrap(True); chunks_lay.addWidget(self.provenance)
        acts=QHBoxLayout(); self.preferences=QPushButton("Preferences…"); self.preferences.clicked.connect(self._preferences); self.start=QPushButton("Start chain"); self.resume=QPushButton("Resume / Recover"); self.retry=QPushButton("Retry"); self.cancel=QPushButton("Cancel pending"); self.assemble=QPushButton("Assemble MP4"); [acts.addWidget(x) for x in (self.preferences,self.start,self.resume,self.retry,self.cancel,self.assemble)]; lay.addLayout(acts)
        self.status=QLabel("Ready"); self.status.setObjectName("durableStatus"); lay.addWidget(self.status); self.paths=QLabel("Chunks/intermediates/results: not loaded"); self.paths.setObjectName("resultPaths"); self.paths.setWordWrap(True); lay.addWidget(self.paths); self.chunks=QListWidget(); self.chunks.setObjectName("chunkResults"); lay.addWidget(self.chunks); self.log=QTextEdit(); self.log.setReadOnly(True); lay.addWidget(self.log)
        self.initial_confirmation=QLabel("Initial image: empty — choose a file"); self.initial_confirmation.setObjectName("initialImagePreview"); lay.insertWidget(1,self.initial_confirmation)
        self.initial_button.clicked.connect(self._choose_initial); self.chunk_count.valueChanged.connect(lambda _ : (self._invalidate(), self._sync_prompt_visibility())); self.add_chunk_button.clicked.connect(self._add_chunk_control); self.remove_chunk_button.clicked.connect(self._remove_chunk_control); [w.textChanged.connect(self._invalidate) for w in (self.project,self.execution,self.initial)]; self.initial.textChanged.connect(self._update_initial_preview); [w.textChanged.connect(self._invalidate) for w in self.prompts]; [w.valueChanged.connect(self._general_value_changed) for w in (self.megapixels,self.length,self.steps,self.fps)]; self.ref_image_size.currentTextChanged.connect(self._general_value_changed); self.also_ref_first_frame.toggled.connect(self._general_value_changed); self.references.itemChanged.connect(lambda item: (self._update_reference_labels(), self._invalidate())); self.preflight.clicked.connect(self._preflight); self.prepare.clicked.connect(self._prepare); self.start.clicked.connect(self._start_chain); self.resume.clicked.connect(self._resume_or_recover); self.retry.clicked.connect(lambda:self._run(lambda:self.facade.retry_execution(self.project.text().strip(), self.execution.text().strip()))); self.cancel.clicked.connect(lambda:self._run(lambda:self.facade.cancel_pending(self.project.text().strip(), self.execution.text().strip()))); self.assemble.clicked.connect(self._assemble); self._sync_prompt_visibility(); self.start.setEnabled(False); self._update_resume_recover()
        self.move_up_button.clicked.connect(lambda:self._move_sequence(-1)); self.move_down_button.clicked.connect(lambda:self._move_sequence(1)); self.duplicate_button.clicked.connect(self._duplicate_sequence); self.chunk_tabs.currentChanged.connect(lambda i: (self._show_provenance(), self._update_sequence_controls()))
        self.set_override_button.clicked.connect(self._set_override); self.clear_override_button.clicked.connect(lambda _=False: self._clear_override()); self.chunks.currentRowChanged.connect(lambda i: self.chunk_tabs.setCurrentIndex(i))
        self._prompt_timer=QTimer(self); self._prompt_timer.setSingleShot(True); self._prompt_timer.setInterval(400); self._prompt_timer.timeout.connect(self._flush_prompt); self._prompt_dirty=None; self._pending_action=None; self._continuation=None
        self.refresh()

    def _persist_prompt_edit(self):
        editor=self.sender(); i=self.prompts.index(editor) if editor in self.prompts else -1
        if i < 0: return
        self._drafts[i].prompt=editor.toPlainText(); self._invalidate()
        cid=getattr(editor,"_chunk_id",None)
        if cid is not None and self._sequence_ids:
            self._prompt_dirty=(cid,editor.toPlainText()); self._prompt_timer.start()
    def _flush_prompt(self):
        if self._prompt_dirty and not self._busy:
            cid,text=self._prompt_dirty; self._prompt_dirty=None; self._sequence_op("update_prompt",cid,prompt=text)
    def _flush_prompt_before_action(self, action=None):
        if self._prompt_timer.isActive():
            self._prompt_timer.stop()
        if self._prompt_dirty:
            dirty=self._prompt_dirty
            self._prompt_dirty=None
            cid,text=dirty
            p,e=self.project.text().strip(),self.execution.text().strip()
            if p and e:
                self._pending_action=action
                self._run(lambda:self.facade.edit_sequence(p,e,operation="update_prompt",chunk_id=cid,prompt=text), "prompt_flush")
                return True
        return False

    def _selected_chunk_id(self):
        i=self.chunk_tabs.currentIndex()
        return self._sequence_ids[i] if 0 <= i < len(self._sequence_ids) else None
    def _sequence_op(self, operation, chunk_id=None, **kwargs):
        p,e=self.project.text().strip(),self.execution.text().strip()
        if not p or not e: return
        self._invalidate(); self._run(lambda:self.facade.edit_sequence(p,e,operation=operation,chunk_id=chunk_id,**kwargs), "sequence_edit")
    def _add_chunk_control(self):
        if self._sequence_ids: self._add_sequence()
        else:
            self._drafts.append(ChunkDraft()); self.chunk_count.setValue(len(self._drafts)); self._sync_prompt_visibility(); self.chunk_tabs.setCurrentIndex(len(self._drafts)-1)
    def _remove_chunk_control(self):
        if self._sequence_ids: self._remove_sequence()
        else:
            i=self.chunk_tabs.currentIndex()
            if len(self._drafts)>2 and 0 <= i < len(self._drafts):
                self._drafts.pop(i); self.chunk_count.setValue(len(self._drafts)); self._sync_prompt_visibility(); self.chunk_tabs.setCurrentIndex(min(i,len(self._drafts)-1))
    def _add_sequence(self):
        if self._flush_prompt_before_action(("add",None,{"defaults":{"prompt":""}})): return
        self._sequence_op("add", defaults={"prompt":""})
    def _remove_sequence(self):
        cid=self._selected_chunk_id()
        if self._flush_prompt_before_action(("remove",cid,{})): return
        if cid is not None and len(self._sequence_ids)>2: self._sequence_op("remove", cid)
    def _move_sequence(self,delta):
        cid=self._selected_chunk_id()
        if self._sequence_ids and self._flush_prompt_before_action(("move",cid,{"delta":delta})): return
        if not self._sequence_ids:
            i=self.chunk_tabs.currentIndex(); j=i+delta
            if 0<=i<len(self._drafts) and 0<=j<len(self._drafts): self._drafts[i],self._drafts[j]=self._drafts[j],self._drafts[i]; self._sync_prompt_visibility(); self.chunk_tabs.setCurrentIndex(j)
            return
        if cid is not None: self._sequence_op("move", cid, delta=delta)
    def _duplicate_sequence(self):
        cid=self._selected_chunk_id()
        if self._sequence_ids and self._flush_prompt_before_action(("duplicate",cid,{})): return
        if not self._sequence_ids:
            i=self.chunk_tabs.currentIndex()
            if 0<=i<len(self._drafts): self._drafts.insert(i+1,ChunkDraft(prompt=self._drafts[i].prompt,overrides=dict(self._drafts[i].overrides))); self.chunk_count.setValue(len(self._drafts)); self._sync_prompt_visibility(); self.chunk_tabs.setCurrentIndex(i+1)
            return
        if cid is not None: self._sequence_op("duplicate", cid)
    def _set_override(self):
        cid=self._selected_chunk_id()
        if cid is not None:
            key=self.override_key.currentText(); raw=self.override_value.text()
            value=raw
            if key in {"length","steps","fps"}: value=int(raw)
            elif key=="megapixels": value=float(raw)
            elif key=="also_ref_first_frame": value=raw.strip().lower() in {"1","true","yes","on"}
            self._sequence_op("set_override", cid, key=key, value=value)
    def _clear_override(self, key=None):
        key=self.override_key.currentText() if key is None else key; i=self.chunk_tabs.currentIndex()
        if not 0 <= i < len(self._drafts): return
        self._drafts[i].overrides.pop(key,None); self._sync_draft_controls(); self._invalidate()
        cid=self._selected_chunk_id()
        if cid is not None: self._sequence_op("clear_override", cid, key=key)
    def _direct_override_toggle(self, i, key, on, editor, toggle, prov):
        if i >= len(self._drafts): return
        if on:
            value=self._effective_value(i,key)
            self._drafts[i].overrides[key]=value
            self._set_editor_value(editor,value)
        else:
            self._drafts[i].overrides.pop(key,None)
            self._set_editor_value(editor,self._effective_value(i,key))
        prov.setText("Override" if on else "Inherited (general)"); self._invalidate()
        cid=self._sequence_ids[i] if i < len(self._sequence_ids) else None
        if cid is not None: self._sequence_op("set_override" if on else "clear_override",cid,key=key,**({"value":self._drafts[i].overrides[key]} if on else {}))
    def _effective_value(self,i,key):
        return self._drafts[i].overrides.get(key, self._general_value(key))
    def _general_value(self,key):
        return {"megapixels":self.megapixels.value(),"length":self.length.value(),"steps":self.steps.value(),"fps":self.fps.value(),"ref_image_size":self.ref_image_size.currentText(),"also_ref_first_frame":self.also_ref_first_frame.isChecked()}[key]
    def _set_editor_value(self,e,v):
        e.blockSignals(True)
        if hasattr(e,"setValue"): e.setValue(v)
        elif hasattr(e,"setCurrentText"): e.setCurrentText(str(v))
        elif hasattr(e,"setChecked"): e.setChecked(bool(v))
        e.blockSignals(False)
    def _refresh_inherited_chunk_editors(self):
        if not hasattr(self,"chunk_tabs") or not hasattr(self,"ref_image_size"): return
        keys=("megapixels","length","steps","fps","ref_image_size","also_ref_first_frame")
        for i in range(min(len(self._drafts),self.chunk_tabs.count())):
            page=self.chunk_tabs.widget(i)
            for key in keys:
                toggle=getattr(page,f"chunk_{key}_override",None); editor=getattr(page,f"chunk_{key}_editor",None)
                if toggle is not None and editor is not None and not toggle.isChecked(): self._set_editor_value(editor,self._general_value(key))
    def _general_value_changed(self,*_):
        self._refresh_inherited_chunk_editors(); self._invalidate()
    def _direct_override_value(self,i,key,value):
        if i>=len(self._drafts): return
        page=self.chunk_tabs.widget(i); toggle=getattr(page,f"chunk_{key}_override",None)
        if not toggle or not toggle.isChecked(): return
        self._drafts[i].overrides[key]=value; self._invalidate()
        cid=self._sequence_ids[i] if i < len(self._sequence_ids) else None
        if cid is not None: self._sequence_op("set_override",cid,key=key,value=value)
    def _show_provenance(self):
        cid=self._selected_chunk_id()
        if not cid: self.provenance.setText("Effective values: select a chunk"); return
        result=self.facade.edit_sequence(self.project.text().strip(),self.execution.text().strip(),operation="read_provenance",chunk_id=cid)
        detail=getattr(result,"detail",None)
        if isinstance(detail,dict): self.provenance.setText(" | ".join(f"{k}={v['value']} ({v['source']})" for k,v in detail.items()))
    def refresh(self): self.render(self.facade.refresh())
    def _inputs(self):
        self._ensure_prompt_count(); prompts=[self.prompts[i].toPlainText() for i in range(self.chunk_count.value())]
        refs=[self.references.item(i).text().strip() for i in range(min(6,self.references.count())) if self.references.item(i) and self.references.item(i).text().strip()]
        overrides=[dict(d.overrides) for d in self._drafts[:self.chunk_count.value()]]
        return dict(project_id=self.project.text(), execution_id=self.execution.text(), initial_image=self.initial.text(), prompts=prompts, references=refs, chunk_count=self.chunk_count.value(), megapixels=self.megapixels.value(), length=self.length.value(), steps=self.steps.value(), fps=self.fps.value(), ref_image_size=self.ref_image_size.currentText(), also_ref_first_frame=self.also_ref_first_frame.isChecked(), chunk_overrides=overrides)
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
                if not pm.isNull(): label.setPixmap(pm.scaled(REFERENCE_PREVIEW_WIDTH,REFERENCE_PREVIEW_HEIGHT,Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def _sync_prompt_visibility(self):
        self._ensure_prompt_count()
        for i in range(len(self.prompts)):
            page=self.chunk_tabs.widget(i)
            if page is not None and not page.findChildren(QGroupBox, "chunkSettings"):
                box=QGroupBox("Chunk settings / Overrides", page); box.setObjectName("chunkSettings"); form=QFormLayout(box)
                for key,label in (("megapixels","Megapixels"),("length","Length / Frames"),("steps","Steps"),("fps","FPS"),("ref_image_size","Reference image size"),("also_ref_first_frame","Also reference first frame")):
                    toggle=QCheckBox("Override"); toggle.setObjectName(f"chunk_{key}_override")
                    if key=="megapixels": editor=QDoubleSpinBox(); editor.setRange(0.01,1000); editor.setDecimals(2)
                    elif key in {"length","steps","fps"}: editor=QSpinBox(); editor.setRange(1,100000)
                    elif key=="ref_image_size": editor=QComboBox(); editor.addItems(sorted(SUPPORTED_REF_IMAGE_SIZES))
                    else: editor=QCheckBox()
                    editor.setObjectName(f"chunk_{key}_editor"); editor.setEnabled(False); self._set_editor_value(editor,self._effective_value(i,key))
                    prov=QLabel("Inherited (general)"); prov.setObjectName(f"chunk_{key}_provenance")
                    toggle.toggled.connect(editor.setEnabled); toggle.toggled.connect(lambda on,k=key,p=prov: p.setText("Override" if on else "Inherited (general)"));
                    toggle.toggled.connect(lambda on,i=i,k=key,e=editor,t=toggle,p=prov: self._direct_override_toggle(i,k,on,e,t,p))
                    if key == "also_ref_first_frame": editor.toggled.connect(lambda v,i=i,k=key: self._direct_override_value(i,k,v))
                    elif key == "ref_image_size": editor.currentTextChanged.connect(lambda v,i=i,k=key: self._direct_override_value(i,k,v))
                    else: editor.valueChanged.connect(lambda v,i=i,k=key: self._direct_override_value(i,k,v))
                    form.addRow(label+":",toggle); form.addRow("",editor); form.addRow("",prov)
                    setattr(page, f"chunk_{key}_editor", editor); setattr(page, f"chunk_{key}_override", toggle)
                    restore=QPushButton("Restore inherited"); restore.setObjectName(f"chunk_{key}_restore"); restore.setToolTip("Clear this chunk override and use the general value"); restore.clicked.connect(lambda _=False,k=key: self._clear_override(k)); form.addRow("Overrides:",restore)
                page.layout().addWidget(box)
        self._sync_draft_controls(); self._update_sequence_controls()
    def _ensure_prompt_count(self):
        while len(self._drafts) < self.chunk_count.value(): self._drafts.append(ChunkDraft())
        while len(self._drafts) > self.chunk_count.value() and len(self._drafts)>2: self._drafts.pop()
        while len(self.prompts) < self.chunk_count.value():
            i=len(self.prompts); page=QWidget(); pl=QVBoxLayout(page); pl.addWidget(QLabel(f"Prompt — Chunk {i+1}")); e=QTextEdit(); e.setObjectName(f"chunkPrompt{i+1}"); e.setPlaceholderText(f"Prompt — Chunk {i+1}"); e.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)); e.setMinimumHeight(260); e.textChanged.connect(self._invalidate); e.textChanged.connect(lambda i=i,e=e: self._drafts[i].__setattr__('prompt',e.toPlainText()) if i < len(self._drafts) else None); e.textChanged.connect(self._persist_prompt_edit); pl.addWidget(e,1); self.prompts.append(e); self.chunk_tabs.addTab(page,f"Chunk {i+1}")
        while len(self.prompts) > self.chunk_count.value():
            self.chunk_tabs.removeTab(self.chunk_tabs.count()-1); self.prompts.pop()
    def _sync_draft_controls(self):
        if not hasattr(self,"chunk_tabs") or not hasattr(self,"ref_image_size"): return
        keys=("megapixels","length","steps","fps","ref_image_size","also_ref_first_frame")
        for i,draft in enumerate(self._drafts[:len(self.prompts)]):
            editor=self.prompts[i]; editor.blockSignals(True); editor.setPlainText(draft.prompt); editor.blockSignals(False)
            page=self.chunk_tabs.widget(i)
            for key in keys:
                toggle=getattr(page,f"chunk_{key}_override",None); value_editor=getattr(page,f"chunk_{key}_editor",None); provenance=getattr(page,f"chunk_{key}_provenance",None)
                if toggle is None or value_editor is None: continue
                on=key in draft.overrides; toggle.blockSignals(True); toggle.setChecked(on); toggle.blockSignals(False); value_editor.setEnabled(on); self._set_editor_value(value_editor,draft.overrides.get(key,self._general_value(key)))
                if provenance is not None: provenance.setText("Override" if on else "Inherited (general)")
    def _update_sequence_controls(self):
        if not hasattr(self,"chunk_tabs") or not hasattr(self,"remove_chunk_button"): return
        n=len(self._sequence_ids) or len(self._drafts); idx=self.chunk_tabs.currentIndex()
        self.add_chunk_button.setEnabled(not self._busy); self.remove_chunk_button.setEnabled(not self._busy and n>2); self.remove_chunk_button.setToolTip("Minimum is 2 chunks" if n<=2 else "Remove selected chunk")
        self.move_up_button.setEnabled(not self._busy and idx>0); self.move_down_button.setEnabled(not self._busy and idx>=0 and idx<n-1); self.duplicate_button.setEnabled(not self._busy)
    def _preflight(self): self._run(lambda:self.facade.preflight(**self._inputs()), "preflight")
    def _prepare(self):
        if self._flush_prompt_before_action(("prepare",None,{})): return
        # A new Prepare supersedes any older deferred restoration.  The
        # successful operation will install a fresh immutable identity.
        self._prepared_identity=None; self._prepared_key=None; self._prepared_selection=None
        self._run(lambda:self.facade.prepare(**self._inputs()), "prepare")
    def _start_chain(self):
        if self._prompt_dirty:
            self.status.setText("Prompt changes must be flushed before Start"); return
        if self._prepared_key is None or self._form_key()!=self._prepared_key:
            self.status.setText("Prepare is stale; re-prepare before Start"); self._update_start(); return
        project_id, execution_id = self._prepared_selection or (self.project.text().strip(), self.execution.text().strip())
        self._run(lambda:self.facade.start_chain(project_id, execution_id), "start")
    def _resume_or_recover(self):
        """Reopen an execution from durable IDs, never from the GUI form.

        The capability decision is made from a fresh authoritative snapshot in
        the worker operation.  The form's image, references, prompts and
        generation controls are deliberately not read or forwarded here.
        """
        project_id, execution_id = self.project.text().strip(), self.execution.text().strip()

        def operation():
            snapshot = self.facade.refresh(project_id, execution_id)
            if (
                snapshot.state in {"error", "unavailable"}
                or snapshot.project_id != project_id
                or snapshot.execution_id != execution_id
            ):
                return OperationResult(
                    False,
                    snapshot,
                    "authoritative execution snapshot is missing or invalid",
                )
            if snapshot.can_resume:
                return self.facade.resume_execution(project_id, execution_id)
            if snapshot.can_recover:
                return self.facade.recover_execution(project_id, execution_id)
            return OperationResult(
                False,
                snapshot,
                "no safe resume/recover capability is available",
            )

        self._run(operation, "resume")
    @staticmethod
    def _freeze_form_value(value):
        if isinstance(value, Mapping):
            return tuple((key, MainWindow._freeze_form_value(item)) for key, item in sorted(value.items(), key=lambda pair: str(pair[0])))
        if isinstance(value, (list, tuple)):
            return tuple(MainWindow._freeze_form_value(item) for item in value)
        return value
    def _form_key(self):
        return tuple((key, self._freeze_form_value(value)) for key, value in self._inputs().items())
    def _selection(self): return (self.project.text().strip(), self.execution.text().strip())
    def _update_start(self): self.start.setEnabled(bool(self._auth_can_start and not self._auth_busy and not self._busy and self._prepared_key is not None and self._form_key()==self._prepared_key))
    def render(self,s):
        previous_selected_id=self._selected_chunk_id() if hasattr(self,"chunk_tabs") else None
        previous_index=self.chunk_tabs.currentIndex() if hasattr(self,"chunk_tabs") else 0
        self._last_snapshot=s
        self._auth_can_start = bool(s.can_start); self._auth_busy = bool(s.busy)
        self.status.setText(s.state + (": "+"; ".join(s.errors) if s.errors else "")); self.chunks.clear(); self._sequence_ids=[c.chunk_id for c in s.chunks];
        if self._sequence_ids:
            self.chunk_count.blockSignals(True); self.chunk_count.setValue(max(2,len(self._sequence_ids))); self.chunk_count.blockSignals(False)
            self._drafts=[ChunkDraft(draft_id=str(c.chunk_id) if c.chunk_id else uuid4().hex, prompt=str(getattr(c,"prompt","") or ""), overrides=dict(getattr(c,"overrides",()) or ())) for c in s.chunks]
            self._sync_prompt_visibility()
            # Reconcile every editor by stable ID and hydrate from durable snapshot.
            for i, c in enumerate(s.chunks):
                editor = self.prompts[i]; editor._chunk_id = c.chunk_id
                editor.blockSignals(True); editor.setPlainText(self._drafts[i].prompt); editor.blockSignals(False)
                self.chunk_tabs.setTabText(i, f"Chunk {i+1}")
            self._sync_draft_controls()
            target_index=(self._sequence_ids.index(previous_selected_id) if previous_selected_id in self._sequence_ids else min(max(previous_index,0),len(self._sequence_ids)-1))
            self.chunk_tabs.blockSignals(True); self.chunk_tabs.setCurrentIndex(target_index); self.chunk_tabs.blockSignals(False)
        else:
            self._ensure_prompt_count()
        [self.chunks.addItem(f"Chunk {c.order+1} (order {c.order+1}): {c.state}" + (f" [{c.attempt_ref}]" if c.attempt_ref else "") + (f" error={c.error}" if c.error else "") + (f" output={c.output}" if c.output else "") + (f" transition={c.transition}" if c.transition else "")) for c in s.chunks];
        # An explicitly empty reference_slots is authoritative: clear any
        # references from the previously rendered snapshot.  Objects that do
        # not expose reference_slots have no authority over this GUI state.
        reference_slots = getattr(s, "reference_slots", None)
        if reference_slots is not None:
            self.references.clear(); self.references.addItems(list(reference_slots))
        configuration = getattr(s, "configuration", None)
        if isinstance(configuration, Mapping):
            values = dict(configuration)
            for key, widget in (
                ("megapixels", self.megapixels),
                ("length", self.length),
                ("steps", self.steps),
                ("fps", self.fps),
                ("ref_image_size", self.ref_image_size),
                ("also_ref_first_frame", self.also_ref_first_frame),
            ):
                if key in values:
                    self._set_editor_value(widget, values[key])
            self._refresh_inherited_chunk_editors()
        self._update_reference_labels()
        self.parameters.setText("Supported parameters: " + (", ".join(s.supported_parameters) if s.supported_parameters else "none reported")); self.cancel.setEnabled(s.can_cancel and not self._busy); self.cancel.setToolTip("Cancel is disabled unless exactly one safe pending job is proven" if not s.can_cancel else "Cancel the uniquely identified pending job"); self.retry.setEnabled(s.can_retry and not self._busy); self.retry.setToolTip("Retry is disabled until the durable retry contract permits it" if not s.can_retry else "Retry the failed chunk while preserving completed work"); self.resume.setToolTip("Resume/recover the durable execution" if (s.can_resume or s.can_recover) else "Enter both IDs to request a fresh durable capability snapshot"); self.assemble.setEnabled(s.can_assemble and not self._busy); self.assemble.setToolTip("Assemble/reassemble through F8" if s.can_assemble else "Requires all chunks to have verified outputs");
        try: artifacts = tuple(s.artifacts or ())
        except TypeError: artifacts = ()
        self.paths.setText("Chunks/intermediates/results: " + ("; ".join(artifacts) if artifacts else "none published yet"))
        self._update_sequence_controls()
        self._update_resume_recover()
        self._update_start()
    def _run(self,op,kind="other"):
        if self._busy: return
        self._operation_kind=kind; self._busy=True; self._set_enabled(False)
        self._thread=QThread(); self._worker=OperationWorker(op); self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self._on_worker_succeeded, Qt.QueuedConnection)
        self._worker.failed.connect(self._on_worker_failed, Qt.QueuedConnection)
        # The deferred delete must be queued while the worker thread's event
        # loop is still alive.  Scheduling it from QThread.finished races with
        # loop teardown on Windows and can terminate Python with 0xC0000409.
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(self._thread.quit)
        # Marshal teardown back to the GUI thread explicitly; a bare lambda
        # has no QObject receiver and may run on the just-stopped worker thread.
        self._thread.finished.connect(self._cleanup, Qt.QueuedConnection)
        self._thread.finished.connect(self._thread.deleteLater)
        self._retired_workers.append(self._worker)
        self._retired_threads.append(self._thread)
        self._thread.destroyed.connect(lambda *_: self._retired_threads.remove(self._thread) if self._thread in self._retired_threads else None)
        self._thread.start()
    @Slot(object)
    def _on_worker_succeeded(self,r):
        self._done(r)
    @Slot(str)
    def _on_worker_failed(self,error):
        self.log.append(error)
        if self._operation_kind == "prepare":
            self._prepared_identity=None; self._prepared_key=None; self._prepared_selection=None
        # A failed prompt flush must be terminal for the deferred gesture:
        # discard both the dirty draft and the queued action.  In particular,
        # _cleanup must never replay an action after a flush failure.
        if self._operation_kind == "prompt_flush":
            self._pending_action = None
            self._continuation = None
            self._prompt_dirty = None
        try: self.render(self.facade.refresh(self.project.text().strip(), self.execution.text().strip()))
        except Exception: self._last_snapshot=None
    @Slot(object)
    def _done(self,r):
        self.render(r.snapshot)
        if self._operation_kind=="prompt_flush":
            pending=self._pending_action; self._pending_action=None
            if r.success and pending: self._continuation=pending
            elif not r.success:
                self._prompt_dirty=None
        if r.success and self._operation_kind=="prepare":
            # Render may apply authoritative persisted fields (including
            # reference slots) and emit invalidation signals. Capture the
            # post-render form as the prepared snapshot identity.  Keep it in
            # a frozen value so cleanup cannot replace it with a later form.
            selection=(r.snapshot.project_id or self.project.text().strip(), r.snapshot.execution_id or self.execution.text().strip())
            self._prepared_identity=PreparedIdentity(self._form_key(), selection)
            self._prepared_key=self._prepared_identity.form_key
            self._prepared_selection=self._prepared_identity.selection
            self._update_start()
        elif not r.success and self._operation_kind=="prepare":
            self._prepared_identity=None; self._prepared_key=None; self._prepared_selection=None
        self.log.append(r.message or "Operation completed")
    @Slot()
    def _cleanup(self):
        expected=self._prepared_identity if self._operation_kind == "prepare" else None
        continuation=self._continuation; self._continuation=None
        self._busy=False
        if self._last_snapshot is not None:
            self._set_enabled(True)
            self.render(self._last_snapshot)
        else: self._set_enabled(False)
        # The cleanup render can emit invalidation signals.  Restore only the
        # immutable identity produced by Prepare, and only when the current
        # form and project/execution selection still match it exactly.
        if expected is not None and self._last_snapshot is not None:
            QTimer.singleShot(0, lambda identity=expected: self._restore_prepared(identity))
        self._update_start(); self._worker=None; self._thread=None
        if continuation:
            op,cid,kw=continuation
            def resume_continuation():
                if self._closing: return
                if op=="prepare": self._prepare()
                else: self._sequence_op(op,cid,**kw)
            QTimer.singleShot(0, resume_continuation)
    def _restore_prepared(self, identity):
        # A callback from an older Prepare must never invalidate a newer one.
        if self._prepared_identity is not identity:
            self._update_start()
            return
        if self._form_key()==identity.form_key and self._selection()==identity.selection:
            self._prepared_key=identity.form_key; self._prepared_selection=identity.selection
        else:
            self._prepared_key=None; self._prepared_selection=None
        self._update_start()
    def _invalidate(self,*_): self._prepared_key=None; self._prepared_selection=None; self._update_resume_recover(); self._update_start()
    def _update_resume_recover(self):
        """Gate only the visual recovery affordance, never its authority."""
        if not hasattr(self, "resume"):
            return
        enabled = bool(self.project.text().strip() and self.execution.text().strip()) and not self._busy
        self.resume.setEnabled(enabled)
    def _set_enabled(self,v):
        [x.setEnabled(v) for x in (self.preflight,self.prepare,self.start,self.retry,self.cancel,self.assemble,self.add_chunk_button,self.remove_chunk_button,self.move_up_button,self.move_down_button,self.duplicate_button,self.set_override_button,self.clear_override_button)]
        self._update_resume_recover()
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
        else:
            self._closing=True
            self._prompt_timer.stop()
            self._pending_action=None; self._continuation=None
            e.accept()
