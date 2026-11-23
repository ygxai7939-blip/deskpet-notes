"""Dark library palette for the workspace window."""

WORKSPACE_STYLE = """
QFrame#libraryCenter { background: rgba(37,37,37,224); border: none; border-radius: 18px; }
QFrame#libraryPet { background: rgba(32,32,32,177); border: none; border-radius: 18px; }
QFrame#libraryDetails { background: rgba(44,44,44,224); border: none; border-radius: 18px; }
QFrame#feedUndo { background: #2b2b2b; border-radius: 12px; }
QFrame#libraryTabs { background: #303030; border: none; border-radius: 12px; }
QFrame#libraryPetShortcut { background: #242424; border: none; border-radius: 14px; }
QFrame#characterBehavior { background: rgba(51,51,51,114); border: none; border-radius: 14px; }
QWidget#characterPageBody { background: transparent; }
QScrollArea#characterPageScroll QScrollBar::add-page:vertical,
QScrollArea#characterPageScroll QScrollBar::sub-page:vertical { background: transparent; }
QPushButton#characterCard {
  background: rgba(31,31,31,107); border: 1px solid #3f3f3f; border-radius: 15px;
  padding: 0; min-height: 194px;
}
QPushButton#characterCard:hover { background: rgba(62,62,62,96); border-color: #676767; }
QPushButton#characterCard:checked { background: rgba(59,59,59,119); border-color: #878787; }
QPushButton#characterMore {
  background: #373737; border: 1px solid #4c4c4c; border-radius: 8px; padding: 0; min-height: 0;
}
QPushButton#characterMore:hover { background: #494949; border-color: #676767; }
QPushButton#characterMore:pressed { background: #515151; }
QLabel#characterActive {
  color: #ededed; background: #454545; border-radius: 8px; padding: 2px 7px; font-size: 10px;
}
QLabel#characterDescription { color: #bdbdbd; font-size: 12px; }
QLabel#characterEmpty {
  color: #bdbdbd; background: rgba(40,40,40,130); border-radius: 12px; font-size: 12px;
}
QPushButton#characterControl {
  color: #ebebeb; background: rgba(55,55,55,205); border: 1px solid #484848;
  border-radius: 15px; padding: 0 12px; min-height: 30px; font-size: 12px;
}
QPushButton#characterControl:hover, QPushButton#characterControl:focus {
  background: #414141; border-color: #676767;
}
QFrame#libraryRule { background: #3b3b3b; border: none; }
QFrame#libraryCard { background: #2e2e2e; border: 1px solid #2e2e2e; border-radius: 14px; }
QFrame#libraryCard[selected="true"] { background: #343434; border-color: #626262; }
QLabel#libraryTitle { color: #dedede; font-size: 14px; font-weight: 700; }
QLabel#libraryHeading { color: #e6e6e6; font-size: 23px; font-weight: 700; }
QLabel#libraryCardTitle { color: #dedede; font-size: 13px; font-weight: 700; }
QLabel#libraryDetailTitle { color: #ededed; font-size: 16px; font-weight: 700; }
QLabel#libraryText { color: #dedede; font-size: 12px; }
QLabel#libraryMeta { color: #a6a6a6; font-size: 11px; }
QLabel#publisherCredit { color: #929292; font-size: 10px; }
QLabel#libraryPreview {
  color: #c5c5c5; background: #242424; border: none; border-radius: 9px; padding: 8px 9px;
  font-size: 12px;
}
QPushButton#libraryNav {
  color: #dedede; background: transparent; border: none; border-radius: 10px;
  text-align: left; padding: 0 10px; min-height: 35px; font-size: 13px;
}
QPushButton#libraryNav:checked { background: #343434; font-weight: 700; }
QPushButton#libraryTab {
  color: #bdbdbd; background: transparent; border: none; border-radius: 8px;
  padding: 0 10px; min-height: 27px; font-size: 12px;
}
QPushButton#libraryTab:hover { background: #383838; }
QPushButton#libraryTab:checked { color: #ededed; background: #494949; }
QPushButton#libraryAction {
  color: #ededed; background: #3b3b3b; border: none; border-radius: 10px;
  padding: 0 11px; min-height: 34px; font-size: 12px; font-weight: 600;
}
QPushButton#libraryAction:hover { background: #494949; }
QPushButton#libraryAction:pressed { background: #545454; }
QPushButton#librarySecondary {
  color: #dedede; background: #383838; border: none; border-radius: 8px;
  padding: 0 9px; min-height: 26px; font-size: 11px;
}
QPushButton#librarySecondary:hover { background: #494949; }
QPushButton#librarySecondary:pressed { background: #545454; }
QPushButton#libraryIcon, QPushButton#libraryClose {
  color: #bdbdbd; background: transparent; border: none; border-radius: 8px; padding: 0; min-height: 25px;
}
QPushButton#libraryIcon:hover, QPushButton#libraryClose:hover { background: #494949; }
QPushButton#librarySelect, QPushButton#libraryDelete {
  background: #383838; border: 1px solid #414141; border-radius: 9px; padding: 0;
}
QPushButton#librarySelect:hover, QPushButton#libraryDelete:hover { background: #494949; }
QPushButton#librarySelect:checked { background: #535353; border-color: #747474; }
QPushButton#libraryDelete:disabled { background: #2d2d2d; border-color: #353535; }
QPushButton#libraryMark { background: transparent; border: none; border-radius: 5px; padding: 0; }
QPushButton#libraryMark:hover, QPushButton#libraryMark:checked { background: #505050; }
QLineEdit#librarySearch {
  color: #ededed; background: #383838; border: 1px solid #383838; border-radius: 10px;
  padding: 0 9px; min-height: 32px; placeholder-text-color: #b0b0b0; selection-background-color: #616161;
}
QLineEdit#librarySearch:focus { border-color: #6a6a6a; }
QPlainTextEdit#libraryDetailText {
  color: #dedede; background: #252525; border: none; border-radius: 10px;
  font-size: 12px; padding: 9px; selection-background-color: #525252;
}
QPushButton#choice {
  min-width: 113px; text-align: left; padding: 4px 31px 4px 11px;
  color: #dedede; background: #383838; border: none; border-radius: 9px;
}
QPushButton#choice:hover, QPushButton#choice:pressed { background: #494949; }
QScrollBar::handle:vertical { background: #494949; border-radius: 3px; }
"""
