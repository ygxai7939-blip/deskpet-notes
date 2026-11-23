"""Smoke test the integrated Windows UI with test-only note data."""
from pathlib import Path
from shutil import copyfile
import json
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt, QVariantAnimation
from PySide6.QtGui import QEnterEvent, QFontDatabase, QMouseEvent, QTextBlockFormat, QTextCursor, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

import desk_workspace
from desk_style import create_ui_application
from edge_notes import TAB_STEP
from paper_feed import HOLD_MS, SWALLOW_MS
from pet_packages import read_package
from pixel_snow import Flake
from sticky_store import Note, NoteStore


root = Path(__file__).resolve().parent
runtime = root.parent / "deskpet-zh"
sys.path.insert(0, str(runtime))
from core import settings
from platforms.windows.desktop_pet import DesktopPet

app = create_ui_application("DeskPet notes smoke")
app.setEffectEnabled(Qt.UIEffect.UI_General, True)
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyhbd.ttc")
app.setQuitOnLastWindowClosed(False)
with TemporaryDirectory(dir=root) as scratch:
    scratch = Path(scratch)
    path = scratch / "notes.json"
    settings_file = scratch / "pet-settings.json"
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
    next(action for action in actions.actions() if action.text() == "关闭便签").trigger()
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
    editor.fold_into_pet()
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
    studio.shutdown()
print("PASS: multi-character library, switching and same-ID copies, note library and edge visibility, snow compositing and pause, "
      "paper feed hold and cancel, persisted deletion and undo, save failure rollback, "
      "draggable edge tabs and note reattachment, and confirmed batch selection and deletion")
