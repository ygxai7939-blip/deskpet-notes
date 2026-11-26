"""Smoke test the integrated Windows UI with test-only note data."""
from pathlib import Path
from shutil import copyfile
from io import BytesIO
import json
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image, ImageDraw
from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt, QVariantAnimation
from PySide6.QtGui import QEnterEvent, QFontDatabase, QMouseEvent, QTextBlockFormat, QTextCursor, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

root = Path(__file__).resolve().parent
runtime = root.parent / "deskpet-zh"
sys.path.insert(0, str(runtime))

import desk_workspace
from desk_style import create_ui_application
from edge_notes import TAB_STEP
from paper_feed import HOLD_MS, SWALLOW_MS
from pet_packages import HD_CELL, LEGACY_ACTIONS, read_package
from pixel_snow import Flake
from sticky_store import Note, NoteStore, tag_key


from core import settings
from core.state import PetState
from data_backup import stage_backup
from platforms.windows.desktop_pet import DesktopPet


def verify_playback():
    anims = {name: (row, 6 if name == "idle" else 4, fps)
             for name, (row, fps) in LEGACY_ACTIONS.items()}
    pet_state = PetState(0, 0, 800, 600, 96, 104, anims=anims)
    pet_state.tick(.34)
    assert pet_state.fidx == 2
    pet_state.enter("idle")
    assert pet_state.fidx == 2
    pet_state.tick(.16)
    assert pet_state.fidx == 3
    pet_state.on_release()
    pet_state.tick(.22)
    pet_state.on_release()
    pet_state.tick(.27)
    assert pet_state.anim == "waving" and pet_state.fidx == 3
    pet_state.tick(.01)
    assert pet_state.anim == "idle" and pet_state.fidx == 0
    pet_state.enter("sleeping")
    pet_state.tick(2.0)
    assert pet_state.anim == "failed" and pet_state.fidx == 3
    pet_state.on_release()
    assert pet_state.anim == "waiting"
    assert not pet_state.can_pet
    pet_state.on_release("petting")
    assert pet_state.anim == "review"
    pet_state.on_drag_start()
    pet_state.tick(.9)
    assert pet_state.anim == "jumping" and pet_state.fidx == 2
    pet_state.on_release()
    assert pet_state.anim == "jumping" and pet_state.fidx == 2
    pet_state.tick(.11)
    assert pet_state.anim == "jumping" and pet_state.fidx == 3
    pet_state.tick(.10)
    assert pet_state.anim == "idle"
    x, y = pet_state.x, pet_state.y
    pet_state.update_cursor(x + 1, y - 100)
    pet_state.enter("chasing")
    pet_state.tick(.20)
    pet_state.update_cursor(pet_state.x - 1, y - 100)
    pet_state.tick(.01)
    assert pet_state.anim == "run_right" and pet_state.fidx == 2
    pet_state.update_cursor(pet_state.x - 100, y - 100)
    pet_state.tick(.01)
    assert pet_state.anim == "run_left" and pet_state.fidx == 2


def make_hd_role(destination):
    actions = {action: {"row": row, "frames": 10 if action == "waving" else 3, "fps": fps}
               for action, (row, fps) in LEGACY_ACTIONS.items()}
    for action in ("petting", "lifted", "landing", "waking", "celebrate"):
        actions[action] = {"row": len(actions), "frames": 3, "fps": 10}
    width, height = HD_CELL
    image = Image.new("RGBA", (width * 10, height * len(actions)))
    pen = ImageDraw.Draw(image)
    for clip in actions.values():
        for col in range(clip["frames"]):
            x, y = col * width, clip["row"] * height
            pen.ellipse((x + 80, y + 90 - col, x + 304, y + 320 - col),
                        fill=(128, 128, 128, 255))
    image_file = BytesIO()
    image.save(image_file, "WEBP", lossless=True)
    metadata = {"id": "qa-hd", "displayName": "高清测试角色", "spritesheetPath": "spritesheet.webp",
                "schemaVersion": 2, "frameSize": HD_CELL, "actions": actions}
    with ZipFile(destination, "w") as archive:
        archive.writestr("pet.json", json.dumps(metadata))
        archive.writestr("spritesheet.webp", image_file.getvalue())


def verify_character_interactions(studio, scratch):
    source = scratch / "test-hd.zip"
    make_hd_role(source)
    pack = read_package(source)
    assert pack.cell_size == HD_CELL and len(pack.action_frames("waving")) == 10
    pet = studio.pet
    installed = pack.install(pet.library)
    assert read_package(installed).animations == pack.animations
    studio.select_character(installed)
    assert pet._anims == pack.animations and pet._frames[0][0].width() == pet.width() * 2
    preview = desk_workspace.CharacterActions(pack, studio.panel)
    preview.choice.select("waving", notify=True)
    for _ in range(10):
        preview.sprite.advance()
    assert preview.sprite.position == 9 and preview.play_button.text() == "重播"
    preview.play_button.click()
    assert preview.sprite.position == 0
    preview.reject()

    def mouse_move(local, buttons):
        global_point = pet.mapToGlobal(local)
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(global_point),
                            Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(pet, event)

    pet.apply_movement(False)
    pet._ps.enter("idle")
    pos = pet.rect().center()
    QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=pos)
    mouse_move(pos + QPoint(1, 0), Qt.MouseButton.LeftButton)
    assert not pet._ps.is_dragging
    QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=pos)
    assert pet._click_timer.isActive()
    QTest.qWait(QApplication.doubleClickInterval() + 70)
    assert pet._ps.anim == "waving"

    QTest.mouseClick(pet, Qt.MouseButton.LeftButton, pos=pos)
    assert pet._click_timer.isActive()
    QTest.mouseDClick(pet, Qt.MouseButton.LeftButton, pos=pos)
    app.processEvents()
    assert not pet._click_timer.isActive() and studio.panel.isVisible()

    QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=pos)
    mouse_move(pos - QPoint(QApplication.startDragDistance() + 6, 0), Qt.MouseButton.LeftButton)
    assert pet._ps.is_dragging and pet._ps.anim == "lifted"
    QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=pos)
    assert not pet._ps.is_dragging and pet._ps.anim == "landing"
    pet._ps.enter("sleeping")
    pet.react("action")
    assert pet._ps.anim == "waking"
    pet._ps.enter("idle")
    y = pet.height() // 3
    for x in (pet.width() // 3, pet.width() * 2 // 3, pet.width() // 3):
        mouse_move(QPoint(x, y), Qt.MouseButton.NoButton)
    assert pet._ps.anim == "petting"

    note = studio.new_note()
    editor = studio.windows[note.id].editor
    editor.setPlainText("第一项\n第二项")
    editor.moveCursor(QTextCursor.MoveOperation.Start)
    editor.checklist_at_cursor()
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.checklist_at_cursor()
    editor.checklist_at_cursor()
    assert pet._ps.anim != "celebrate"
    editor.moveCursor(QTextCursor.MoveOperation.Start)
    editor.checklist_at_cursor()
    assert pet._ps.anim == "celebrate"
    assert studio.flush()

    backup = scratch / "test-hd-backup.zip"
    studio.save_backup_file(backup)
    with TemporaryDirectory(dir=scratch) as temp:
        recovered = stage_backup(backup, Path(temp))
        assert recovered.active == installed.name
        assert read_package(recovered.root / "incoming" / "library" / installed.name).animations == pack.animations


verify_playback()
app = create_ui_application("DeskPet notes smoke")
app.setEffectEnabled(Qt.UIEffect.UI_General, True)
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyhbd.ttc")
app.setQuitOnLastWindowClosed(False)
with TemporaryDirectory(dir=root) as scratch:
    scratch = Path(scratch)
    path = scratch / "settings" / "notes.json"
    settings_file = scratch / "settings" / "settings.json"
    startup_file = scratch / "startup" / "DeskPet.bat"
    library = scratch / "library"
    library.mkdir()
    original = library / "atlas-example.codex-pet.zip"
    copyfile(root.parent / "release" / "example.codex-pet.zip", original)
    original_bytes = original.read_bytes()
    pet = DesktopPet(original, .5, settings.load(settings_file), library=library,
                     settings_file=settings_file, launch_script=root / "open_preview.pyw",
                     startup_file=startup_file)
    pet.show()
    studio = desk_workspace.DeskWorkspace(app, pet, path, tray=False, hotkeys=False)
    assert studio.panel.findChild(desk_workspace.QLabel, "publisherCredit").text() == "Ygxai"
    assert studio.pet._anims["idle"][1] == 4
    pet_menu = studio.pet_menu()
    assert "新建便签" in [a.text() for a in pet_menu.actions()]
    pet_settings = next(action.menu() for action in pet_menu.actions() if action.text() == "宠物设置")
    startup = next(action for action in pet_settings.actions() if action.text() == "开机启动")
    startup.trigger()
    assert str(root / "open_preview.pyw") in startup_file.read_text(encoding="utf-8")
    startup.trigger()
    assert not startup_file.exists()
    pet_menu.deleteLater()
    studio.panel.change_page(1)
    studio.panel.hide()
    QTest.mouseDClick(pet, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert studio.panel.isVisible() and studio.panel.pages.currentIndex() == 0
    assert not studio.store.records
    first = studio.new_note()
    first_window = studio.windows[first.id]
    footer = first_window.findChildren(QPushButton, "noteAction")
    assert [button.accessibleName() for button in footer] == ["归档便签", "删除便签"]
    assert all(not button.text() and not button.icon().isNull() for button in footer)
    assert first_window.saved.accessibleName() == "保存中…"
    assert studio.flush() and first_window.saved.accessibleName() == "已保存"
    assert not first_window.saved.text() and not first_window.saved.pixmap().isNull()
    actions = first_window.options_menu()
    next(action for action in actions.actions() if action.text() == "收起便签").trigger()
    actions.deleteLater()
    assert not first_window.isVisible()
    QTest.qWait(100)
    QTest.mouseDClick(pet, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert studio.panel.isVisible() and not studio.windows[first.id].isVisible()
    studio.panel.note_cards[first.id].open_button.click()
    assert len(studio.store.records) == 1 and studio.windows[first.id].isVisible()
    for index, (title, body) in enumerate((
        ("桌宠界面验收", "看看示例角色的浮窗、菜单和桌面便签"),
        ("素材整理", "把角色的图集和说明放到同一目录"),
        ("随手一记", "稍后把今天的想法写下来"),
    )):
        item = first if index == 0 else studio.new_note()
        editor = studio.windows[item.id]
        editor.title_field.setText(title)
        editor.editor.setPlainText(body)
        editor.update_content()
    editor.editor.checklist_at_cursor()
    check_editor = editor.editor
    block = check_editor.document().firstBlock()
    caret = check_editor.cursorRect(QTextCursor(block))
    check_point = check_editor.check_box(block, caret).center().toPoint()
    assert block.blockFormat().marker() == QTextBlockFormat.MarkerType.Unchecked
    pixels = check_editor.viewport().grab().toImage()
    for y in range(check_point.y() - 3, check_point.y() + 4):
        for x in range(check_point.x() - 3, check_point.x() + 4):
            assert pixels.pixelColor(x, y).red() > 160, "Native checkbox is visible inside the custom outline"
    QTest.mouseClick(check_editor.viewport(), Qt.MouseButton.LeftButton, pos=check_point)
    assert block.blockFormat().marker() == QTextBlockFormat.MarkerType.Checked
    assert check_editor.spring.state() == QVariantAnimation.State.Running
    QTest.qWait(400)
    assert check_editor.spring_block is None
    QTest.mouseClick(check_editor.viewport(), Qt.MouseButton.LeftButton, pos=check_point)
    assert block.blockFormat().marker() == QTextBlockFormat.MarkerType.Unchecked
    app.setEffectEnabled(Qt.UIEffect.UI_General, False)
    QTest.mouseClick(check_editor.viewport(), Qt.MouseButton.LeftButton, pos=check_point)
    assert check_editor.spring.state() == QVariantAnimation.State.Stopped
    assert block.blockFormat().marker() == QTextBlockFormat.MarkerType.Checked
    app.setEffectEnabled(Qt.UIEffect.UI_General, True)

    check_editor.moveCursor(QTextCursor.MoveOperation.End)
    for row in ("22222", "33333"):
        QTest.keyClick(check_editor, Qt.Key.Key_Return)
        QTest.keyClicks(check_editor, row)
    document = check_editor.document()
    second, third = document.findBlockByNumber(1), document.findBlockByNumber(2)
    assert second.blockFormat().marker() == third.blockFormat().marker() == check_editor.unchecked
    caret = check_editor.cursorRect(QTextCursor(second))
    box_center = check_editor.check_box(second, caret).center().toPoint()
    QTest.mouseClick(check_editor.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(caret.left(), box_center.y()))
    assert check_editor.textCursor().block() == second
    assert second.blockFormat().marker() == check_editor.unchecked

    selection = QTextCursor(document)
    selection.setPosition(block.position() + 1)
    selection.setPosition(third.position() + 2, QTextCursor.MoveMode.KeepAnchor)
    check_editor.setTextCursor(selection)
    QTest.mouseClick(check_editor.viewport(), Qt.MouseButton.LeftButton, pos=box_center)
    assert second.blockFormat().marker() == check_editor.checked
    assert third.blockFormat().marker() == check_editor.unchecked
    assert check_editor.textCursor().position() == selection.position()
    check_editor.checklist_at_cursor()
    assert all(row.blockFormat().marker() == check_editor.checked for row in (block, second, third))
    check_editor.checklist_at_cursor()
    assert block.blockFormat().marker() == second.blockFormat().marker() == check_editor.checked
    assert third.blockFormat().marker() == check_editor.unchecked
    assert check_editor.textCursor().anchor() == selection.anchor()
    assert check_editor.textCursor().position() == selection.position()

    studio.show_note(item)
    QTest.qWait(100)
    QTest.mouseClick(check_editor.viewport(), Qt.MouseButton.LeftButton, pos=check_editor.viewport().rect().center())
    assert check_editor.hasFocus()
    QTest.mouseClick(editor.paper, Qt.MouseButton.LeftButton, pos=QPoint(5, editor.paper.height() // 2))
    assert not check_editor.hasFocus()
    QTest.mouseClick(check_editor.viewport(), Qt.MouseButton.LeftButton, pos=check_editor.viewport().rect().center())
    assert check_editor.hasFocus()
    QTest.mouseClick(editor.title_field, Qt.MouseButton.LeftButton, pos=editor.title_field.rect().center())
    assert editor.title_field.hasFocus() and not check_editor.hasFocus()
    QTest.mouseClick(check_editor.viewport(), Qt.MouseButton.LeftButton, pos=check_editor.cursorRect(QTextCursor(third)).center())
    editor.format_bar.show()
    bold = next(b for b in editor.findChildren(QPushButton) if b.text() == "B")
    weight = check_editor.fontWeight()
    QTest.mouseClick(bold, Qt.MouseButton.LeftButton)
    assert check_editor.fontWeight() != weight and not check_editor.hasFocus()
    check_editor.setTextCursor(QTextCursor(third))
    check_editor.setFocus()
    check = next(b for b in editor.findChildren(QPushButton)
                 if b.toolTip() == "在当前行插入清单或切换勾选")
    QTest.mouseClick(check, Qt.MouseButton.LeftButton)
    assert third.blockFormat().marker() == check_editor.checked and not check_editor.hasFocus()
    QTest.mouseClick(check, Qt.MouseButton.LeftButton)
    assert third.blockFormat().marker() == check_editor.unchecked
    editor.toggle_pin(True)
    assert item.topmost and editor.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    expanded_size = (editor.width(), editor.height())
    actions = editor.options_menu()
    next(action for action in actions.actions() if action.text() == "收起便签").trigger()
    actions.deleteLater()
    assert item.collapsed and not item.visible and not editor.isVisible()
    assert studio.flush()
    assert NoteStore(path).records[item.id].collapsed and not NoteStore(path).records[item.id].visible
    studio.show_note(item)
    assert not item.collapsed and (editor.width(), editor.height()) == expanded_size
    editor.set_color("鼠尾草")
    assert studio.flush()
    loaded = NoteStore(path)
    assert len(loaded.records) == 3
    persisted = loaded.records[item.id]
    assert persisted.title == "随手一记" and persisted.topmost and persisted.color == "鼠尾草"
    reopened = QTextDocument()
    reopened.setHtml(persisted.richContent)
    assert reopened.firstBlock().blockFormat().marker() == QTextBlockFormat.MarkerType.Checked
    assert reopened.findBlockByNumber(1).blockFormat().marker() == check_editor.checked
    assert reopened.findBlockByNumber(2).blockFormat().marker() == check_editor.unchecked
    editor.close()
    assert not item.visible and not editor.isVisible()
    studio.show_note(item)
    assert item.visible
    studio.panel.search.setText("素材")
    assert studio.panel.note_list.count() == 2
    studio.panel.search.clear()
    studio.panel.refresh()
    app.processEvents()
    main = studio.panel.findChild(desk_workspace.QFrame, "libraryCenter")
    aside = studio.panel.findChild(desk_workspace.QFrame, "libraryDetails")
    shell = studio.panel.shell
    snow = shell.snow
    assert snow.timer.isActive()
    samples = [QPoint(65, 270), main.mapTo(shell, QPoint(main.width() - 75, main.height() - 75)),
               aside.mapTo(shell, QPoint(12, 80))]
    saved_flakes = snow.flakes
    snow.flakes = [Flake(point.x(), point.y(), 3, 0.) for point in samples]
    rendered = studio.panel.grab().toImage()
    for point, contrast in zip(samples, (100, 16, 16)):
        bright = rendered.pixelColor(point)
        base = rendered.pixelColor(point + QPoint(18, 0))
        assert bright.alpha() == base.alpha() == 255
        assert bright.red() - base.red() >= contrast, (bright.getRgb(), base.getRgb())
        assert base.red() == base.green() == base.blue()
    snow.flakes = saved_flakes
    studio.panel.showMinimized()
    app.processEvents()
    assert not snow.timer.isActive()
    studio.open_panel()
    assert snow.timer.isActive()
    assert studio.panel.detail_pages.currentIndex() == 0
    card = studio.panel.note_cards[item.id]
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
    assert studio.panel.selected_note_id == item.id and card.property("selected")
    assert studio.panel.detail_title.text() == item.label
    assert studio.panel.detail_text.toPlainText() == item.textContent
    studio.panel.note_filters.button(2).click()
    assert not studio.panel.note_cards and studio.panel.detail_pages.currentIndex() == 0
    studio.panel.note_filters.button(0).click()
    assert len(studio.panel.note_cards) == 3
    studio.panel.pet_toggle.click()
    assert not pet.isVisible() and studio.panel.pet_toggle.text() == "显示"
    studio.panel.pet_toggle.click()
    assert pet.isVisible() and studio.panel.pet_toggle.text() == "收起"
    studio.refresh_notes()
    full_size = studio.panel.size()
    studio.panel.resize(studio.panel.minimumSize())
    QTest.qWait(45)
    studio.panel.note_list.activate()
    grid_cards = list(studio.panel.note_cards.values())
    assert grid_cards[0].geometry().right() < grid_cards[1].geometry().left()
    assert studio.panel.search.width() >= 126
    assert studio.panel.rect().contains(aside.mapTo(studio.panel, aside.rect().bottomRight()))
    studio.panel.resize(full_size)
    app.processEvents()

    def glide_between(highlight, first, second):
        highlight.clear()
        for widget in (first, second):
            QApplication.sendEvent(widget, QEnterEvent(QPointF(), QPointF(), QPointF()))
        assert highlight.target == second.geometry()
        assert highlight.glide.state() == QVariantAnimation.State.Running
        highlight.glide.setCurrentTime(highlight.glide.duration())
        assert highlight.geometry() == second.geometry()

    studio.open_panel()
    QTest.qWait(145)
    glide_between(studio.panel.note_glide,
                  studio.panel.note_list.itemAt(0).widget(), studio.panel.note_list.itemAt(1).widget())
    glide_between(studio.panel.nav_glide, studio.panel.group.button(0), studio.panel.group.button(1))
    studio.panel.change_page(1)
    assert studio.panel.group.button(1).isChecked() and studio.panel.pages.currentIndex() == 1
    assert studio.panel.pages.graphicsEffect() is None
    assert studio.panel.pet_options["size"].value == 0.5
    for name, menu in (("menu-qa", studio.pet_menu()), ("note-menu-qa", editor.options_menu()),
                       ("choice-qa", studio.panel.pet_options["size"].choices_menu())):
        menu.popup(pet.pos())
        app.processEvents()
        assert menu.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
        QTest.qWait(125)
        assert not menu.mask().contains(menu.rect().topLeft())
        options = [item for item in menu.actions() if item.isEnabled() and not item.isSeparator()
                   and item.menu() is None and item.text()]
        for option in options[:2]:
            menu.setActiveAction(option)
            menu.update_highlight()
        if len(options) > 1:
            assert menu.highlight.glide.state() == QVariantAnimation.State.Running, name
            menu.highlight.glide.setCurrentTime(menu.highlight.glide.duration())
        assert menu.highlight.geometry() == menu.actionGeometry(options[min(1, len(options) - 1)]).adjusted(1, 1, -1, -1)
        image = menu.grab()
        assert image.toImage().pixelColor(0, 0).alpha() == 0, name
        menu.hide()

    def drag_paper(source, origin):
        QTest.mousePress(source, Qt.MouseButton.MiddleButton, pos=origin)
        assert studio.paper_feed.source is source
        mouth = source.mapFromGlobal(pet.feed_anchor().toPoint())
        traced_move(source, mouth)
        assert studio.paper_feed.ghost.isVisible()
        assert studio.paper_feed.ghost.windowFlags() & Qt.WindowType.WindowTransparentForInput
        return mouth

    def traced_move(source, local):
        app.sendEvent(source, QMouseEvent(QEvent.Type.MouseMove, QPointF(local),
                                         QPointF(source.mapToGlobal(local)), Qt.MouseButton.NoButton,
                                         Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier))

    def release_paper(source, local):
        app.sendEvent(source, QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(local),
                                         QPointF(source.mapToGlobal(local)), Qt.MouseButton.MiddleButton,
                                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

    def finish_hover():
        # Advance the hold without introducing real desktop pointer events into the synthetic gesture.
        QTest.qSleep(HOLD_MS + 25)
        studio.paper_feed.animate()
        assert pet._feed_pose == "ready"

    target = studio.active_notes()[0]
    feed_window = studio.show_note(target)
    grip = feed_window.drag_grip
    center = grip.rect().center()
    mouth = drag_paper(grip, center)
    release_paper(grip, mouth)
    assert target.id in studio.store.records and feed_window.isVisible()
    assert feed_window.windowOpacity() == 1. and not studio.paper_feed.ghost.isVisible()
    mouth = drag_paper(grip, center)
    QTest.keyClick(grip, Qt.Key.Key_Escape)
    assert target.id in studio.store.records and feed_window.isVisible()
    assert feed_window.windowOpacity() == 1. and pet._feed_pose is None
    QTest.mouseRelease(grip, Qt.MouseButton.MiddleButton, pos=mouth)
    mouth = drag_paper(grip, center)
    finish_hover()
    traced_move(grip, mouth + QPoint(-90, 0))
    traced_move(grip, mouth)
    release_paper(grip, mouth)
    assert target.id in studio.store.records and pet._feed_pose is None
    mouth = drag_paper(grip, center)
    finish_hover()
    release_paper(grip, mouth)
    assert target.id not in studio.windows and target.id not in NoteStore(path).records
    QTest.qWait(SWALLOW_MS + 70)
    assert studio.undo_popup.isVisible()
    undo = next(button for button in studio.undo_popup.findChildren(QPushButton) if button.text() == "撤销")
    undo.click()
    assert NoteStore(path).records[target.id] == target
    assert not studio.undo_popup.isVisible()
    original_order = tuple(studio.store.records)
    saved_notes = path.read_bytes()
    with patch.object(studio.store, "save", side_effect=PermissionError("test")), \
         patch.object(desk_workspace, "show_warning") as warning:
        assert not studio.feed_note(target)
        warning.assert_called_once()
        assert studio.store.records[target.id] is target
        assert studio.last_fed_note is None
        assert tuple(studio.store.records) == original_order
        assert path.read_bytes() == saved_notes

    def cancel_delete():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, desk_workspace.SheetDialog)
        surface = dialog.surface.grab().toImage()
        assert surface.pixelColor(240, 35).alpha() == 255
        cancel = next(b for b in dialog.findChildren(QPushButton) if b.text() == "取消")
        assert cancel.isDefault()
        cancel.click()

    QTimer.singleShot(75, cancel_delete)
    studio.ask_delete(item)
    assert item.id in studio.store.records
    assert studio.delete_notes((item,))
    studio.flush()
    assert len(NoteStore(path).records) == 2

    with ZipFile(original) as installed:
        atlas = installed.read("spritesheet.webp")
    test_pack = scratch / "test-character.zip"
    metadata = {"id": "qa-character", "displayName": "测试角色", "spritesheetPath": "spritesheet.webp"}
    with ZipFile(test_pack, "w") as archive:
        archive.writestr("pet.json", json.dumps(metadata))
        archive.writestr("spritesheet.webp", atlas)
    assert read_package(test_pack).name == "测试角色"

    def confirm_preview(label):
        preview = app.activeModalWidget()
        assert isinstance(preview, desk_workspace.CharacterPreview)
        selected = next(button for button in preview.findChildren(QPushButton) if button.text() == label)
        selected.click()

    QTimer.singleShot(80, lambda: confirm_preview("取消"))
    studio.inspect_character(test_pack)
    assert pet._zip_path == original and not (pet.library / "qa-character.codex-pet.zip").exists()
    QTimer.singleShot(80, lambda: confirm_preview("安装并使用"))
    studio.inspect_character(test_pack)
    assert pet._zip_path == pet.library / "qa-character.codex-pet.zip"
    assert pet._name == "测试角色" and settings.load(settings_file)["pet_path"] == str(pet._zip_path)
    assert all(label.text() == "测试角色" for label in studio.panel.pet_names)
    imported = pet._zip_path
    studio.panel.change_page(1)
    app.processEvents()
    cards = studio.panel.character_grid.cards
    assert set(cards) == {original, imported}
    assert cards[imported].isChecked() and not cards[original].isChecked()
    assert cards[original].height() >= 150
    pet_page = studio.panel.pages.currentWidget()
    samples = [pet_page.mapTo(shell, QPoint(47, 112)), cards[original].mapTo(shell, QPoint(25, 45))]
    saved_flakes = snow.flakes
    snow.flakes = [Flake(point.x(), point.y(), 3, 0.) for point in samples]
    rendered = studio.panel.grab().toImage()
    snow.flakes = saved_flakes
    for point, contrast in zip(samples, (38, 20)):
        bright = rendered.pixelColor(point)
        base = rendered.pixelColor(point + QPoint(18, 0))
        assert bright.red() - base.red() >= contrast, (bright.getRgb(), base.getRgb())
    QTest.mouseClick(cards[original], Qt.MouseButton.LeftButton)
    assert pet._zip_path == original and settings.load(settings_file)["pet_path"] == str(original)
    assert cards[original].isChecked() and not cards[imported].isChecked()
    cards[imported].click()
    assert pet._zip_path == imported and cards[imported].isChecked()

    imported_bytes = imported.read_bytes()
    QTimer.singleShot(80, lambda: confirm_preview("另存为新角色"))
    studio.inspect_character(test_pack)
    duplicate = library / "qa-character-2.codex-pet.zip"
    cards = studio.panel.character_grid.cards
    assert set(cards) == {original, imported, duplicate}
    assert pet._zip_path == duplicate and cards[duplicate].isChecked()
    assert read_package(duplicate).pet_id == "qa-character-2"
    assert original.read_bytes() == original_bytes and imported.read_bytes() == imported_bytes

    QTimer.singleShot(80, lambda: confirm_preview("更新并使用"))
    studio.inspect_character(test_pack)
    assert pet._zip_path == imported and set(studio.panel.character_grid.cards) == {original, imported, duplicate}
    assert settings.load(settings_file)["pet_path"] == str(imported)
    assert len(NoteStore(path).records) == 2
    bad_pack = scratch / "malformed.zip"
    with ZipFile(bad_pack, "w") as archive:
        archive.writestr("pet.json", json.dumps(metadata))
        archive.writestr("extras.txt", "not declared in the manifest")
    try:
        read_package(bad_pack)
    except ValueError:
        pass
    else:
        raise AssertionError("A character ZIP with incorrect declared contents was accepted")

    screen, edge = studio.edge_notes.home_rail()
    area = screen.availableGeometry()
    note = studio.new_note(screen=screen)
    window = studio.windows[note.id]
    window.close()
    studio.edge_notes.refresh()
    rail = studio.edge_notes.rails[(screen, edge)]
    tab = rail.tabs[note.id]
    app.processEvents()
    assert tab.visibleRegion().contains(tab.rect().center())
    local = tab.rect().center()
    QTest.mouseClick(tab, Qt.MouseButton.LeftButton, pos=local)
    assert note.visible and tab.opened
    QTest.mouseDClick(tab, Qt.MouseButton.LeftButton, pos=local)
    QTest.mouseRelease(tab, Qt.MouseButton.LeftButton, pos=local)
    assert not note.visible and not tab.opened
    QTest.mouseClick(tab, Qt.MouseButton.LeftButton, pos=local)
    assert note.visible and tab.opened
    window.close()
    assert not note.visible and not tab.opened
    studio.panel.refresh()
    studio.panel.note_cards[note.id].open_button.click()
    assert window.isVisible() and tab.opened
    QTest.mouseClick(tab, Qt.MouseButton.LeftButton, pos=local)
    assert not window.isVisible() and not tab.opened

    def drag_to(widget, destination, *, send_move=True, check_preview=False):
        start = widget.mapToGlobal(widget.rect().center())
        for kind, point, changed_button, held in (
            (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseMove, destination, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseButtonRelease, destination, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
        ):
            if send_move or kind != QEvent.Type.MouseMove:
                app.sendEvent(widget, QMouseEvent(kind, QPointF(widget.mapFromGlobal(point)), QPointF(point),
                                                 changed_button, held, Qt.KeyboardModifier.NoModifier))
            if check_preview and kind == QEvent.Type.MouseMove:
                preview = studio.edge_notes.drag_preview
                assert preview.isVisible() and preview.windowFlags() & Qt.WindowType.WindowTransparentForInput
                assert len(preview.cards) >= 2 and not note.visible
                preview.motion.setCurrentTime(preview.motion.duration())
                assert preview.width() >= 250 and preview.height() >= 150
        if check_preview:
            assert not studio.edge_notes.drag_preview.isVisible() and not note.visible

    original_y = rail.y()
    drag_to(tab, tab.mapToGlobal(local) + QPoint(0, -72), check_preview=True)
    assert not note.visible and rail.y() < original_y
    drop_y = min(area.bottom(), rail.y() + tab.height() // 2)
    drag_to(tab, QPoint(area.left() + 10, drop_y))
    assert not note.visible and note.edge == "left"
    rail = studio.edge_notes.rails[(screen, "left")]
    assert rail.x() == area.left()
    QTest.mouseClick(rail.tabs[note.id], Qt.MouseButton.LeftButton, pos=local)
    assert note.visible and window.x() >= rail.x() + rail.width()
    assert studio.flush() and NoteStore(path).records[note.id].edge == "left"
    layout = settings.load(settings_file)["note_edge_layout"]
    assert layout["edge"] == "left" and layout["screen"] == screen.name()
    assert 0 <= layout["anchors"][screen.name()]["left"] <= 1
    assert studio.new_note(screen=screen).edge == "left"

    grip = window.drag_grip
    floating = area.center() - QPoint(window.width() // 2, window.height() // 2)

    def pull_away():
        drag_to(grip, floating + grip.mapTo(window, grip.rect().center()))
        assert note.visible and not note.edge
        app.processEvents()
        assert grip.x() == 0

    pull_away()
    drag_to(grip, QPoint(area.right() - 90, area.center().y()))
    assert note.edge == "right", (note.edge, window.geometry(), area)
    right_rail = studio.edge_notes.rails[(screen, "right")]
    assert window.geometry().right() + 1 == right_rail.x()
    drag_to(grip, grip.mapToGlobal(grip.rect().center()) + QPoint(0, 56))
    assert note.edge == "right"
    pull_away()
    drag_to(grip, QPoint(area.left() + rail.width() + 16, area.center().y()), send_move=False)
    assert note.edge == "left", "Releasing next to the left rail should reattach without a final move event"
    assert studio.flush() and NoteStore(path).records[note.id].edge == "left"

    for number in range(area.height() // TAB_STEP + 1):
        parked = Note(title=f"边缘便签 {number}", visible=False, edge="right", edgeScreen=screen.name())
        studio.store.records[parked.id] = parked
    attached_ids = []
    for _ in range(2):
        extra = studio.new_note(screen=screen)
        extra_window = studio.windows[extra.id]
        extra_grip = extra_window.drag_grip
        drag_to(extra_grip, floating + extra_grip.mapTo(extra_window, extra_grip.rect().center()))
        assert extra.visible and not extra.edge
        app.processEvents()
        drag_to(extra_grip, QPoint(area.right() - 90, area.center().y()))
        assert extra.edge == "right"
        crowded = studio.edge_notes.rails[(screen, "right")]
        assert crowded.scroll.verticalScrollBar().value() > 0
        extra_tab = crowded.tabs[extra.id]
        assert extra_tab.visibleRegion().contains(extra_tab.rect().center())
        attached_ids.append(extra.id)
        QTest.mouseClick(extra_tab, Qt.MouseButton.LeftButton, pos=extra_tab.rect().center())
        assert not extra_window.isVisible() and not extra_tab.opened
    assert all(note_id in crowded.tabs for note_id in attached_ids)
    assert studio.flush()
    assert all(NoteStore(path).records[note_id].edge == "right" for note_id in attached_ids)

    studio.open_note_library()
    panel = studio.panel
    assert not panel.delete_button.isEnabled()
    panel.selection_button.click()
    panel.note_cards[note.id].mark.click()
    panel.note_cards[extra.id].mark.click()
    assert panel.checked_notes == {note.id, extra.id} and panel.delete_button.isEnabled()
    panel.search.setText("边缘便签 0")
    assert not panel.checked_notes and not panel.delete_button.isEnabled()
    panel.search.clear()
    panel.note_cards[note.id].mark.click()
    panel.note_cards[extra.id].mark.click()

    def answer_batch_delete(caption):
        dialog = app.activeModalWidget()
        assert isinstance(dialog, desk_workspace.SheetDialog)
        message = dialog.findChild(desk_workspace.QLabel, "dialogBody")
        assert "2 张" in message.text()
        next(control for control in dialog.findChildren(QPushButton) if control.text() == caption).click()

    QTimer.singleShot(70, lambda: answer_batch_delete("取消"))
    panel.delete_button.click()
    assert panel.checked_notes == {note.id, extra.id}
    persisted_before = path.read_bytes()
    with patch.object(studio.store, "save", side_effect=PermissionError("test")), \
         patch.object(desk_workspace, "show_warning") as warning:
        QTimer.singleShot(70, lambda: answer_batch_delete("删除"))
        panel.delete_button.click()
        warning.assert_called_once()
        assert panel.checked_notes == {note.id, extra.id} and path.read_bytes() == persisted_before
    QTimer.singleShot(70, lambda: answer_batch_delete("删除"))
    panel.delete_button.click()
    assert not panel.selection_button.isChecked() and not panel.delete_button.isEnabled()
    assert not {note.id, extra.id}.intersection(NoteStore(path).records)
    assert not {note.id, extra.id}.intersection(studio.windows)

    studio.open_panel(page=1)
    app.processEvents()
    studio.select_character(original)
    active_before = settings.load(settings_file)
    inspected = []

    def inspect_actions():
        preview = app.activeModalWidget()
        if isinstance(preview, desk_workspace.CharacterActions):
            try:
                assert preview.pack.pet_id == "qa-character"
                assert len(preview.choice.options) == 9 and preview.sprite.timer.isActive()
                preview.choice.select("jumping", notify=True)
                assert preview.sprite.timer.interval() == 100
                assert preview.frame_info.text() == "4 帧 · 10 fps"
                preview.play_button.click()
                assert not preview.sprite.timer.isActive() and preview.play_button.text() == "播放"
                preview.play_button.click()
                assert preview.sprite.timer.isActive()
                inspected.append(True)
            finally:
                preview.reject()
    def open_action_menu():
        menu = app.activePopupWidget()
        if isinstance(menu, desk_workspace.RoundedMenu):
            action = next(a for a in menu.actions() if a.text() == "动作预览")
            menu.close()
            QTimer.singleShot(70, inspect_actions)
            action.trigger()

    QTimer.singleShot(70, open_action_menu)
    control = panel.character_grid.cards[imported].more_button
    QTest.mouseClick(control, Qt.MouseButton.LeftButton, pos=control.rect().center())
    assert inspected and pet._zip_path == original and settings.load(settings_file) == active_before

    notes_before = path.read_bytes()
    inactive = read_package(original).as_new(library).install(library)
    panel.refresh_library()
    observed = []

    def answer_role_delete(caption):
        dialog = app.activeModalWidget()
        if dialog is not None:
            observed.append(dialog.findChild(desk_workspace.QLabel, "dialogDetail").text())
            next(control for control in dialog.findChildren(QPushButton) if control.text() == caption).click()

    def remove_role(target, caption="删除角色"):
        QTimer.singleShot(70, lambda: answer_role_delete(caption))
        return studio.ask_delete_character(target, read_package(target).name)

    assert remove_role(inactive) and not inactive.exists()
    assert pet._zip_path == original and "当前使用的角色不会改变" in observed[-1]
    assert not remove_role(original, "取消")
    assert original.exists() and pet._zip_path == original and "将切换到「测试角色」" in observed[-1]
    with patch.object(Path, "unlink", side_effect=PermissionError("test")), \
         patch.object(desk_workspace, "show_warning") as warning:
        assert not remove_role(original)
        warning.assert_called_once()
        assert original.exists() and pet._zip_path == original
    assert remove_role(original) and pet._zip_path == duplicate
    assert panel.character_grid.cards[duplicate].isChecked()
    assert settings.load(settings_file)["pet_path"] == str(duplicate)
    studio.select_character(imported)
    assert remove_role(imported) and pet._zip_path == duplicate
    assert "将切换到「测试角色」" in observed[-1]
    assert remove_role(duplicate) and "桌宠会收起" in observed[-1]
    assert not pet.has_character and not pet.isVisible() and not pet._timer.isActive()
    assert settings.load(settings_file)["pet_path"] is None and not panel.character_grid.cards
    assert test_pack.exists() and path.read_bytes() == notes_before

    verified_role = read_package(test_pack).install(library)
    studio.select_character(verified_role)
    pet._apply_scale(.75)
    pet._apply_personality("focused")
    archived = Note(title="备份测试", visible=False, archived=True, color="薄荷",
                    textContent="已完成", richContent='<ul><li class="checked">已完成</li></ul>')
    studio.store.records[archived.id] = archived
    untagged = Note(title="标签测试", textContent="另一个工作事项", visible=False)
    studio.store.records[untagged.id] = untagged
    studio.changed()
    studio.open_panel(page=0)
    panel.select_note(archived)
    edited = []

    def answer_tags(names, *, save=True):
        dialog = app.activeModalWidget()
        if not isinstance(dialog, desk_workspace.TagEditor):
            return
        try:
            for name in names:
                dialog.entry.setText(name)
                QTest.keyClick(dialog.entry, Qt.Key.Key_Return)
            edited.append(list(dialog.tags.values()))
            if save:
                next(control for control in dialog.findChildren(QPushButton) if control.text() == "保存").click()
            else:
                dialog.reject()
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(70, lambda: answer_tags(("  工作  ", " ＵＩ ", "ui")))
    panel.edit_selected_tags()
    assert edited[-1] == ["工作", "ＵＩ"] and archived.tags == edited[-1]
    assert NoteStore(path).records[archived.id].tags == archived.tags
    assert "#工作" in panel.detail_tags.text()
    QTimer.singleShot(70, lambda: answer_tags(("临时标签",), save=False))
    studio.edit_note_tags(archived)
    assert archived.tags == ["工作", "ＵＩ"]

    QTimer.singleShot(70, lambda: answer_tags(("工作",)))
    studio.edit_note_tags(untagged)
    panel.set_tag_filter(tag_key("工作"))
    assert set(panel.note_cards) == {archived.id, untagged.id}
    panel.search.setText("已完成")
    assert set(panel.note_cards) == {archived.id}
    panel.search.clear()
    panel.note_filters.button(3).click()
    assert set(panel.note_cards) == {archived.id}
    panel.search.setText("ui")
    assert set(panel.note_cards) == {archived.id}
    panel.search.clear()
    panel.note_filters.button(0).click()
    panel.set_tag_filter(None)

    def remove_work_tag():
        dialog = app.activeModalWidget()
        if isinstance(dialog, desk_workspace.TagEditor):
            control = next(item for item in dialog.findChildren(QPushButton)
                           if item.accessibleName() == "移除标签 工作")
            control.click()
            dialog.accept()

    with patch.object(studio.store, "save", side_effect=PermissionError("test")), \
         patch.object(desk_workspace, "show_warning") as messages:
        QTimer.singleShot(70, remove_work_tag)
        studio.edit_note_tags(untagged)
        messages.assert_called_once()
        assert untagged.tags == ["工作"]
    QTimer.singleShot(70, remove_work_tag)
    studio.edit_note_tags(untagged)
    assert not untagged.tags
    assert not NoteStore(path).records[untagged.id].tags
    studio.open_panel(page=1)
    archive_path = scratch / "deskpet-backup.zip"
    actions = {control.text(): control for control in panel.findChildren(QPushButton)}
    with patch.object(desk_workspace, "pick_file", return_value=str(archive_path)), \
         patch.object(desk_workspace, "show_warning") as message:
        actions["导出备份"].click()
        message.assert_called_once()
        assert message.call_args.args[1] == "备份已导出"
    assert archive_path.is_file()
    expected_count = len(studio.store.records)
    expected_settings = settings.load(settings_file)
    archived.archived = False
    archived.title = "替换前的记录"
    studio.changed()
    assert studio.flush()
    in_use_before = path.read_bytes()
    pet._apply_scale(.25)
    previewed = []

    def answer_restore(text):
        dialog = app.activeModalWidget()
        if dialog is not None:
            previewed.append([item.text() for item in dialog.findChildren(desk_workspace.QLabel)])
            next(control for control in dialog.findChildren(QPushButton) if control.text() == text).click()

    with patch.object(desk_workspace, "pick_file", return_value=str(archive_path)), \
         patch.object(desk_workspace, "show_warning") as message:
        QTimer.singleShot(70, lambda: answer_restore("取消"))
        actions["从备份还原"].click()
        assert path.read_bytes() == in_use_before and not (scratch / "backups").exists()
        assert any(f"{expected_count} 张便签" in text and "1 个角色" in text for text in previewed[-1])
        assert any("会替换当前" in text for text in previewed[-1])
        QTimer.singleShot(70, lambda: answer_restore("确认还原"))
        actions["从备份还原"].click()
        message.assert_called_once()
        assert message.call_args.args[1] == "备份已还原"
    restored = NoteStore(path).records[archived.id]
    assert restored.archived and restored.title == "备份测试"
    assert restored.textContent == "已完成" and 'class="checked"' in restored.richContent
    assert restored.tags == ["工作", "ＵＩ"]
    assert restored.color == "薄荷" and pet._zip_path == verified_role
    assert pet._scale == expected_settings["pet_scale"] == .75
    assert pet._ps.personality == expected_settings["personality_style"] == "focused"
    with TemporaryDirectory(dir=scratch) as safety_temp:
        safety_zip, = (scratch / "backups").glob("还原前备份-*.zip")
        previous = stage_backup(safety_zip, Path(safety_temp))
        assert previous.records[archived.id].title == "替换前的记录"
        assert previous.preferences["pet_scale"] == .25
    verify_character_interactions(studio, scratch)

    screen, side = studio.edge_notes.home_rail()
    folded_tabs = [Note(title=f"压缩测试 {index}", visible=False, edge=side, edgeScreen=screen.name())
                   for index in range(4)]
    for entry in folded_tabs:
        studio.store.records[entry.id] = entry
    studio.edge_notes.refresh()
    rail = studio.edge_notes.rails[(screen, side)]
    rail.scroll.verticalScrollBar().setValue(0)
    before_count = len(studio.store.records)
    original_top = rail.y()
    original_height = rail.scroll.height()
    plus = rail.add_note
    start = plus.mapToGlobal(plus.rect().center())
    steps = (0, -max(24, QApplication.startDragDistance()), -76)
    for y_offset in steps:
        point = start + QPoint(0, y_offset)
        press = y_offset == 0
        kind = QEvent.Type.MouseButtonPress if press else QEvent.Type.MouseMove
        changed_button = Qt.MouseButton.LeftButton if press else Qt.MouseButton.NoButton
        app.sendEvent(plus, QMouseEvent(kind, QPointF(plus.mapFromGlobal(point)), QPointF(point),
                                       changed_button, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        if not press:
            assert rail.y() == original_top and rail.scroll.height() == original_height + y_offset
            assert plus.mapToGlobal(plus.rect().center()) == point
            assert not studio.edge_notes.drag_preview.isVisible()
    app.sendEvent(plus, QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(plus.mapFromGlobal(point)),
                                   QPointF(point), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                   Qt.KeyboardModifier.NoModifier))
    assert rail.y() == original_top and rail.scroll.height() == original_height - 76
    assert len(studio.store.records) == before_count
    saved_layout = settings.load(settings_file)["note_edge_layout"]
    assert saved_layout["stack_heights"][screen.name()][side] == original_height - 76
    studio.edge_notes.load_layout()
    studio.edge_notes.refresh()
    assert plus.mapToGlobal(plus.rect().center()) == point
    ordered = list(rail.tabs.values())
    assert 0 < ordered[1].y() - ordered[0].y() < TAB_STEP
    assert rail.track.childAt(ordered[0].width() // 2, ordered[0].exposed_height // 2) is ordered[0]
    first_id = next(iter(rail.tabs))
    was_open = studio.store.records[first_id].visible
    QTest.mouseClick(ordered[0], Qt.MouseButton.LeftButton,
                     pos=QPoint(ordered[0].width() // 2, ordered[0].exposed_height // 2))
    assert studio.store.records[first_id].visible != was_open
    drag_to(plus, point + QPoint(0, 32))
    assert rail.scroll.height() == original_height - 44 and rail.y() == original_top
    QTest.mouseClick(plus, Qt.MouseButton.LeftButton)
    assert len(studio.store.records) == before_count + 1

    single, neighbour = folded_tabs[:2]
    one_window = studio.show_note(single)
    two_window = studio.show_note(neighbour)
    single_menu = one_window.options_menu()
    next(action for action in single_menu.actions() if action.text() == "收起便签").trigger()
    single_menu.deleteLater()
    assert single.collapsed and not one_window.isVisible() and two_window.isVisible()
    assert single.edge == side and single.id not in rail.tabs
    assert studio.show_note(single).isVisible() and single.id in rail.tabs

    floating_note = studio.new_note()
    floating_window = studio.windows[floating_note.id]
    floating_window.detach()
    pending = Note(title="未显示", visible=False)
    studio.store.records[pending.id] = pending
    tray_menu = desk_workspace.RoundedMenu()
    studio.populate_menu(tray_menu, header=False)
    close_all = next(action for action in tray_menu.actions() if action.text() == "收起便签")
    with patch.object(studio.store, "save", side_effect=PermissionError("test")), \
         patch.object(desk_workspace, "show_warning") as warning:
        close_all.trigger()
        warning.assert_called_once()
        assert one_window.isVisible() and two_window.isVisible() and floating_window.isVisible()
    close_all.trigger()
    tray_menu.deleteLater()
    assert not any(window.isVisible() for window in studio.windows.values())
    assert not any(group.tabs for group in studio.edge_notes.rails.values())
    readback = NoteStore(path).records
    assert readback[single.id].collapsed and readback[single.id].edge == side
    assert readback[floating_note.id].collapsed and not readback[floating_note.id].edge
    assert readback[archived.id].archived and not readback[pending.id].collapsed
    studio.shutdown()
print("PASS: multi-character library, action preview, character deletion and fallback, same-ID copies, "
      "note library and edge visibility, snow compositing and pause, "
      "paper feed hold and cancel, persisted deletion and undo, save failure rollback, "
      "draggable edge tabs and note reattachment, batch deletion, tag editing and filtering, "
      "tagged backup and restore, single-pass playback, mouse gestures and HD character backup, "
      "single and bulk collapse, persistent edge stack compression and click-to-create")
