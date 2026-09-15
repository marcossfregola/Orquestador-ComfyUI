"""Small F13.6 presentation component for preparation-library operations.

The widget knows only facade result objects and user-entered form values.  It
does not import storage, backend, or media adapters; MainWindow gives it the
same worker dispatch path used by every other long-running GUI operation.
"""
from __future__ import annotations

from importlib import import_module
from uuid import UUID

from ..application.gui_facade import LibraryOperationResult
from ..application.preparation_library import LibrarySelection


_widgets = import_module("PySide6.QtWidgets")
(
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QTextEdit,
    QDoubleSpinBox,
    QSpinBox,
    QCheckBox,
    QScrollArea,
    QTabWidget,
) = (
    _widgets.QWidget,
    _widgets.QVBoxLayout,
    _widgets.QHBoxLayout,
    _widgets.QFormLayout,
    _widgets.QGroupBox,
    _widgets.QLabel,
    _widgets.QPushButton,
    _widgets.QListWidget,
    _widgets.QListWidgetItem,
    _widgets.QLineEdit,
    _widgets.QTextEdit,
    _widgets.QDoubleSpinBox,
    _widgets.QSpinBox,
    _widgets.QCheckBox,
    _widgets.QScrollArea,
    _widgets.QTabWidget,
)
_core = import_module("PySide6.QtCore")
Qt = _core.Qt
QTimer = _core.QTimer
QEvent = _core.QEvent
QObject = _core.QObject


class _LibraryWheelClickPolicy(QObject):
    """Require a mouse click before a configuration control owns the wheel.

    Qt focus is not proof of editing intent: it can be assigned while a panel
    is created, restored, or navigated by keyboard.  The policy records the
    registered control under the actual left-click target, including an inner
    spinbox line edit, and clears that record on every click elsewhere.
    """

    def __init__(self, scroll_area, parent=None):
        super().__init__(parent)
        self._scroll_area = scroll_area
        self._protected = []
        self._armed = None
        self._application = _widgets.QApplication.instance()
        if self._application is None:
            raise RuntimeError("a QApplication is required for the library wheel policy")
        self._application.installEventFilter(self)

    def protect(self, *widgets):
        for widget in widgets:
            if not any(widget is protected for protected in self._protected):
                self._protected.append(widget)

    def _protected_owner(self, widget):
        """Find a registered owner even when Qt targets an inner child."""
        current = widget
        while current is not None:
            for protected in self._protected:
                if current is protected:
                    return protected
            current = current.parent()
        return None

    @staticmethod
    def _is_ancestor(candidate, child):
        current = child.parent()
        while current is not None:
            if current is candidate:
                return True
            current = current.parent()
        return False

    def _click_owner(self, watched, event):
        """Resolve a click once even if Qt later propagates it to parents."""
        owner = self._protected_owner(watched)
        if owner is not None:
            return owner
        position = event.globalPosition().toPoint()
        for protected in self._protected:
            if self._is_ancestor(watched, protected) and protected.isVisible() and protected.rect().contains(
                protected.mapFromGlobal(position)
            ):
                return protected
        return None

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.MouseButtonPress:
            self._armed = (
                self._click_owner(watched, event)
                if event.button() == Qt.LeftButton
                else None
            )
        elif event_type == QEvent.Type.FocusOut:
            if self._protected_owner(watched) is self._armed:
                self._armed = None
        elif event_type == QEvent.Type.Wheel:
            owner = self._protected_owner(watched)
            if owner is not None and owner is not self._armed:
                # QAbstractScrollArea owns platform-aware wheel step handling.
                # Passing the original event on keeps page scrolling intact
                # while returning True prevents the hovered editor mutating.
                self._scroll_area.wheelEvent(event)
                return True
        return super().eventFilter(watched, event)


class PreparationLibraryPanel(QWidget):
    """F13.6's simple project/execution and saved-configuration library."""

    def __init__(self, facade, run_operation, parent=None):
        super().__init__(parent)
        self.facade = facade
        self._run = run_operation
        self._snapshot = None
        self._selection = None
        self._preset_id = None
        self._template_id = None
        self._form_mode = "globals"
        self._busy = False
        self._rendering = False
        # ProjectId is a technical key.  A normal user-facing row must not
        # turn a clone's generated UUID into its apparent name.  The canonical
        # F13.2 aggregate intentionally has no durable project-name field, so
        # the source label is retained only for the current UI session.
        self._project_labels = {}
        self._pending_clone_source_label = None
        self._pending_success_message = None
        self._focus_new_entry = False
        self._available = callable(getattr(facade, "library_snapshot", None))
        self.setObjectName("preparationLibraryPanel")

        root = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("libraryScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        root.addWidget(self.scroll_area)
        self._wheel_click_policy = _LibraryWheelClickPolicy(self.scroll_area, self)
        host = QWidget()
        self.scroll_area.setWidget(host)
        layout = QVBoxLayout(host)

        work = QGroupBox("Proyectos y ejecuciones")
        work_form = QVBoxLayout(work)
        work_form.addWidget(
            QLabel(
                "Elegí una ejecución para abrirla o crear un borrador independiente "
                "a partir de su configuración. Los identificadores técnicos no se muestran."
            )
        )
        self.selection_context = QLabel("Selección actual: ninguna")
        self.selection_context.setObjectName("librarySelectionContext")
        self.selection_context.setWordWrap(True)
        work_form.addWidget(self.selection_context)
        create_row = QHBoxLayout()
        create_row.addWidget(QLabel("Nuevo proyecto:"))
        self.new_project_id = QLineEdit()
        self.new_project_id.setObjectName("libraryNewProjectId")
        self.new_project_id.setPlaceholderText("Nombre o identificador del nuevo proyecto")
        self.create_draft_button = QPushButton("Crear borrador")
        self.create_draft_button.setObjectName("libraryCreateDraftButton")
        create_row.addWidget(self.new_project_id)
        create_row.addWidget(self.create_draft_button)
        work_form.addLayout(create_row)
        self.execution_list = QListWidget()
        self.execution_list.setObjectName("libraryExecutionList")
        self.execution_list.setMinimumHeight(150)
        work_form.addWidget(self.execution_list)
        work_actions = QHBoxLayout()
        self.refresh_button = QPushButton("Actualizar biblioteca")
        self.refresh_button.setObjectName("libraryRefreshButton")
        self.open_button = QPushButton("Abrir selección")
        self.open_button.setObjectName("libraryOpenButton")
        self.clone_button = QPushButton("Crear a partir de esta")
        self.clone_button.setObjectName("libraryCloneButton")
        for button in (self.refresh_button, self.open_button, self.clone_button):
            work_actions.addWidget(button)
        work_form.addLayout(work_actions)
        layout.addWidget(work)

        defaults = QGroupBox("Valores globales y presets técnicos")
        defaults_form = QVBoxLayout(defaults)
        defaults_form.addWidget(
            QLabel(
                "Los ocho valores técnicos se copian a borradores nuevos o a presets. "
                "Guardarlos no modifica ejecuciones existentes."
            )
        )
        self._technical_widgets = self._technical_form(defaults_form)
        global_actions = QHBoxLayout()
        self.save_globals_button = QPushButton("Guardar valores globales")
        self.save_globals_button.setObjectName("librarySaveGlobalDefaultsButton")
        self.reload_globals_button = QPushButton("Recargar valores globales")
        self.reload_globals_button.setObjectName("libraryLoadGlobalDefaultsButton")
        global_actions.addWidget(self.save_globals_button)
        global_actions.addWidget(self.reload_globals_button)
        defaults_form.addLayout(global_actions)

        self.preset_list = QListWidget()
        self.preset_list.setObjectName("libraryPresetList")
        self.preset_list.setMinimumHeight(100)
        defaults_form.addWidget(QLabel("Presets técnicos"))
        defaults_form.addWidget(self.preset_list)
        self.preset_name = QLineEdit()
        self.preset_name.setObjectName("libraryPresetName")
        self.preset_name.setPlaceholderText("Nombre del preset")
        defaults_form.addWidget(self.preset_name)
        self.preset_default = QCheckBox("Marcar como preset predeterminado")
        self.preset_default.setObjectName("libraryPresetDefault")
        defaults_form.addWidget(self.preset_default)
        preset_actions_one = QHBoxLayout()
        self.create_preset_button = QPushButton("Crear preset")
        self.create_preset_button.setObjectName("libraryCreatePresetButton")
        self.update_preset_button = QPushButton("Actualizar valores")
        self.update_preset_button.setObjectName("libraryUpdatePresetButton")
        self.rename_preset_button = QPushButton("Renombrar preset")
        self.rename_preset_button.setObjectName("libraryRenamePresetButton")
        for button in (
            self.create_preset_button,
            self.update_preset_button,
            self.rename_preset_button,
        ):
            preset_actions_one.addWidget(button)
        defaults_form.addLayout(preset_actions_one)
        preset_actions_two = QHBoxLayout()
        self.delete_preset_button = QPushButton("Eliminar preset")
        self.delete_preset_button.setObjectName("libraryDeletePresetButton")
        self.set_default_preset_button = QPushButton("Usar como predeterminado")
        self.set_default_preset_button.setObjectName("librarySetDefaultPresetButton")
        self.clear_default_preset_button = QPushButton("Quitar predeterminado")
        self.clear_default_preset_button.setObjectName("libraryClearDefaultPresetButton")
        self.apply_preset_button = QPushButton("Aplicar al borrador seleccionado")
        self.apply_preset_button.setObjectName("libraryApplyPresetButton")
        for button in (
            self.delete_preset_button,
            self.set_default_preset_button,
            self.clear_default_preset_button,
            self.apply_preset_button,
        ):
            preset_actions_two.addWidget(button)
        defaults_form.addLayout(preset_actions_two)
        layout.addWidget(defaults)

        templates = QGroupBox("Plantillas de chunks")
        templates_form = QVBoxLayout(templates)
        templates_form.addWidget(
            QLabel(
                "Cada pestaña representa un chunk y su prompt. Aplicar una plantilla "
                "reemplaza sólo el plan de prompts de un borrador editable."
            )
        )
        self.template_list = QListWidget()
        self.template_list.setObjectName("libraryTemplateList")
        self.template_list.setMinimumHeight(100)
        templates_form.addWidget(self.template_list)
        self.template_name = QLineEdit()
        self.template_name.setObjectName("libraryTemplateName")
        self.template_name.setPlaceholderText("Nombre de la plantilla")
        templates_form.addWidget(self.template_name)
        self.template_tabs = QTabWidget()
        self.template_tabs.setObjectName("libraryTemplateChunkTabs")
        self.template_tabs.setMinimumHeight(150)
        self._template_prompt_editors = []
        templates_form.addWidget(self.template_tabs)
        template_chunk_actions = QHBoxLayout()
        self.add_template_chunk_button = QPushButton("Agregar chunk")
        self.add_template_chunk_button.setObjectName("libraryAddTemplateChunkButton")
        self.remove_template_chunk_button = QPushButton("Quitar chunk")
        self.remove_template_chunk_button.setObjectName("libraryRemoveTemplateChunkButton")
        template_chunk_actions.addWidget(self.add_template_chunk_button)
        template_chunk_actions.addWidget(self.remove_template_chunk_button)
        template_chunk_actions.addStretch(1)
        templates_form.addLayout(template_chunk_actions)
        self._set_template_prompts(("", ""))
        template_actions_one = QHBoxLayout()
        self.create_template_button = QPushButton("Crear plantilla")
        self.create_template_button.setObjectName("libraryCreateTemplateButton")
        self.update_template_button = QPushButton("Actualizar prompts")
        self.update_template_button.setObjectName("libraryUpdateTemplateButton")
        self.rename_template_button = QPushButton("Renombrar plantilla")
        self.rename_template_button.setObjectName("libraryRenameTemplateButton")
        for button in (
            self.create_template_button,
            self.update_template_button,
            self.rename_template_button,
        ):
            template_actions_one.addWidget(button)
        templates_form.addLayout(template_actions_one)
        template_actions_two = QHBoxLayout()
        self.duplicate_template_button = QPushButton("Duplicar plantilla")
        self.duplicate_template_button.setObjectName("libraryDuplicateTemplateButton")
        self.delete_template_button = QPushButton("Eliminar plantilla")
        self.delete_template_button.setObjectName("libraryDeleteTemplateButton")
        self.apply_template_button = QPushButton("Aplicar al borrador seleccionado")
        self.apply_template_button.setObjectName("libraryApplyTemplateButton")
        for button in (
            self.duplicate_template_button,
            self.delete_template_button,
            self.apply_template_button,
        ):
            template_actions_two.addWidget(button)
        templates_form.addLayout(template_actions_two)
        layout.addWidget(templates)

        self.status = QLabel("Biblioteca sin cargar")
        self.status.setObjectName("libraryStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)

        self.execution_list.itemSelectionChanged.connect(self._execution_changed)
        self.execution_list.itemDoubleClicked.connect(lambda _item: self.open_selected())
        self.new_project_id.textChanged.connect(lambda _text: self._update_controls())
        self.preset_list.itemSelectionChanged.connect(self._preset_changed)
        self.template_list.itemSelectionChanged.connect(self._template_changed)
        self.refresh_button.clicked.connect(self.refresh)
        self.create_draft_button.clicked.connect(self.create_draft)
        self.open_button.clicked.connect(self.open_selected)
        self.clone_button.clicked.connect(self.clone_selected)
        self.save_globals_button.clicked.connect(self.save_global_defaults)
        self.reload_globals_button.clicked.connect(self.load_global_defaults)
        self.create_preset_button.clicked.connect(self.create_preset)
        self.update_preset_button.clicked.connect(self.update_preset)
        self.rename_preset_button.clicked.connect(self.rename_preset)
        self.delete_preset_button.clicked.connect(self.delete_preset)
        self.set_default_preset_button.clicked.connect(self.set_default_preset)
        self.clear_default_preset_button.clicked.connect(self.clear_default_preset)
        self.apply_preset_button.clicked.connect(self.apply_preset)
        self.create_template_button.clicked.connect(self.create_template)
        self.update_template_button.clicked.connect(self.update_template)
        self.rename_template_button.clicked.connect(self.rename_template)
        self.duplicate_template_button.clicked.connect(self.duplicate_template)
        self.delete_template_button.clicked.connect(self.delete_template)
        self.apply_template_button.clicked.connect(self.apply_template)
        self.add_template_chunk_button.clicked.connect(self.add_template_chunk)
        self.remove_template_chunk_button.clicked.connect(self.remove_template_chunk)
        self._update_controls()

    @staticmethod
    def _integer_box(minimum=1, maximum=1000000):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        return widget

    @staticmethod
    def _is_technical_uuid(value):
        """Return whether a ProjectId is the generated F13.2 technical key."""
        if not isinstance(value, str):
            return False
        try:
            return str(UUID(value)) == value.lower()
        except (TypeError, ValueError, AttributeError):
            return False

    @staticmethod
    def _state_label(classification):
        return {
            "draft": "Borrador editable",
            "queued": "En cola",
            "running": "En ejecución",
            "recovering": "En recuperación",
            "succeeded": "Finalizada",
            "failed": "Fallida",
            "cancelled": "Cancelada",
            "attention_required": "Requiere revisión",
        }.get(str(classification), "Estado no disponible")

    def display_project_name(self, project_id):
        """Return presentation identity without leaking a generated UUID."""
        if project_id in self._project_labels:
            return self._project_labels[project_id]
        if self._is_technical_uuid(project_id):
            return "Proyecto generado"
        return str(project_id).strip() or "Proyecto sin nombre"

    def display_selection(self, selection):
        if selection is None:
            return "ninguna"
        return (
            f"Proyecto: {self.display_project_name(selection.project_id)} · "
            f"Ejecución {selection.execution_number} · "
            f"{self._state_label(selection.classification)}"
        )

    def _update_selection_context(self):
        self.selection_context.setText("Selección actual: " + self.display_selection(self._selection))

    def _restore_scroll_position(self, value):
        """Restore after Qt lays out a refreshed list without moving focus."""
        def restore():
            bar = self.scroll_area.verticalScrollBar()
            bar.setValue(max(0, min(int(value), bar.maximum())))

        QTimer.singleShot(0, restore)

    def _technical_form(self, parent_layout):
        form = QFormLayout()
        megapixels = QDoubleSpinBox()
        megapixels.setObjectName("libraryGlobalMegapixels")
        megapixels.setRange(0.01, 1000.0)
        megapixels.setDecimals(2)
        megapixels.setSingleStep(0.01)
        length = self._integer_box()
        length.setObjectName("libraryGlobalLength")
        steps = self._integer_box()
        steps.setObjectName("libraryGlobalSteps")
        fps = self._integer_box()
        fps.setObjectName("libraryGlobalFps")
        ref_size = QLineEdit()
        ref_size.setObjectName("libraryGlobalReferenceImageSize")
        primary = QCheckBox()
        primary.setObjectName("libraryGlobalFirstFramePrimary")
        also_reference = QCheckBox()
        also_reference.setObjectName("libraryGlobalAlsoReferenceFirstFrame")
        timeout = self._integer_box()
        timeout.setObjectName("libraryGlobalTimeout")
        widgets = {
            "megapixels": megapixels,
            "length": length,
            "steps": steps,
            "fps": fps,
            "ref_image_size": ref_size,
            "also_ref_first_frame": also_reference,
            "first_frame_as_primary_reference": primary,
            "orchestration_timeout_seconds": timeout,
        }
        labels = {
            "megapixels": "Megapixels",
            "length": "Duración / frames",
            "steps": "Pasos",
            "fps": "FPS",
            "ref_image_size": "Tamaño de imagen de referencia",
            "also_ref_first_frame": "Incluir también el primer frame como referencia",
            "first_frame_as_primary_reference": "Usar el primer frame como Referencia 1",
            "orchestration_timeout_seconds": "Timeout de orquestación (segundos)",
        }
        for key in (
            "megapixels",
            "length",
            "steps",
            "fps",
            "ref_image_size",
            "also_ref_first_frame",
            "first_frame_as_primary_reference",
            "orchestration_timeout_seconds",
        ):
            form.addRow(labels[key], widgets[key])
        self._wheel_click_policy.protect(
            megapixels,
            length,
            steps,
            fps,
            timeout,
        )
        parent_layout.addLayout(form)
        return widgets

    def ensure_loaded(self):
        if self._snapshot is None and not self._busy:
            self._focus_new_entry = True
            self.refresh()

    def set_busy(self, value):
        self._busy = bool(value)
        self._update_controls()

    def _dispatch(self, operation, kind, success_message=None):
        if self._busy or not self._available:
            return
        self._pending_success_message = success_message
        self._run(operation, kind)

    def refresh(self):
        self._dispatch(
            lambda: self.facade.library_snapshot(),
            "library_refresh",
            "Biblioteca actualizada",
        )

    def _mapping(self):
        widgets = self._technical_widgets
        return {
            "megapixels": float(widgets["megapixels"].value()),
            "length": int(widgets["length"].value()),
            "steps": int(widgets["steps"].value()),
            "fps": int(widgets["fps"].value()),
            "ref_image_size": widgets["ref_image_size"].text().strip(),
            "also_ref_first_frame": bool(widgets["also_ref_first_frame"].isChecked()),
            "first_frame_as_primary_reference": bool(
                widgets["first_frame_as_primary_reference"].isChecked()
            ),
            "orchestration_timeout_seconds": int(
                widgets["orchestration_timeout_seconds"].value()
            ),
        }

    def _set_mapping(self, mapping):
        values = dict(mapping or ())
        for key, widget in self._technical_widgets.items():
            if key not in values:
                continue
            widget.blockSignals(True)
            try:
                value = values[key]
                if hasattr(widget, "setChecked"):
                    widget.setChecked(bool(value))
                elif hasattr(widget, "setValue"):
                    widget.setValue(value)
                else:
                    widget.setText(str(value))
            finally:
                widget.blockSignals(False)

    def _template_prompts(self):
        """Keep tab order and blank tabs so the owning use case can fail closed."""
        return tuple(editor.toPlainText().strip() for editor in self._template_prompt_editors)

    def _set_template_prompts(self, prompts):
        values = tuple(str(value) for value in prompts)
        if len(values) < 2:
            values = values + ("",) * (2 - len(values))
        previous_index = self.template_tabs.currentIndex()
        while len(self._template_prompt_editors) < len(values):
            index = len(self._template_prompt_editors)
            editor = QTextEdit()
            editor.setObjectName(f"libraryTemplatePrompt{index + 1}")
            editor.setPlaceholderText(f"Prompt del chunk {index + 1}")
            self._template_prompt_editors.append(editor)
            self.template_tabs.addTab(editor, f"Chunk {index + 1}")
        while len(self._template_prompt_editors) > len(values):
            index = len(self._template_prompt_editors) - 1
            editor = self._template_prompt_editors.pop()
            self.template_tabs.removeTab(index)
            editor.deleteLater()
        for index, (editor, value) in enumerate(zip(self._template_prompt_editors, values)):
            editor.blockSignals(True)
            editor.setPlainText(value)
            editor.blockSignals(False)
            self.template_tabs.setTabText(index, f"Chunk {index + 1}")
        self.template_tabs.setCurrentIndex(
            min(max(previous_index, 0), len(self._template_prompt_editors) - 1)
        )

    def add_template_chunk(self):
        self._set_template_prompts(self._template_prompts() + ("",))
        self.template_tabs.setCurrentIndex(len(self._template_prompt_editors) - 1)
        self._update_controls()

    def remove_template_chunk(self):
        if len(self._template_prompt_editors) <= 2:
            return
        index = self.template_tabs.currentIndex()
        values = list(self._template_prompts())
        values.pop(index if 0 <= index < len(values) else len(values) - 1)
        self._set_template_prompts(tuple(values))
        self._update_controls()

    def _current_execution(self):
        item = self.execution_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return value if hasattr(value, "execution_id") else None

    def _current_preset_id(self):
        item = self.preset_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _current_template_id(self):
        item = self.template_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _execution_changed(self):
        if self._rendering:
            return
        self._selection = self._current_execution()
        self._update_selection_context()
        self._update_controls()

    def _preset_changed(self):
        if self._rendering:
            return
        preset_id = self._current_preset_id()
        self._preset_id = preset_id
        if preset_id is not None and self._snapshot is not None:
            preset = next(
                (item for item in self._snapshot.technical_presets if item.preset_id == preset_id),
                None,
            )
            if preset is not None:
                self._form_mode = "preset"
                self.preset_name.setText(preset.name)
                self.preset_default.setChecked(preset.is_default)
                self._set_mapping(preset.mapping)
        elif preset_id is None:
            self._form_mode = "globals"
            if self._snapshot is not None:
                self._set_mapping(self._snapshot.global_defaults)
        self._update_controls()

    def _template_changed(self):
        if self._rendering:
            return
        template_id = self._current_template_id()
        self._template_id = template_id
        if template_id is not None and self._snapshot is not None:
            template = next(
                (item for item in self._snapshot.chunk_templates if item.template_id == template_id),
                None,
            )
            if template is not None:
                self.template_name.setText(template.name)
                self._set_template_prompts(template.prompts)
        self._update_controls()

    def _find_execution_item(self, selection):
        if selection is None:
            return None
        for index in range(self.execution_list.count()):
            item = self.execution_list.item(index)
            value = item.data(Qt.UserRole)
            if (
                hasattr(value, "project_id")
                and value.project_id == selection.project_id
                and value.execution_id == selection.execution_id
            ):
                return item
        return None

    def _find_data_item(self, widget, value):
        for index in range(widget.count()):
            item = widget.item(index)
            if item.data(Qt.UserRole) == value:
                return item
        return None

    def render(self, snapshot):
        previous_scroll = self.scroll_area.verticalScrollBar().value()
        focus_new_entry = self._focus_new_entry
        self._focus_new_entry = False
        self._snapshot = snapshot
        selected_execution = self._selection
        selected_preset = self._preset_id
        selected_template = self._template_id
        self._rendering = True
        try:
            self.execution_list.clear()
            projects = list(snapshot.projects)
            if focus_new_entry and selected_execution is not None:
                projects.sort(
                    key=lambda project: (
                        project.project_id != selected_execution.project_id,
                        self.display_project_name(project.project_id).casefold(),
                    )
                )
            for project in projects:
                if not project.executions:
                    self.execution_list.addItem(
                        f"Proyecto: {self.display_project_name(project.project_id)} · sin ejecuciones"
                    )
                for execution in project.executions:
                    text = (
                        f"Proyecto: {self.display_project_name(project.project_id)} · "
                        f"Ejecución {execution.execution_number} · "
                        f"{self._state_label(execution.classification)}"
                    )
                    item = QListWidgetItem(text)
                    item.setData(
                        Qt.UserRole,
                        LibrarySelection(
                            execution.project_id,
                            execution.execution_id,
                            execution.execution_number,
                            execution.classification,
                            execution.can_open,
                            execution.can_edit,
                            execution.can_clone,
                        ),
                    )
                    self.execution_list.addItem(item)
            self.preset_list.clear()
            for preset in snapshot.technical_presets:
                text = preset.name + (" (default)" if preset.is_default else "")
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, preset.preset_id)
                self.preset_list.addItem(item)
            self.template_list.clear()
            for template in snapshot.chunk_templates:
                item = QListWidgetItem(template.name)
                item.setData(Qt.UserRole, template.template_id)
                self.template_list.addItem(item)

            execution_item = self._find_execution_item(selected_execution)
            if execution_item is not None:
                self.execution_list.setCurrentItem(execution_item)
                self._selection = execution_item.data(Qt.UserRole)
            else:
                self._selection = None
            preset_item = self._find_data_item(self.preset_list, selected_preset)
            if preset_item is not None:
                self.preset_list.setCurrentItem(preset_item)
                self._preset_id = selected_preset
            else:
                self._preset_id = None
                self._form_mode = "globals"
            template_item = self._find_data_item(self.template_list, selected_template)
            if template_item is not None:
                self.template_list.setCurrentItem(template_item)
                self._template_id = selected_template
            else:
                self._template_id = None
            if self._form_mode == "preset" and self._preset_id is not None:
                preset = next(
                    item
                    for item in snapshot.technical_presets
                    if item.preset_id == self._preset_id
                )
                self._set_mapping(preset.mapping)
                self.preset_name.setText(preset.name)
                self.preset_default.setChecked(preset.is_default)
            else:
                self._set_mapping(snapshot.global_defaults)
        finally:
            self._rendering = False
        self._update_selection_context()
        self.status.setText("Biblioteca cargada")
        self._update_controls()
        # A new draft/clone is deliberately placed at the top of the list and
        # shown from the top.  Ordinary refreshes retain the user's position.
        self._restore_scroll_position(0 if focus_new_entry else previous_scroll)

    def handle_result(self, result):
        if not isinstance(result, LibraryOperationResult):
            self.show_error("resultado inesperado de la Biblioteca")
            return
        if result.success and result.selection is not None and self._pending_clone_source_label:
            self._project_labels[result.selection.project_id] = (
                f"Copia de {self._pending_clone_source_label}"
            )
            self._focus_new_entry = True
        self._pending_clone_source_label = None
        if result.selection is not None:
            self._selection = result.selection
        if result.library is not None:
            self.render(result.library)
        if result.success:
            self.status.setText(
                result.message or self._pending_success_message or "Operación completada"
            )
        else:
            self.show_error(result.message or "la operación de Biblioteca falló")
        self._pending_success_message = None
        self._update_controls()

    def show_error(self, message):
        self._pending_success_message = None
        self._pending_clone_source_label = None
        self._focus_new_entry = False
        detail = str(message).strip()
        self.status.setText("Error en Biblioteca" + (f": {detail}" if detail else ""))

    def open_selected(self):
        selection = self._current_execution()
        if selection is None or not selection.can_open:
            return
        self._dispatch(
            lambda: self.facade.open_library_execution(
                selection.project_id, selection.execution_id
            ),
            "library_open",
            "Ejecución abierta",
        )

    def create_draft(self):
        project_id = self.new_project_id.text().strip()
        if not project_id:
            self.show_error("indicá un nombre o identificador para el nuevo proyecto")
            return
        self._focus_new_entry = True
        self._dispatch(
            lambda: self.facade.create_library_draft(project_id),
            "library_create_draft",
            "Borrador creado",
        )

    def clone_selected(self):
        selection = self._current_execution()
        if selection is None or not selection.can_clone:
            return
        self._pending_clone_source_label = self.display_project_name(selection.project_id)
        self._focus_new_entry = True
        self._dispatch(
            lambda: self.facade.clone_library_execution(
                selection.project_id, selection.execution_id
            ),
            "library_clone",
            "Copia creada como borrador independiente",
        )

    def save_global_defaults(self):
        self._form_mode = "globals"
        mapping = self._mapping()
        self._dispatch(
            lambda mapping=mapping: self.facade.update_global_defaults(mapping),
            "library_globals",
            "Valores globales guardados",
        )

    def load_global_defaults(self):
        self._form_mode = "globals"
        # A load is a durable re-read, not merely a restoration of whatever
        # happened to be in this panel before another actor changed defaults.
        # ``render`` preserves the current row selection while replacing the
        # form with the refreshed authoritative snapshot.
        self.refresh()

    def create_preset(self):
        name = self.preset_name.text()
        mapping = self._mapping()
        is_default = self.preset_default.isChecked()
        self._dispatch(
            lambda name=name, mapping=mapping, is_default=is_default: self.facade.create_preset(
                name, mapping, is_default=is_default
            ),
            "library_preset_create",
            "Preset creado",
        )

    def update_preset(self):
        preset_id = self._current_preset_id()
        if preset_id is None:
            return
        mapping = self._mapping()
        self._dispatch(
            lambda preset_id=preset_id, mapping=mapping: self.facade.update_preset(
                preset_id, mapping
            ),
            "library_preset_update",
            "Valores del preset actualizados",
        )

    def rename_preset(self):
        preset_id = self._current_preset_id()
        if preset_id is None:
            return
        name = self.preset_name.text()
        self._dispatch(
            lambda preset_id=preset_id, name=name: self.facade.rename_preset(
                preset_id, name
            ),
            "library_preset_rename",
            "Preset renombrado",
        )

    def delete_preset(self):
        preset_id = self._current_preset_id()
        if preset_id is not None:
            self._dispatch(
                lambda: self.facade.delete_preset(preset_id),
                "library_preset_delete",
                "Preset eliminado",
            )

    def set_default_preset(self):
        preset_id = self._current_preset_id()
        if preset_id is not None:
            self._dispatch(
                lambda: self.facade.set_default_preset(preset_id),
                "library_preset_default",
                "Preset predeterminado actualizado",
            )

    def clear_default_preset(self):
        self._dispatch(
            lambda: self.facade.clear_default_preset(),
            "library_preset_clear_default",
            "Preset predeterminado quitado",
        )

    def apply_preset(self):
        preset_id = self._current_preset_id()
        selection = self._current_execution()
        if preset_id is None or selection is None or not selection.can_edit:
            return
        self._dispatch(
            lambda: self.facade.apply_preset(
                preset_id, selection.project_id, selection.execution_id
            ),
            "library_preset_apply",
            "Preset aplicado al borrador",
        )

    def create_template(self):
        name = self.template_name.text()
        prompts = self._template_prompts()
        self._dispatch(
            lambda name=name, prompts=prompts: self.facade.create_template(name, prompts),
            "library_template_create",
            "Plantilla creada",
        )

    def update_template(self):
        template_id = self._current_template_id()
        if template_id is not None:
            prompts = self._template_prompts()
            self._dispatch(
                lambda template_id=template_id, prompts=prompts: self.facade.update_template(
                    template_id, prompts
                ),
                "library_template_update",
                "Prompts de la plantilla actualizados",
            )

    def rename_template(self):
        template_id = self._current_template_id()
        if template_id is not None:
            name = self.template_name.text()
            self._dispatch(
                lambda template_id=template_id, name=name: self.facade.rename_template(
                    template_id, name
                ),
                "library_template_rename",
                "Plantilla renombrada",
            )

    def duplicate_template(self):
        template_id = self._current_template_id()
        if template_id is not None:
            name = self.template_name.text()
            self._dispatch(
                lambda template_id=template_id, name=name: self.facade.duplicate_template(
                    template_id, name
                ),
                "library_template_duplicate",
                "Plantilla duplicada",
            )

    def delete_template(self):
        template_id = self._current_template_id()
        if template_id is not None:
            self._dispatch(
                lambda: self.facade.delete_template(template_id),
                "library_template_delete",
                "Plantilla eliminada",
            )

    def apply_template(self):
        template_id = self._current_template_id()
        selection = self._current_execution()
        if template_id is None or selection is None or not selection.can_edit:
            return
        self._dispatch(
            lambda: self.facade.apply_template(
                template_id, selection.project_id, selection.execution_id
            ),
            "library_template_apply",
            "Plantilla aplicada al borrador",
        )

    def _update_controls(self):
        loaded = self._snapshot is not None
        ready = self._available and loaded and not self._busy
        selection = self._current_execution()
        preset_id = self._current_preset_id()
        template_id = self._current_template_id()
        self.refresh_button.setEnabled(self._available and not self._busy)
        self.new_project_id.setEnabled(self._available and not self._busy)
        self.create_draft_button.setEnabled(
            self._available and not self._busy and bool(self.new_project_id.text().strip())
        )
        self.execution_list.setEnabled(loaded and not self._busy)
        self.open_button.setEnabled(ready and selection is not None and selection.can_open)
        self.clone_button.setEnabled(ready and selection is not None and selection.can_clone)
        for widget in self._technical_widgets.values():
            widget.setEnabled(ready)
        self.save_globals_button.setEnabled(ready)
        self.reload_globals_button.setEnabled(self._available and not self._busy)
        self.preset_list.setEnabled(ready)
        self.preset_name.setEnabled(ready)
        self.preset_default.setEnabled(ready)
        self.create_preset_button.setEnabled(ready)
        self.update_preset_button.setEnabled(ready and preset_id is not None)
        self.rename_preset_button.setEnabled(ready and preset_id is not None)
        self.delete_preset_button.setEnabled(ready and preset_id is not None)
        self.set_default_preset_button.setEnabled(ready and preset_id is not None)
        self.clear_default_preset_button.setEnabled(ready)
        self.apply_preset_button.setEnabled(
            ready and preset_id is not None and selection is not None and selection.can_edit
        )
        self.template_list.setEnabled(ready)
        self.template_name.setEnabled(ready)
        self.template_tabs.setEnabled(ready)
        for editor in self._template_prompt_editors:
            editor.setReadOnly(not ready)
        self.add_template_chunk_button.setEnabled(ready)
        self.remove_template_chunk_button.setEnabled(ready and len(self._template_prompt_editors) > 2)
        self.remove_template_chunk_button.setToolTip(
            "Una plantilla necesita al menos dos chunks"
            if len(self._template_prompt_editors) <= 2
            else "Quitar el chunk seleccionado de la plantilla"
        )
        self.create_template_button.setEnabled(ready)
        self.update_template_button.setEnabled(ready and template_id is not None)
        self.rename_template_button.setEnabled(ready and template_id is not None)
        self.duplicate_template_button.setEnabled(ready and template_id is not None)
        self.delete_template_button.setEnabled(ready and template_id is not None)
        self.apply_template_button.setEnabled(
            ready and template_id is not None and selection is not None and selection.can_edit
        )


__all__ = ["PreparationLibraryPanel"]
