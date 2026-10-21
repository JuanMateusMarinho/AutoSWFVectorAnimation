"""The Export SWF dialog (spec §13): file and link names checked as they are typed, Helm or Helm morph, back hair,
optional male and female versions, a summary of the colorable areas, then the report of every file written."""
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout)

from autoswf.aqw.contract import client_class_names, sanitize_link
from autoswf.parts.assemble import colorable_summary
from autoswf.project.export import GENDER_NAMES, default_variant, export_problems, pending_animation
from autoswf.project.settings import Adjust, Variant

KINDS = ("Helm", "Helm morph")


class ExportDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Export SWF")
        self.setMinimumWidth(620)
        settings = controller.settings
        self._client_names = self._load_client_names()
        self._link_by_hand = settings.export.link is not None
        self.file_edit = QLineEdit(str(settings.export_file()))
        self.browse_button = QPushButton("Browse…")
        self.link_edit = QLineEdit(settings.export_link() if self._safe_link() else "")
        self.link_message = QLabel()
        self.link_message.setWordWrap(True)
        self.kind_box = QComboBox()
        self.kind_box.addItems(KINDS)
        self.kind_box.setCurrentIndex(1 if settings.export.morph else 0)
        self.kind_box.setToolTip("A morph helm draws a whole head; the export checks that it covers the male and "
                                 "female base heads")
        self.back_hair_box = QCheckBox("Include back hair")
        has_back = controller.helm_build is not None and controller.helm_build.helm is not None \
            and controller.helm_build.helm.item.backhair is not None
        self.back_hair_box.setChecked(settings.export.back_hair)
        self.back_hair_box.setEnabled(has_back)
        if not has_back:
            self.back_hair_box.setToolTip("This helm has no back hair")
        self.variants_box = QCheckBox("Male and female versions (two files)")
        self.variants_box.setChecked(settings.export.variants)
        self.gender_rows: dict[str, tuple[QLineEdit, QLineEdit]] = {}
        self._follows: dict[QLineEdit, bool] = {}         # a version name follows the main one until named by hand
        grid = QGridLayout()
        grid.addWidget(QLabel("File"), 0, 1)
        grid.addWidget(QLabel("Link"), 0, 2)
        for row, g in enumerate(("M", "F"), start=1):
            default, saved = default_variant(settings, g), settings.export.genders.get(g)
            variant = saved or default
            file_edit, link_edit = QLineEdit(variant.file), QLineEdit(variant.link)
            self._follows[file_edit] = Path(variant.file) == Path(default.file)
            self._follows[link_edit] = variant.link == default.link
            for edit_ in (file_edit, link_edit):
                edit_.textEdited.connect(lambda _text, e=edit_: self._follows.__setitem__(e, False))
            grid.addWidget(QLabel(GENDER_NAMES[g].capitalize()), row, 0)
            grid.addWidget(file_edit, row, 1)
            grid.addWidget(link_edit, row, 2)
            file_edit.textEdited.connect(self._check)
            link_edit.textEdited.connect(self._check)
            self.gender_rows[g] = (file_edit, link_edit)
        self.versions_group = QGroupBox("Versions")
        versions = QVBoxLayout(self.versions_group)
        versions.addLayout(grid)
        hint = QLabel("Adjust each version on the canvas: pick the head with the Male/Female button, then use "
                      "Properties ▸ Adjust.")
        hint.setWordWrap(True)
        versions.addWidget(hint)
        self.summary_label = QLabel(self._summary())
        self.summary_label.setWordWrap(True)
        self.export_button = QPushButton("Export")
        self.export_button.setDefault(True)
        close = QPushButton("Close")
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("The report of the export appears here.")

        file_row = QHBoxLayout()
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(self.browse_button)
        form = QFormLayout()
        form.addRow("File", file_row)
        form.addRow("Link (class name)", self.link_edit)
        form.addRow("", self.link_message)
        form.addRow("Type", self.kind_box)
        form.addRow("", self.back_hair_box)
        form.addRow("", self.variants_box)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.export_button)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.versions_group)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.report, 1)
        layout.addLayout(buttons)

        self._updating = False
        self.file_edit.textChanged.connect(self._on_file)
        self.link_edit.textChanged.connect(self._on_link)
        self.browse_button.clicked.connect(self._browse)
        self.variants_box.toggled.connect(self._on_variants)
        self.export_button.clicked.connect(self.export)
        close.clicked.connect(self.reject)
        self._on_variants(self.variants_box.isChecked())

    # ------------------------------------------------------------ state

    def _load_client_names(self):
        client = self.controller.cache.client_path()
        if client is None:
            return ()
        from autoswf.swf.decode import MovieData
        try:
            return client_class_names(MovieData(client))
        except ValueError:
            return ()

    def _safe_link(self) -> bool:
        try:
            self.controller.settings.export_link()
            return True
        except ValueError:
            return False

    def _summary(self) -> str:
        build = self.controller.helm_build
        if build is None or build.helm is None:
            return "The helm is not built yet."
        lines = [colorable_summary(build.helm)]
        pending = pending_animation(build, self.controller.settings)
        if pending:
            lines.append("Not animated yet: %s (see AI suggestions)." % ", ".join(pending))
        return "\n".join(lines)

    def export_settings(self):
        """The export settings as the dialog shows them."""
        export = self.controller.settings.copy().export
        export.file = self.file_edit.text().strip() or None
        export.link = self.link_edit.text().strip() if self._link_by_hand else None
        export.morph = self.kind_box.currentIndex() == 1
        export.back_hair = self.back_hair_box.isChecked()
        export.variants = self.variants_box.isChecked()
        if export.variants or export.genders:
            genders = {}
            for g, (file_edit, link_edit) in self.gender_rows.items():
                old = export.genders.get(g)
                genders[g] = Variant(file_edit.text().strip(), link_edit.text().strip(),
                                     old.helm if old else Adjust(), dict(old.parts) if old else {})
            export.genders = genders
        return export

    def _candidate(self):
        settings = self.controller.settings.copy()
        settings.export = self.export_settings()
        if settings.export.link is None:
            try:
                settings.export.link = sanitize_link(Path(settings.export.file or "").stem)
            except ValueError:
                settings.export.link = ""
        return settings

    def _check(self) -> None:
        problems = export_problems(self._candidate(), self._client_names)
        self.link_message.setText("\n".join(problems))
        self.link_message.setStyleSheet("color: #f0b03c;" if problems else "")
        self.export_button.setEnabled(not problems and self.controller.helm_build is not None)

    # ------------------------------------------------------------ edits

    def _on_file(self, text: str) -> None:
        if not self._link_by_hand:
            self._updating = True
            try:
                self.link_edit.setText(sanitize_link(Path(text).stem))
            except ValueError:
                self.link_edit.setText("")
            self._updating = False
        self._refresh_versions()
        self._check()

    def _on_link(self, text: str) -> None:
        if self._updating:
            return
        self._link_by_hand = True
        self._refresh_versions()
        self._check()

    def _refresh_versions(self) -> None:
        """Version names follow the main file and link until edited (defaults <Name>M / <Name>F)."""
        file = Path(self.file_edit.text().strip() or "helm.swf")
        link = self.link_edit.text().strip()
        for g, (file_edit, link_edit) in self.gender_rows.items():
            if self._follows[file_edit]:
                file_edit.setText(str(file.with_name(file.stem + g + (file.suffix or ".swf"))))
            if self._follows[link_edit]:
                link_edit.setText(link + g if link else "")

    def _on_variants(self, on: bool) -> None:
        self.versions_group.setVisible(on)
        if on:
            self._refresh_versions()
        self._check()

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export SWF", self.file_edit.text(), "SWF files (*.swf)")
        if path:
            self.file_edit.setText(path)

    def export(self) -> None:
        export = self.export_settings()
        if export.to_dict() != self.controller.settings.export.to_dict():
            self.controller.change("Export settings", lambda s: setattr(s, "export", export))
        self.export_button.setEnabled(False)
        self.report.setPlainText("Exporting…")
        self.controller.export(self._on_exported)

    def _on_exported(self, results) -> None:
        lines = []
        for r in results:
            lines.append(r.summary())
            lines += ["  " + n for n in r.notes]
        self.report.setPlainText("\n".join(lines))
        self._check()
