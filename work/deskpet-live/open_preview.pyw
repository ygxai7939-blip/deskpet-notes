from pathlib import Path
import json
import os
import sys
import traceback

from app_version import APP_VERSION


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT.parent / "deskpet-zh"
FROZEN = getattr(sys, "frozen", False)
DATA = Path(os.environ.get("DESKPET_DATA_DIR") or (
    Path(os.environ["LOCALAPPDATA"]) / "DeskPetNotes" if FROZEN else ROOT
)).resolve()
LIBRARY = DATA / "library"
PACK = LIBRARY / "dimple.codex-pet.zip"
SETTINGS_FILE = DATA / "settings" / "settings.json"
STATUS = DATA / "preview-status.json"


def restore_position(widget):
    path = DATA / "relaunch-position.json"
    if not path.exists():
        return
    import ctypes
    from ctypes import wintypes

    x, y = json.loads(path.read_text(encoding="utf-8"))
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.SetWindowPos.restype = wintypes.BOOL
    no_size_no_order_no_focus = 0x0001 | 0x0004 | 0x0010
    if user32.SetWindowPos(int(widget.winId()), None, x, y, 0, 0, no_size_no_order_no_focus):
        widget._ps.x, widget._ps.y = float(widget.x()), float(widget.y())
        geometry = widget.screen().availableGeometry()
        widget._ps.sx, widget._ps.sy = geometry.x(), geometry.y()
        widget._ps.sw, widget._ps.sh = geometry.width(), geometry.height()
    path.unlink(missing_ok=True)


def snapshot(studio):
    widget = studio.pet
    if not FROZEN and studio.panel.isVisible():
        output = ROOT.parents[1] / "outputs" / "桌宠便签-运行截图.png"
        studio.panel.grab().save(str(output))
    data = {
        "pid": os.getpid(),
        "version": APP_VERSION,
        "vers": "DeskPet + DeskStickyNotes / note library, edge tabs, paper feed and pixel snow preview",
        "title": widget.windowTitle(),
        "visible": widget.isVisible(),
        "window": [widget.x(), widget.y(), widget.width(), widget.height()],
        "panel_visible": studio.panel.isVisible(),
        "note_count": len(studio.store.records),
    }
    STATUS.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def run():
    from PySide6.QtCore import QLockFile, QTimer
    from desk_style import create_ui_application

    DATA.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(DATA / ".deskpet.lock"))
    lock.setStaleLockTime(0)
    activation = DATA / ".show-panel"
    if not lock.tryLock(100):
        activation.touch()
        return 0
    from data_backup import recover_restore
    recover_restore(DATA)
    LIBRARY.mkdir(exist_ok=True)
    if not FROZEN:
        sys.path.insert(0, str(RUNTIME))
    from core import settings
    from core.bundle import CHARACTER_LOAD_ERRORS
    from desk_workspace import DeskWorkspace
    from platforms.windows.desktop_pet import DesktopPet

    app = create_ui_application("DeskPet")
    app.setApplicationDisplayName("桌宠便签")
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    preferences = settings.load(SETTINGS_FILE)
    previous = preferences.get("pet_path")
    saved = Path(previous).resolve() if isinstance(previous, str) and previous else None
    widget = DesktopPet(None, preferences["pet_scale"], preferences, library=LIBRARY,
                        settings_file=SETTINGS_FILE, launch_script=Path(__file__).resolve(),
                        startup_file=(Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/DeskPetNotes.bat")
                        if FROZEN else None)
    installed = widget.character_paths()
    for chosen in dict.fromkeys((saved, PACK, *installed)):
        if chosen not in installed:
            continue
        try:
            loaded = widget.load_character(chosen)
        except CHARACTER_LOAD_ERRORS:
            continue
        widget._switch_pet(chosen, loaded=loaded)
        widget.show()
        restore_position(widget)
        break
    else:
        widget._switch_pet(None)
    studio = DeskWorkspace(app, widget, DATA / "settings" / "notes.json")
    if not widget.has_character or "--show-settings" in sys.argv[1:]:
        studio.panel.change_page(1)
    studio.open_panel()

    def reopen():
        if activation.exists():
            activation.unlink(missing_ok=True)
            studio.open_panel()

    bring_front = QTimer(interval=500)
    bring_front.timeout.connect(reopen)
    bring_front.start()
    QTimer.singleShot(420, lambda: snapshot(studio))
    try:
        return app.exec()
    finally:
        studio.shutdown()


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception:
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "preview-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
