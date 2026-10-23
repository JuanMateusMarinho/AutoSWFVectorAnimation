"""Edit › Preferences… (Plan 7, spec §8.9, §8.11): the AI page (the NVIDIA key in Windows' credential store, the model,
Test connection), the Tablet page (Windows Ink or Wintab) and the Ruffle page (Plan 8: which Ruffle Open in Ruffle uses).
Network calls run on a thread; the window never waits."""
import threading

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from autoswf.ai import nvidia


class _Relay(QObject):
    """Brings a worker thread's result back to the GUI thread."""
    models = Signal(object)
    result = Signal(object)


class PreferencesDialog(QDialog):
    def __init__(self, settings_store: QSettings, parent=None, *, base_url: str = nvidia.BASE_URL):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.store, self.base_url = settings_store, base_url
        self.relay = _Relay()
        self.relay.models.connect(self._got_models)
        self.relay.result.connect(self._got_result)
        tabs = QTabWidget()
        ai = QWidget()
        form = QFormLayout(ai)
        self.provider = QComboBox()
        self.provider.addItem("NVIDIA (build.nvidia.com)")
        form.addRow("Provider", self.provider)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_key = QCheckBox("Show")
        self.show_key.toggled.connect(lambda on: self.key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        self.save_button = QPushButton("Save key")
        self.save_button.clicked.connect(self.save_key)
        self.remove_button = QPushButton("Remove key")
        self.remove_button.clicked.connect(self.remove_key)
        row = QHBoxLayout()
        for w in (self.key_edit, self.show_key, self.save_button, self.remove_button):
            row.addWidget(w)
        form.addRow("API key", row)
        self.model_box = QComboBox()
        self.model_box.setEditable(False)
        self.model_box.currentTextChanged.connect(lambda text: text and self.store.setValue("ai/model", text))
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_models)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_box, 1)
        model_row.addWidget(refresh)
        form.addRow("Model", model_row)
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self.test_connection)
        form.addRow("", self.test_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        form.addRow("", self.status)
        note = QLabel("Your key is stored by Windows and is never saved in projects.")
        note.setWordWrap(True)
        form.addRow("", note)
        tabs.addTab(ai, "AI")
        tablet = QWidget()
        column = QVBoxLayout(tablet)
        self.wintab = QCheckBox("Use Wintab instead of Windows Ink (takes effect after restarting AutoSWF)")
        self.wintab.setChecked(str(self.store.value("tablet/wintab", False)).lower() in ("true", "1"))
        self.wintab.toggled.connect(lambda on: self.store.setValue("tablet/wintab", on))
        column.addWidget(self.wintab)
        column.addStretch(1)
        tabs.addTab(tablet, "Tablet")
        ruffle = QWidget()
        column = QVBoxLayout(ruffle)
        intro = QLabel("Open in Ruffle plays armors in this Ruffle. The Artix Games Launcher is one: choose its program "
                       "to test with the same Ruffle as AQW.")
        intro.setWordWrap(True)
        column.addWidget(intro)
        self.ruffle_label = QLabel()
        self.ruffle_label.setWordWrap(True)
        column.addWidget(self.ruffle_label)
        row = QHBoxLayout()
        choose = QPushButton("Choose…")
        choose.clicked.connect(self.choose_ruffle)
        default = QPushButton("Use the default")
        default.clicked.connect(self.default_ruffle)
        row.addWidget(choose)
        row.addWidget(default)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)
        tabs.addTab(ruffle, "Ruffle")
        self._show_ruffle()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        saved = self.store.value("ai/model", "")
        if saved:
            self.model_box.addItem(str(saved))
        self._show_key_state()

    def _key(self) -> str | None:
        try:
            return nvidia.load_key()
        except Exception:
            return None

    # ------------------------------------------------------------ Ruffle

    def _show_ruffle(self) -> None:
        from autoswf.ruffle import launch
        found = launch.find_ruffle(self.store.value(launch.SETTINGS_KEY) or None)
        self.ruffle_label.setText("Using: %s" % found if found is not None
                                  else "No Ruffle found. Choose the Artix Games Launcher's program or ruffle.exe.")

    def choose_ruffle(self) -> None:
        from autoswf.ruffle import launch
        path, _ = QFileDialog.getOpenFileName(self, "Choose Ruffle (the Artix Games Launcher or ruffle.exe)", "",
                                              "Programs (*.exe)")
        if path:
            self.store.setValue(launch.SETTINGS_KEY, path)
            self._show_ruffle()

    def default_ruffle(self) -> None:
        from autoswf.ruffle import launch
        self.store.remove(launch.SETTINGS_KEY)
        self._show_ruffle()

    def _show_key_state(self) -> None:
        has_key = self._key() is not None
        self.key_edit.setPlaceholderText("A key is saved" if has_key else "Paste your key from build.nvidia.com")
        self.remove_button.setEnabled(has_key)

    def save_key(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            return
        try:
            nvidia.save_key(key)
        except Exception as e:                       # the credential store refused
            self.status.setText("Windows could not store the key (%s)" % type(e).__name__)
            return
        self.key_edit.clear()
        self.status.setText("The key is saved.")
        self._show_key_state()

    def remove_key(self) -> None:
        nvidia.remove_key()
        self.status.setText("The key was removed.")
        self._show_key_state()

    def _in_thread(self, work) -> None:
        threading.Thread(target=work, daemon=True).start()

    def refresh_models(self) -> None:
        key = self._key()
        if key is None:
            self.status.setText("Save your key first.")
            return
        self.status.setText("Asking NVIDIA for the models…")

        def work():
            try:
                self.relay.models.emit(nvidia.list_models(key, base_url=self.base_url))
            except Exception as e:
                self.relay.models.emit(e)
        self._in_thread(work)

    def _got_models(self, models) -> None:
        if isinstance(models, Exception):
            self.status.setText("Could not list the models (%s)." % type(models).__name__)
            return
        saved = str(self.store.value("ai/model", "") or "")
        choice = saved or nvidia.preferred_model(models) or (models[0] if models else "")
        self.model_box.blockSignals(True)
        self.model_box.clear()
        self.model_box.addItems(models)
        if saved and saved not in models:
            self.model_box.addItem(saved)
            self.status.setText("%s is not in NVIDIA's list right now." % saved)
        else:
            self.status.setText("%d models." % len(models))
        self.model_box.setCurrentText(choice)
        self.model_box.blockSignals(False)
        if choice:
            self.store.setValue("ai/model", choice)

    def test_connection(self) -> None:
        key, model = self._key(), self.model_box.currentText()
        if key is None or not model:
            self.status.setText("Save your key and pick a model first.")
            return
        self.status.setText("Testing…")
        self._in_thread(lambda: self.relay.result.emit(nvidia.check_connection(key, model, base_url=self.base_url)))

    def _got_result(self, result) -> None:
        self.status.setText(result.message)
