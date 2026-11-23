"""Commit explicit word choices only after the short undo window has elapsed."""
import time
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor


class CorrectionLearning:
    DELAY = 10.0

    def __init__(self, window, clock=time.monotonic):
        self.window=window;self.clock=clock;self.pending=[]
        self.timer=QTimer(window);self.timer.setInterval(250);self.timer.timeout.connect(self.flush)

    def add(self, original, replacement, start):
        if not self.window.library.ai.enabled('self_learning'):return
        cursor=QTextCursor(self.window.editor.document())
        cursor.setPosition(start)
        cursor.setPosition(start+len(replacement.encode('utf-16-le'))//2,QTextCursor.MoveMode.KeepAnchor)
        if cursor.selectedText()!=replacement:return
        self.pending.append((self.clock()+self.DELAY,cursor,original,replacement))
        self.pending=self.pending[-100:];self.timer.start()

    def flush(self):
        if getattr(self.window,'_closing',False):self.clear();return
        ai=self.window.library.ai
        if not ai.enabled('self_learning'):self.clear();return
        remaining=[];now=self.clock()
        for deadline,cursor,original,replacement in self.pending:
            # QTextCursor follows edits. Undo, deleting or editing the word
            # invalidates the choice without retaining a document snapshot.
            if cursor.document() is not self.window.editor.document() or cursor.selectedText()!=replacement:continue
            if now<deadline:remaining.append((deadline,cursor,original,replacement))
            else:ai.confirm_correction(original,replacement)
        self.pending=remaining
        if not remaining:self.timer.stop()

    def clear(self):
        self.timer.stop();self.pending.clear()
