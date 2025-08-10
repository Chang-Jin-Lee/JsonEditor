# json_table_editor_pink.py
# ------------------------------------------------------------
# JSON 표 편집 + CSV/XLSX/JSON 저장 + 내장 배경(워터마크, 투명도 조절)
# - 루트가 List[Dict] → 바로 표
# - 루트가 Dict → 내부 List[Dict] 경로 선택
# - 셀 수정/행 추가/삭제 가능
# - 분홍×흰 테마(QSS) 적용
# - 기본 배경 이미지를 base64로 "코드 내에" 내장 (exe에 함께 포함)
# ------------------------------------------------------------

import sys, json
from typing import Any, List, Optional

import pandas as pd
from PySide6 import QtCore, QtGui, QtWidgets

# ==== 0) 내장 배경 이미지(Base64) ====
# 여기에 원하시는 PNG/JPG의 base64 문자열을 넣어주세요.
# 예시는 아주 작은 연분홍 PNG 더미(바꾸셔도 됩니다).
BACKGROUND_IMAGE_B64 = (
    ""
)

# ==== 1) 테마(QSS + 팔레트) ====
def apply_pink_theme(app: QtWidgets.QApplication):
    # 기본 팔레트(밝은 계열)
    pal = app.palette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor("#fff6fa"))
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor("#ffffff"))
    pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#ffe6f1"))
    pal.setColor(QtGui.QPalette.Text, QtGui.QColor("#333333"))
    pal.setColor(QtGui.QPalette.Button, QtGui.QColor("#ffedf5"))
    pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#333333"))
    pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#ff77aa"))
    pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
    app.setPalette(pal)

    # 위젯 전반 스타일(QSS)
    app.setStyleSheet("""
        QWidget { font-family: "Segoe UI", "Malgun Gothic"; font-size: 12px; color: #333; }
        QMainWindow { background: #fff6fa; }

        QPushButton {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffd1e3, stop:1 #ffedf5);
            border: 1px solid #ffb3d1;
            border-radius: 8px;
            padding: 6px 10px;
        }
        QPushButton:hover { background: #ffddee; }
        QPushButton:pressed { background: #ffc8e0; }

        QTableView {
            gridline-color: #ffd1e3;
            selection-background-color: #ff77aa;
            selection-color: white;
            background: #ffffff;
            alternate-background-color: #ffe6f1;
            border: 1px solid #ffb3d1;
            border-radius: 6px;
        }
        QHeaderView::section {
            background: #ffedf5;
            border: 1px solid #ffb3d1;
            padding: 6px;
        }
        QLineEdit, QComboBox {
            background: #ffffff;
            border: 1px solid #ffb3d1;
            border-radius: 6px;
            padding: 4px 6px;
        }
        QLabel#statusLabel {
            color: #666; padding: 4px 2px;
        }
        QSlider::groove:horizontal {
            height: 6px; background: #ffd1e3; border-radius: 3px;
        }
        QSlider::handle:horizontal {
            width: 14px; background: #ff77aa; margin: -5px 0; border-radius: 7px;
            border: 1px solid #ff4f93;
        }
    """)

# ==== 2) JSON 내부에서 List[Dict] 경로 찾기 ====
def find_record_paths(obj: Any, max_depth: int = 4) -> List[str]:
    paths = []
    def _walk(node, path, depth):
        if depth > max_depth: return
        if isinstance(node, dict):
            for k, v in node.items():
                newp = f"{path}.{k}" if path else k
                if isinstance(v, list) and v and all(isinstance(i, dict) for i in v):
                    paths.append(newp)
                _walk(v, newp, depth + 1)
        elif isinstance(node, list):
            for v in node[:5]:
                _walk(v, path, depth + 1)
    if isinstance(obj, dict):
        _walk(obj, "", 0)
    return paths

def get_by_path(d: dict, path: str):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur: return None
        cur = cur[part]
    return cur

# ==== 3) 편집 가능한 DataFrame 모델 ====
class PandasTableModel(QtCore.QAbstractTableModel):
    def __init__(self, df: pd.DataFrame):
        super().__init__()
        self._df = df.copy()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self._df.columns)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid(): return None
        val = self._df.iat[index.row(), index.column()]
        if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
            if pd.isna(val): return ""
            return str(val)
        return None

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if not index.isValid() or role != QtCore.Qt.EditRole: return False
        orig = self._df.iat[index.row(), index.column()]
        new_val = value
        if isinstance(orig, (dict, list)):  # JSON 문자열이면 파싱 시도
            try:
                new_val = json.loads(value)
            except Exception:
                new_val = value
        self._df.iat[index.row(), index.column()] = new_val
        self.dataChanged.emit(index, index, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
        return True

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role != QtCore.Qt.DisplayRole: return None
        if orientation == QtCore.Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    def flags(self, index):
        if not index.isValid(): return QtCore.Qt.ItemIsEnabled
        return QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable

    def insertRows(self, position, rows=1, parent=QtCore.QModelIndex()):
        self.beginInsertRows(QtCore.QModelIndex(), position, position + rows - 1)
        empty = {c: "" for c in self._df.columns}
        for _ in range(rows):
            self._df = pd.concat(
                [self._df.iloc[:position], pd.DataFrame([empty]), self._df.iloc[position:]],
                ignore_index=True
            )
        self.endInsertRows()
        return True

    def removeRows(self, position, rows=1, parent=QtCore.QModelIndex()):
        if position < 0 or position + rows > len(self._df): return False
        self.beginRemoveRows(QtCore.QModelIndex(), position, position + rows - 1)
        self._df = self._df.drop(self._df.index[position:position+rows]).reset_index(drop=True)
        self.endRemoveRows()
        return True

    def dataframe(self) -> pd.DataFrame:
        return self._df.copy()

# ==== 4) 워터마크 가능한 테이블 뷰 ====
class WatermarkTableView(QtWidgets.QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QtGui.QPixmap] = None
        self._opacity: float = 0.12
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

    def setWatermarkPixmap(self, pm: Optional[QtGui.QPixmap]):
        self._pixmap = pm
        self.viewport().update()

    def setOpacity(self, value: float):
        self._opacity = max(0.0, min(1.0, value))
        self.viewport().update()

    def paintEvent(self, e: QtGui.QPaintEvent):
        super().paintEvent(e)
        if not self._pixmap or self._pixmap.isNull(): return
        p = QtGui.QPainter(self.viewport())
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        p.setOpacity(self._opacity)
        vw, vh = self.viewport().width(), self.viewport().height()
        pm = self._pixmap
        scale = min(vw / pm.width(), vh / pm.height()) * 0.6
        if scale <= 0: 
            p.end(); return
        w, h = int(pm.width()*scale), int(pm.height()*scale)
        x, y = (vw - w)//2, (vh - h)//2
        p.drawPixmap(QtCore.QRect(x, y, w, h), pm)
        p.end()

# ==== 5) 메인 윈도우 ====
class MainWindow(QtWidgets.QMainWindow):
    MAX_PREVIEW_COLUMNS = 200

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JSON Table Editor — Pink Theme")
        self.resize(1280, 820)

        self._df: Optional[pd.DataFrame] = None

        # 중앙 UI
        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(10,10,10,10)
        layout.setSpacing(8)

        # 툴바
        top = QtWidgets.QHBoxLayout()
        self.btn_open = QtWidgets.QPushButton("JSON 열기")
        self.btn_save_json = QtWidgets.QPushButton("JSON 저장")
        self.btn_csv = QtWidgets.QPushButton("CSV로 내보내기")
        self.btn_xlsx = QtWidgets.QPushButton("엑셀(XLSX)로 내보내기")
        self.btn_add = QtWidgets.QPushButton("행 추가")
        self.btn_del = QtWidgets.QPushButton("선택 행 삭제")

        top.addWidget(self.btn_open)
        top.addSpacing(10)
        top.addWidget(self.btn_save_json)
        top.addWidget(self.btn_csv)
        top.addWidget(self.btn_xlsx)
        top.addSpacing(20)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_del)
        top.addStretch(1)

        # 배경/투명도
        self.opacity_label = QtWidgets.QLabel("배경 투명도")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(12)
        top.addWidget(self.opacity_label)
        top.addWidget(self.slider)

        layout.addLayout(top)

        # 표
        self.table = WatermarkTableView(self)
        layout.addWidget(self.table, 1)

        # 상태 라벨
        self.status = QtWidgets.QLabel("파일을 열어주세요.")
        self.status.setObjectName("statusLabel")
        layout.addWidget(self.status)

        self.setCentralWidget(central)

        # 시그널
        self.btn_open.clicked.connect(self.on_open)
        self.btn_save_json.clicked.connect(self.on_save_json)
        self.btn_csv.clicked.connect(self.on_export_csv)
        self.btn_xlsx.clicked.connect(self.on_export_xlsx)
        self.btn_add.clicked.connect(self.on_add_row)
        self.btn_del.clicked.connect(self.on_del_rows)
        self.slider.valueChanged.connect(lambda v: self.table.setOpacity(v/100.0))

        # 시작 시 내장 배경 적용
        self._apply_embedded_background()

    # --- 내장 배경 적용 ---
    def _apply_embedded_background(self):
        try:
            raw = QtCore.QByteArray.fromBase64(BACKGROUND_IMAGE_B64.encode("ascii"))
            pm = QtGui.QPixmap()
            pm.loadFromData(raw)
            if not pm.isNull():
                self.table.setWatermarkPixmap(pm)
                self.status.setText("기본 배경 이미지가 적용되었습니다.")
        except Exception:
            self.status.setText("기본 배경 이미지를 불러오지 못했습니다.")

    # --- JSON → DataFrame ---
    def _to_dataframe(self, data: Any) -> pd.DataFrame:
        if isinstance(data, list):
            if not data: return pd.DataFrame()
            if all(isinstance(x, dict) for x in data):
                return pd.json_normalize(data, sep=".")
            return pd.DataFrame({"value": data})

        if isinstance(data, dict):
            cands = find_record_paths(data)
            if cands:
                chosen, ok = QtWidgets.QInputDialog.getItem(self, "경로 선택", "표로 펼칠 리스트 경로:", cands, 0, False)
                if ok and chosen:
                    recs = get_by_path(data, chosen)
                    return pd.json_normalize(recs, sep=".")
            return pd.json_normalize(data, sep=".")
        return pd.DataFrame({"value": [data]})

    # --- 핸들러들 ---
    def on_open(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "JSON 파일 선택", "", "JSON files (*.json);;All files (*)")
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "에러", f"JSON 로드 실패: {e}")
            return
        df = self._to_dataframe(data)
        if len(df.columns) > self.MAX_PREVIEW_COLUMNS:
            df = df[df.columns[:self.MAX_PREVIEW_COLUMNS]]
            QtWidgets.QMessageBox.information(self, "알림", f"컬럼이 많아 처음 {self.MAX_PREVIEW_COLUMNS}개만 표시합니다.")
        self._df = df
        self.table.setModel(PandasTableModel(df))
        self.status.setText(f"로드 완료 | 행 {len(df)}, 열 {len(df.columns)}")

    def _current_df(self) -> Optional[pd.DataFrame]:
        m = self.table.model()
        return m.dataframe() if isinstance(m, PandasTableModel) else None

    def on_save_json(self):
        df = self._current_df()
        if df is None:
            QtWidgets.QMessageBox.information(self, "알림", "먼저 JSON을 여세요.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "JSON로 저장", "", "JSON files (*.json)")
        if not path: return
        try:
            rows = []
            for _, row in df.iterrows():
                obj = {}
                for c, v in row.items():
                    if isinstance(v, str):
                        try: obj[c] = json.loads(v)
                        except Exception: obj[c] = v
                    else:
                        obj[c] = (None if pd.isna(v) else v)
                rows.append(obj)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            QtWidgets.QMessageBox.information(self, "완료", f"저장됨: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "에러", f"저장 실패: {e}")

    def on_export_csv(self):
        df = self._current_df()
        if df is None:
            QtWidgets.QMessageBox.information(self, "알림", "먼저 JSON을 여세요.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "CSV로 저장", "", "CSV files (*.csv)")
        if not path: return
        try:
            df.to_csv(path, index=False, encoding="utf-8-sig")
            QtWidgets.QMessageBox.information(self, "완료", f"저장됨: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "에러", f"저장 실패: {e}")

    def on_export_xlsx(self):
        df = self._current_df()
        if df is None:
            QtWidgets.QMessageBox.information(self, "알림", "먼저 JSON을 여세요.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "엑셀(xlsx)로 저장", "", "Excel Workbook (*.xlsx)")
        if not path: return
        try:
            df.to_excel(path, index=False)
            QtWidgets.QMessageBox.information(self, "완료", f"저장됨: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "에러", f"저장 실패: {e}")

    def on_add_row(self):
        m = self.table.model()
        if isinstance(m, PandasTableModel):
            m.insertRows(m.rowCount(), 1)
            self.status.setText("행 1개 추가")

    def on_del_rows(self):
        m = self.table.model()
        if not isinstance(m, PandasTableModel): return
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            QtWidgets.QMessageBox.information(self, "알림", "삭제할 행을 선택하세요.")
            return
        for r in sorted([s.row() for s in sel], reverse=True):
            m.removeRows(r, 1)
        self.status.setText(f"행 {len(sel)}개 삭제")

def main():
    # HiDPI 대응
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    apply_pink_theme(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
