from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from eurorack_inventory.domain.models import NormalizedBomItem
from eurorack_inventory.services.bom_matching import BomMatchingService, ScoredMatch
from eurorack_inventory.repositories.bom import BomRepository
from eurorack_inventory.repositories.parts import PartRepository


class BomMatchDialog(QDialog):
    """Dialog for manually matching a BOM item to an inventory part."""

    def __init__(
        self,
        parent,
        *,
        item: NormalizedBomItem,
        matching_service: BomMatchingService,
        bom_repo: BomRepository,
        part_repo: PartRepository,
        bom_service=None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self.matching = matching_service
        self.bom_repo = bom_repo
        self.part_repo = part_repo
        self.bom_service = bom_service
        self.selected_part_id: int | None = None

        self.setWindowTitle("Match BOM Item")
        self.setMinimumSize(500, 400)

        # Item info
        info = QLabel(
            f"<b>{item.normalized_value}</b> | "
            f"Type: {item.component_type or '?'} | "
            f"Qty: {item.qty} | "
            f"Package: {item.package_hint or '?'}"
        )

        # Search
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search inventory parts...")
        self.search_edit.setText(item.normalized_value)
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._do_search)
        self.search_edit.returnPressed.connect(self._do_search)
        search_layout.addWidget(self.search_edit)
        search_layout.addWidget(search_btn)

        # Candidate list
        self.candidate_list = QListWidget()
        self.candidate_list.itemDoubleClicked.connect(self._on_double_click)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.match_btn = QPushButton("Match Selected")
        self.match_btn.clicked.connect(self._match_selected)
        self.skip_btn = QPushButton("Skip Item")
        self.skip_btn.clicked.connect(self._skip_item)
        self.create_btn = QPushButton("Create Part...")
        self.create_btn.clicked.connect(self._create_and_match)
        if bom_service is None:
            self.create_btn.setEnabled(False)
        self.unmatch_btn = QPushButton("Unmatch")
        self.unmatch_btn.clicked.connect(self._unmatch_item)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.match_btn)
        btn_layout.addWidget(self.skip_btn)
        btn_layout.addWidget(self.create_btn)
        btn_layout.addWidget(self.unmatch_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(search_layout)
        layout.addWidget(QLabel("Candidates:"))
        layout.addWidget(self.candidate_list)
        layout.addLayout(btn_layout)

        # Initial search
        self._do_search()

    def _do_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        self.candidate_list.clear()
        candidates = self.matching.find_candidates(
            query,
            component_type=self.item.component_type,
            package_hint=self.item.package_hint,
        )
        for candidate in candidates:
            part = self.part_repo.get_part_by_id(candidate.part_id)
            if part is None:
                continue
            label = (
                f"{part.name} | {part.category or '?'} | "
                f"pkg={part.default_package or '?'} | "
                f"qty={part.qty} | score={candidate.score:.0f} ({candidate.reason})"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, candidate)
            self.candidate_list.addItem(item)

    def _on_double_click(self, list_item: QListWidgetItem) -> None:
        self._match_selected()

    def _match_selected(self) -> None:
        current = self.candidate_list.currentItem()
        if current is None:
            return
        candidate: ScoredMatch = current.data(Qt.UserRole)
        with self.bom_repo.db.transaction():
            self.bom_repo.link_to_part(
                self.item.id,
                candidate.part_id,
                candidate.score / 100.0,
                "manually_matched",
            )
            self.bom_repo.update_normalized_item(self.item.id, is_verified=True)
        self.accept()

    def _skip_item(self) -> None:
        with self.bom_repo.db.transaction():
            self.bom_repo.update_normalized_item(
                self.item.id,
                match_status="skipped",
                is_verified=True,
            )
        self.accept()

    def _create_and_match(self) -> None:
        from eurorack_inventory.ui.part_dialog import PartDialog

        dialog = PartDialog(self)
        # Pre-fill from BOM item
        dialog.name_edit.setText(self.item.normalized_value)
        dialog.category_combo.setCurrentText(self.item.component_type or "")
        dialog.package_combo.setCurrentText(self.item.package_hint or "")
        dialog.qty_spin.setValue(0)
        dialog.qty_spin.setEnabled(False)
        if self.item.tayda_pn:
            dialog.supplier_name_edit.setText("Tayda")
            dialog.supplier_sku_edit.setText(self.item.tayda_pn)
        elif self.item.mouser_pn:
            dialog.supplier_name_edit.setText("Mouser")
            dialog.supplier_sku_edit.setText(self.item.mouser_pn)

        if dialog.exec() != PartDialog.DialogCode.Accepted:
            return

        fields = dialog.get_fields()
        self.bom_service.create_part_and_match(self.item.id, fields)
        self.accept()

    def _unmatch_item(self) -> None:
        with self.bom_repo.db.transaction():
            self.bom_repo.unlink_part(self.item.id)
            self.bom_repo.update_normalized_item(self.item.id, is_verified=False)
        self.accept()
