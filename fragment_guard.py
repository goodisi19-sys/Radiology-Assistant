"""Track an explicit replacement range while unrelated document editing continues."""
from PySide6.QtGui import QTextCursor
class FragmentGuard:
    def __init__(self,document,cursor,whole=False):
        self.document=document;self.start=cursor.selectionStart();self.end=cursor.selectionEnd()
        self.valid=self.end>self.start or whole;self.whole=whole;self.applying=False
        document.contentsChange.connect(self.changed)
    def changed(self,pos,removed,added):
        if self.applying or not self.valid:return
        if self.whole:self.valid=False;return
        if removed and pos<self.end and pos+removed>self.start:self.valid=False;return
        if added and self.start<=pos<self.end:self.valid=False;return
        if pos<self.start:
            self.start+=added-removed;self.end+=added-removed
    def cursor(self):
        cursor=QTextCursor(self.document);cursor.setPosition(self.start)
        cursor.setPosition(self.end,QTextCursor.MoveMode.KeepAnchor);return cursor
    def replace(self,text):
        if not self.valid:return False
        self.applying=True
        try:
            cursor=self.cursor();cursor.beginEditBlock();cursor.insertText(text);cursor.endEditBlock()
            self.end=cursor.position();self.valid=True
        finally:self.applying=False
        return True
    def close(self):
        self.valid=False
        try:self.document.contentsChange.disconnect(self.changed)
        except (RuntimeError,TypeError):pass
