"""Optional calculations and RAM-only source comparison; never edit a protocol."""
import math,difflib,re

def ellipsoid_ml(dimensions,unit='мм'):
    if len(dimensions)!=3 or unit not in ('мм','см'):raise ValueError('Нужны три размера в одинаковых единицах: мм или см.')
    if any(not math.isfinite(v) or v<=0 for v in dimensions):raise ValueError('Размеры должны быть положительными конечными числами.')
    value=math.pi/6*math.prod(dimensions)/(1000 if unit=='мм' else 1)
    if not math.isfinite(value):raise ValueError('Слишком большие размеры.')
    return value

def template_diff(baseline,current):
    return '\n'.join(difflib.unified_diff(baseline.splitlines(),current.splitlines(),fromfile='Вставленный шаблон',tofile='Текущий текст',lineterm=''))

def verified_checklist(db,area):
    # Only explicit verified sources; frequency is a suggestion, never a compulsory finding.
    from protocol_context import STRUCTURES
    rows=db.execute('SELECT content FROM verified_standards WHERE category=?',(area,)).fetchall()
    total=len(rows)
    return [(organ,sum(bool(re.search(pattern,text,re.I)) for text, in rows),total) for organ,pattern in STRUCTURES.items() if any(re.search(pattern,text,re.I) for text, in rows)]

def show_volume(parent):
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QLineEdit,QComboBox,QLabel,QPushButton
    dialog=QDialog(parent);dialog.setWindowTitle('Объём эллипсоида — справочный расчёт')
    layout=QVBoxLayout(dialog);layout.addWidget(QLabel('Три размера через x. Расчёт не изменяет документ.'))
    entry=QLineEdit();entry.setPlaceholderText('30x21x36');layout.addWidget(entry)
    unit=QComboBox();unit.addItems(['мм','см']);layout.addWidget(unit);result=QLabel();layout.addWidget(result)
    def calculate():
        try:result.setText(f'{ellipsoid_ml([float(x.replace(",",".")) for x in re.split("[xх×]",entry.text())],unit.currentText()):.2f} мл (π/6 × a × b × c)')
        except ValueError as error:result.setText(str(error))
    button=QPushButton('Рассчитать');button.clicked.connect(calculate);layout.addWidget(button);dialog.exec()

def show_source_review(window):
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QPlainTextEdit,QLabel
    dialog=QDialog(window);dialog.setWindowTitle('Сравнение с вставленным шаблоном');dialog.resize(800,550);layout=QVBoxLayout(dialog)
    baseline=getattr(window,'_inserted_template_baseline',None)
    layout.addWidget(QLabel('Сравнивается только последний действительно вставленный шаблон. Изменения не являются ошибками.'))
    text=QPlainTextEdit();text.setReadOnly(True)
    text.setPlainText(template_diff(baseline,window.editor.toPlainText()) if baseline is not None else 'В этом документе шаблон ещё не вставлялся; сравнивать не с чем.')
    layout.addWidget(text)
    state=window.protocol_context.update(window.editor.toPlainText());rows=verified_checklist(window.library.db,state.area)
    layout.addWidget(QLabel('Необязательные пункты из личных верифицированных стандартов:\n'+'; '.join(f'{name}: {count}/{total}' for name,count,total in rows) if rows else 'Для области нет верифицированного личного чек-листа.'))
    dialog.exec()
