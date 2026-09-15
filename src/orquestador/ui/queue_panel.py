"""F13.10 product-queue panel.

Widgets render application snapshots and dispatch only through ``GuiFacade``.
They deliberately have no SQLite, ComfyUI, or scheduler-control dependency.
"""
from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..application.gui_facade import QueueOperationResult


class QueuePanel(QWidget):
    """A readable, non-blocking UI projection of the durable execution queue."""

    def __init__(self, facade, run_operation, parent=None):
        super().__init__(parent)
        self.facade = facade
        self._run = run_operation
        self._snapshot = None
        self._selection_id = None
        self._busy = False
        self._rendering = False
        self._pending_success_message = None
        self._available = callable(getattr(facade, "queue_snapshot", None))
        self.setObjectName("queuePanel")

        root = QVBoxLayout(self)
        summary = QGroupBox("Estado de la cola")
        summary_layout = QVBoxLayout(summary)
        self.global_state = QLabel("Cola sin cargar")
        self.global_state.setObjectName("queueGlobalState")
        self.global_state.setWordWrap(True)
        self.global_detail = QLabel(
            "La cola conserva el orden y un único item activo de forma durable."
        )
        self.global_detail.setObjectName("queueGlobalDetail")
        self.global_detail.setWordWrap(True)
        summary_layout.addWidget(self.global_state)
        summary_layout.addWidget(self.global_detail)
        root.addWidget(summary)

        work = QGroupBox("Trabajos")
        work_layout = QVBoxLayout(work)
        work_layout.addWidget(
            QLabel(
                "El scheduler toma automáticamente el próximo item cuando la cola "
                "no está pausada. Un activo con recuperación o revisión pendiente "
                "bloquea el siguiente trabajo."
            )
        )
        self.items = QTreeWidget()
        self.items.setObjectName("queueItems")
        self.items.setColumnCount(4)
        self.items.setHeaderLabels(("Orden", "Proyecto", "Ejecución", "Estado"))
        self.items.setRootIsDecorated(False)
        self.items.setAlternatingRowColors(True)
        self.items.setMinimumHeight(220)
        self.items.setSelectionMode(QTreeWidget.SingleSelection)
        self.items.setUniformRowHeights(True)
        self.items.header().setStretchLastSection(True)
        self.items.setColumnWidth(0, 70)
        self.items.setColumnWidth(1, 230)
        self.items.setColumnWidth(2, 120)
        work_layout.addWidget(self.items, 1)

        first_actions = QHBoxLayout()
        self.refresh_button = QPushButton("Actualizar cola")
        self.refresh_button.setObjectName("queueRefreshButton")
        self.pause_resume_button = QPushButton("Pausar cola")
        self.pause_resume_button.setObjectName("queuePauseResumeButton")
        self.open_button = QPushButton("Ver selección")
        self.open_button.setObjectName("queueOpenButton")
        for button in (self.refresh_button, self.pause_resume_button, self.open_button):
            first_actions.addWidget(button)
        first_actions.addStretch(1)
        work_layout.addLayout(first_actions)

        second_actions = QHBoxLayout()
        self.move_up_button = QPushButton("Mover arriba")
        self.move_up_button.setObjectName("queueMoveUpButton")
        self.move_down_button = QPushButton("Mover abajo")
        self.move_down_button.setObjectName("queueMoveDownButton")
        self.duplicate_button = QPushButton("Duplicar")
        self.duplicate_button.setObjectName("queueDuplicateButton")
        self.skip_button = QPushButton("Omitir")
        self.skip_button.setObjectName("queueSkipButton")
        self.remove_button = QPushButton("Remover")
        self.remove_button.setObjectName("queueRemoveButton")
        for button in (
            self.move_up_button,
            self.move_down_button,
            self.duplicate_button,
            self.skip_button,
            self.remove_button,
        ):
            second_actions.addWidget(button)
        second_actions.addStretch(1)
        work_layout.addLayout(second_actions)
        root.addWidget(work, 1)

        self.status = QLabel("Cola sin cargar")
        self.status.setObjectName("queueStatus")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.items.itemSelectionChanged.connect(self._selection_changed)
        self.items.itemDoubleClicked.connect(lambda _item, _column: self.open_selected())
        self.refresh_button.clicked.connect(self.refresh)
        self.pause_resume_button.clicked.connect(self.pause_or_resume)
        self.open_button.clicked.connect(self.open_selected)
        self.move_up_button.clicked.connect(lambda: self.move_selected(-1))
        self.move_down_button.clicked.connect(lambda: self.move_selected(1))
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.skip_button.clicked.connect(self.skip_selected)
        self.remove_button.clicked.connect(self.remove_selected)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._refresh_if_idle)
        self._update_controls()

    @staticmethod
    def _is_technical_uuid(value):
        if not isinstance(value, str):
            return False
        try:
            return str(UUID(value)) == value.lower()
        except (TypeError, ValueError, AttributeError):
            return False

    @classmethod
    def _project_label(cls, project_id):
        return "Proyecto generado" if cls._is_technical_uuid(project_id) else str(project_id)

    @staticmethod
    def _global_label(state):
        return {
            "idle": "Idle",
            "paused": "Paused",
            "running": "Running",
            "starting": "Iniciando",
            "finishing": "Finalizando item",
            "recovery": "Recovery en curso",
            "manual_review": "Requiere revisión manual",
            "blocked": "Bloqueada",
        }.get(str(state), str(state) or "Sin estado")

    @staticmethod
    def _entry_label(entry):
        return {
            "queued": "En espera",
            "paused": "Activa (pausada)",
            "running": "Activa — Running",
            "starting": "Activa — iniciando",
            "finishing": "Activa — finalizando",
            "recovery": "Activa — Recovery",
            "manual_review": "Activa — revisión manual",
            "blocked": "Activa — bloqueada",
            "finished": "Finalizada",
            "removed": "Removida",
            "skipped": "Omitida",
        }.get(str(getattr(entry, "presentation_state", "")), str(getattr(entry, "queue_state", "")))

    def ensure_loaded(self):
        if self._snapshot is None and not self._busy:
            self.refresh()

    def activate(self):
        self.ensure_loaded()
        if self._available:
            self._refresh_timer.start()

    def deactivate(self):
        self._refresh_timer.stop()

    def set_busy(self, value):
        self._busy = bool(value)
        self._update_controls()

    def _refresh_if_idle(self):
        if not self._busy and self.isVisible():
            self.refresh(silent=True)

    def _dispatch(self, operation, kind, success_message=None):
        if self._busy or not self._available:
            return
        self._pending_success_message = success_message
        self._run(operation, kind)

    def refresh(self, _checked=False, *, silent=False):
        self._dispatch(
            lambda: self.facade.queue_snapshot(),
            "queue_refresh",
            None if silent else "Cola actualizada",
        )

    def _current_entry(self):
        item = self.items.currentItem()
        value = item.data(0, Qt.UserRole) if item is not None else None
        return value if hasattr(value, "queue_item_id") else None

    def _selection_changed(self):
        if self._rendering:
            return
        entry = self._current_entry()
        self._selection_id = entry.queue_item_id if entry is not None else None
        self._update_controls()

    def _find_item(self, queue_item_id):
        if queue_item_id is None:
            return None
        for index in range(self.items.topLevelItemCount()):
            item = self.items.topLevelItem(index)
            entry = item.data(0, Qt.UserRole)
            if getattr(entry, "queue_item_id", None) == queue_item_id:
                return item
        return None

    def render(self, snapshot):
        selected_id = self._selection_id
        self._snapshot = snapshot
        self._rendering = True
        try:
            self.items.clear()
            for entry in snapshot.entries:
                number = (
                    f"Ejecución {entry.execution_number}"
                    if entry.execution_number is not None
                    else "Ejecución sin número"
                )
                item = QTreeWidgetItem(
                    (
                        str(entry.position + 1),
                        self._project_label(entry.project_id),
                        number,
                        self._entry_label(entry),
                    )
                )
                item.setData(0, Qt.UserRole, entry)
                detail = entry.detail
                if entry.terminal_reason:
                    detail = (detail + " " if detail else "") + entry.terminal_reason
                item.setToolTip(3, detail)
                item.setToolTip(1, entry.project_id)
                if entry.is_active:
                    font = QFont(item.font(0))
                    font.setBold(True)
                    for column in range(4):
                        item.setFont(column, font)
                self.items.addTopLevelItem(item)
            selected_item = self._find_item(selected_id)
            if selected_item is not None:
                self.items.setCurrentItem(selected_item)
                self._selection_id = selected_id
            else:
                self._selection_id = None
        finally:
            self._rendering = False
        self.global_state.setText(
            "Estado global: " + self._global_label(snapshot.state)
        )
        self.global_detail.setText(snapshot.detail)
        self.status.setText("Cola cargada")
        self._update_controls()

    def handle_result(self, result):
        if not isinstance(result, QueueOperationResult):
            self.show_error("resultado inesperado de la cola")
            return
        if result.selection is not None:
            self._selection_id = result.selection.queue_item_id
        if result.queue is not None:
            self.render(result.queue)
        if result.success:
            message = result.message or self._pending_success_message
            if message:
                self.status.setText(message)
        else:
            self.show_error(result.message or "la operación de cola falló")
        self._pending_success_message = None
        self._update_controls()

    def show_error(self, message):
        self._pending_success_message = None
        detail = str(message).strip()
        self.status.setText("Error en cola" + (f": {detail}" if detail else ""))

    def open_selected(self):
        entry = self._current_entry()
        if entry is None:
            return
        self._dispatch(
            lambda: self.facade.select_queue_item(entry.queue_item_id),
            "queue_select",
            "Selección de cola abierta",
        )

    def move_selected(self, delta):
        entry = self._current_entry()
        if entry is None or self._snapshot is None:
            return
        queued = [item for item in self._snapshot.entries if item.queue_state == "queued"]
        try:
            index = next(
                index for index, item in enumerate(queued) if item.queue_item_id == entry.queue_item_id
            )
        except StopIteration:
            return
        target = index + delta
        if not 0 <= target < len(queued):
            return
        queued[index], queued[target] = queued[target], queued[index]
        self._dispatch(
            lambda: self.facade.reorder_queue(
                tuple(item.queue_item_id for item in queued),
                selection_queue_item_id=entry.queue_item_id,
            ),
            "queue_reorder",
            "Orden de cola actualizado",
        )

    def pause_or_resume(self):
        if self._snapshot is None:
            return
        selected = self._selection_id
        if self._snapshot.paused:
            operation = lambda: self.facade.resume_queue(
                expected_revision=self._snapshot.revision,
                selection_queue_item_id=selected,
            )
            message = "Cola reanudada"
        else:
            operation = lambda: self.facade.pause_queue(
                expected_revision=self._snapshot.revision,
                selection_queue_item_id=selected,
            )
            message = "Cola pausada"
        self._dispatch(operation, "queue_pause_resume", message)

    def duplicate_selected(self):
        entry = self._current_entry()
        if entry is None:
            return
        self._dispatch(
            lambda: self.facade.duplicate_queue_item(entry.queue_item_id),
            "queue_duplicate",
            "Se creó y encoló una copia independiente",
        )

    def skip_selected(self):
        entry = self._current_entry()
        if entry is None:
            return
        self._dispatch(
            lambda: self.facade.skip_queue_item(
                entry.queue_item_id,
                reason="operator skipped from GUI",
            ),
            "queue_skip",
            "Item omitido",
        )

    def remove_selected(self):
        entry = self._current_entry()
        if entry is None:
            return
        self._dispatch(
            lambda: self.facade.remove_queue_item(
                entry.queue_item_id,
                reason="operator removed from GUI",
            ),
            "queue_remove",
            "Item removido",
        )

    def _update_controls(self):
        entry = self._current_entry()
        available = self._available and not self._busy
        self.refresh_button.setEnabled(available)
        if self._snapshot is None:
            self.pause_resume_button.setEnabled(False)
            self.pause_resume_button.setText("Pausar cola")
        else:
            self.pause_resume_button.setEnabled(available)
            self.pause_resume_button.setText(
                "Reanudar cola" if self._snapshot.paused else "Pausar cola"
            )
            self.pause_resume_button.setToolTip(
                "La pausa impide iniciar el próximo item; no cancela el activo."
            )
        self.open_button.setEnabled(available and bool(getattr(entry, "can_open", False)))
        self.move_up_button.setEnabled(available and bool(getattr(entry, "can_move_up", False)))
        self.move_down_button.setEnabled(available and bool(getattr(entry, "can_move_down", False)))
        self.duplicate_button.setEnabled(available and bool(getattr(entry, "can_duplicate", False)))
        self.skip_button.setEnabled(available and bool(getattr(entry, "can_skip", False)))
        self.remove_button.setEnabled(available and bool(getattr(entry, "can_remove", False)))


__all__ = ["QueuePanel"]
