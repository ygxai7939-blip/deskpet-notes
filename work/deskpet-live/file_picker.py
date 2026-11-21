"""File selection in the app's frameless dialog shell."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout

from desk_style import SheetDialog, button, label


FILE_STYLE = """
QFileDialog { background: transparent; }
QAbstractItemView {
  background: #f2f2f2; border: none; border-radius: 8px; padding: 2px;
  selection-background-color: #565656; selection-color: white;
}
QHeaderView { background: #f2f2f2; border: none; }
QHeaderView::section { background: #e9e9e9; border: none; padding: 5px 6px; }
QComboBox {
  min-height: 26px; background: #eeeeee; border: none; border-radius: 8px; padding: 1px 7px;
}
QComboBox::drop-down { width: 20px; border: none; }
QToolButton { background: #efefef; border: none; border-radius: 7px; padding: 4px; }
QToolButton:hover { background: #dedede; }
QPushButton { background: #eeeeee; border: none; border-radius: 9px; }
QPushButton:hover { background: #e0e0e0; }
QSplitter::handle { background: transparent; }
"""


def confirm_replace(parent, path):
    dialog = SheetDialog("替换文件", parent)
    dialog.setFixedWidth(420)
    message = label(f"「{Path(path).name}」已存在。要替换这个文件吗？", "dialogBody")
    message.setWordWrap(True)
    dialog.body.addWidget(message)
    row = QHBoxLayout()
    row.addStretch()
    cancel = button("取消", dialog.reject, "secondary")
    cancel.setDefault(True)
    row.addWidget(cancel)
    row.addWidget(button("替换", dialog.accept, "primary"))
    dialog.body.addLayout(row)
    try:
        return bool(dialog.exec())
    finally:
        dialog.deleteLater()


def pick_file(parent, title, filters, *, suggested_name=None):
    dialog = SheetDialog(title, parent)
    dialog.resize(700, 490)
    save = suggested_name is not None
    picker = QFileDialog(dialog)
    picker.setOption(QFileDialog.Option.DontUseNativeDialog)
    picker.setWindowFlags(Qt.WindowType.Widget)
    picker.setStyleSheet(FILE_STYLE)
    picker.setAcceptMode(QFileDialog.AcceptMode.AcceptSave if save else QFileDialog.AcceptMode.AcceptOpen)
    picker.setFileMode(QFileDialog.FileMode.AnyFile if save else QFileDialog.FileMode.ExistingFile)
    picker.setNameFilter(filters)
    for field, text in ((QFileDialog.DialogLabel.LookIn, "位置"),
                        (QFileDialog.DialogLabel.FileName, "文件名"),
                        (QFileDialog.DialogLabel.FileType, "文件类型"),
                        (QFileDialog.DialogLabel.Accept, "保存" if save else "打开"),
                        (QFileDialog.DialogLabel.Reject, "取消")):
        picker.setLabelText(field, text)
    if save:
        picker.setOption(QFileDialog.Option.DontConfirmOverwrite)
        picker.setDefaultSuffix(Path(suggested_name).suffix.lstrip("."))
        picker.selectFile(suggested_name)
    picker.accepted.connect(dialog.accept)
    picker.rejected.connect(dialog.reject)
    dialog.body.addWidget(picker, 1)
    try:
        while True:
            picker.show()
            if not dialog.exec():
                return ""
            selected = picker.selectedFiles()
            if not selected:
                return ""
            path = selected[0]
            if not save or not Path(path).exists() or confirm_replace(parent, path):
                return path
    finally:
        dialog.deleteLater()
