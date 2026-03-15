from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.services.settings import ClassifierSettings, SettingsRepository

_STORAGE_CLASS_LABELS = {
    StorageClass.SMALL_SHORT_CELL: "Small cell",
    StorageClass.LARGE_CELL: "Large cell",
    StorageClass.LONG_CELL: "Long cell",
    StorageClass.BINDER_CARD: "Binder card",
}


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings_repo: SettingsRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings_repo = settings_repo
        self.setWindowTitle("Classifier Settings")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- Quantity thresholds ---
        thresh_box = QGroupBox("Quantity Thresholds")
        thresh_form = QFormLayout(thresh_box)

        self._spin_small_comp = QSpinBox()
        self._spin_small_comp.setRange(1, 10000)
        self._spin_small_comp.setToolTip(
            "SMT passives with this many or more units are assigned to large cells"
        )
        thresh_form.addRow("Small component limit:", self._spin_small_comp)

        self._spin_dip_ic = QSpinBox()
        self._spin_dip_ic.setRange(1, 10000)
        self._spin_dip_ic.setToolTip(
            "DIP ICs with fewer than this many units go to small cells instead of binders"
        )
        thresh_form.addRow("DIP IC qty limit:", self._spin_dip_ic)

        self._spin_th_small = QSpinBox()
        self._spin_th_small.setRange(1, 10000)
        self._spin_th_small.setToolTip(
            "Through-hole parts with fewer than this many units go to small cells instead of long cells"
        )
        thresh_form.addRow("Through-hole small qty limit:", self._spin_th_small)

        layout.addWidget(thresh_box)

        # --- Default assignment targets ---
        target_box = QGroupBox("Default Storage Targets")
        target_form = QFormLayout(target_box)

        self._combo_ic = self._make_storage_combo()
        target_form.addRow("ICs / Semiconductors:", self._combo_ic)

        self._combo_mechanical = self._make_storage_combo()
        target_form.addRow("Mechanical (switches, pots…):", self._combo_mechanical)

        self._combo_long = self._make_storage_combo()
        target_form.addRow("Through-hole long parts:", self._combo_long)

        self._combo_passive = self._make_storage_combo()
        target_form.addRow("Small passives (SMT, caps…):", self._combo_passive)

        layout.addWidget(target_box)

        # --- Buttons ---
        btn_row = QHBoxLayout()

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

    def _make_storage_combo(self) -> QComboBox:
        combo = QComboBox()
        for sc in StorageClass:
            combo.addItem(_STORAGE_CLASS_LABELS[sc], sc.value)
        return combo

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _load_settings(self) -> None:
        s = self.settings_repo.get_classifier_settings()
        self._spin_small_comp.setValue(s.small_component_qty_limit)
        self._spin_dip_ic.setValue(s.dip_ic_qty_limit)
        self._spin_th_small.setValue(s.through_hole_small_qty_limit)
        self._apply_rules_to_combos(s.category_rules)

    def _apply_rules_to_combos(self, rules: list[dict]) -> None:
        """Map category_rules list back to the four combo boxes."""
        combos = [self._combo_ic, self._combo_mechanical, self._combo_long, self._combo_passive]
        for i, combo in enumerate(combos):
            if i < len(rules):
                self._set_combo_value(combo, rules[i].get("target", StorageClass.SMALL_SHORT_CELL.value))

    def _build_rules_from_combos(self, base_rules: list[dict]) -> list[dict]:
        """Rebuild category_rules from the combo box selections."""
        combos = [self._combo_ic, self._combo_mechanical, self._combo_long, self._combo_passive]
        rules = []
        for i, combo in enumerate(combos):
            if i < len(base_rules):
                rule = dict(base_rules[i])
            else:
                rule = {}
            rule["target"] = combo.currentData()
            rules.append(rule)
        return rules

    def _reset_defaults(self) -> None:
        defaults = ClassifierSettings()
        self._spin_small_comp.setValue(defaults.small_component_qty_limit)
        self._spin_dip_ic.setValue(defaults.dip_ic_qty_limit)
        self._spin_th_small.setValue(defaults.through_hole_small_qty_limit)
        self._apply_rules_to_combos(defaults.category_rules)

    def _save(self) -> None:
        current = self.settings_repo.get_classifier_settings()
        settings = ClassifierSettings(
            small_component_qty_limit=self._spin_small_comp.value(),
            dip_ic_qty_limit=self._spin_dip_ic.value(),
            through_hole_small_qty_limit=self._spin_th_small.value(),
            category_rules=self._build_rules_from_combos(current.category_rules),
        )
        self.settings_repo.save_classifier_settings(settings)
        self.accept()
