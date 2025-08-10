# json_table_editor_pink.py
# ------------------------------------------------------------
# JSON 표 편집 + CSV/XLSX/JSON 저장 + 내장 배경(워터마크, 투명도 조절)
# - 루트가 List[Dict] → 바로 표
# - 루트가 Dict → 내부 List[Dict] 경로 선택
# - 셀 수정/행 추가/삭제 가능
# - 분홍×흰 테마(QSS) 적용
# - 기본 배경 이미지를 base64로 "코드 내에" 내장 (exe에 함께 포함)
# ------------------------------------------------------------
import sys, json, traceback
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    import numpy as np
except Exception:
    np = None  # numpy 없어도 동작하도록

from PySide6 import QtCore, QtGui, QtWidgets


# ===== 전역 안전 장치: 예기치 못한 예외도 잡아 경고창 =====
def _safe_message(parent: Optional[QtWidgets.QWidget], title: str, text: str, detail: Optional[str] = None):
    try:
        QtWidgets.QMessageBox.warning(parent, title, text + (f"\n\n{detail}" if detail else ""))
    except Exception:
        # 메시지박스 자체가 실패하는 일은 드물지만, 마지막 방어선
        print(f"[WARN] {title}: {text}\n{detail or ''}", file=sys.stderr)

def _fatal_to_warning(exctype, value, tb):
    # 전역 예외도 모두 경고로 바꿔 UI 유지
    msg = "".join(traceback.format_exception(exctype, value, tb))
    _safe_message(None, "오류", "잘못된 파일입니다.", msg)

sys.excepthook = _fatal_to_warning

# ==== 0) 내장 배경 이미지(Base64) ====
# 여기에 원하시는 PNG/JPG의 base64 문자열을 넣어주세요.
# 예시는 아주 작은 연분홍 PNG 더미(바꾸셔도 됩니다).
BACKGROUND_IMAGE_B64 = (
    ""
)

# ===== 테마(QSS) =====
def apply_pink_theme(app: QtWidgets.QApplication):
    try:
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

        app.setStyleSheet("""
            QWidget { font-family: "Segoe UI","Malgun Gothic"; font-size: 12px; color: #333; }
            QMainWindow { background: #fff6fa; }
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffd1e3, stop:1 #ffedf5);
                border: 1px solid #ffb3d1; border-radius: 8px; padding: 6px 10px;
            }
            QPushButton:hover { background: #ffddee; }
            QPushButton:pressed { background: #ffc8e0; }
            QLineEdit, QComboBox {
                background: #ffffff; border: 1px solid #ffb3d1; border-radius: 6px; padding: 4px 6px;
            }
            QTableView {
                gridline-color: #ffd1e3; selection-background-color: #ff77aa; selection-color: #fff;
                background: #ffffff; alternate-background-color: #ffe6f1; border: 1px solid #ffb3d1; border-radius: 6px;
            }
            QHeaderView::section { background: #ffedf5; border: 1px solid #ffb3d1; padding: 6px; }
            QLabel#statusLabel { color: #666; padding: 4px 2px; }
            QSlider::groove:horizontal { height: 6px; background: #ffd1e3; border-radius: 3px; }
            QSlider::handle:horizontal { width: 14px; background: #ff77aa; margin: -5px 0; border-radius: 7px; border: 1px solid #ff4f93; }
            QSplitter::handle { background: #ffedf5; }
        """)
    except Exception as e:
        _safe_message(None, "오류", "테마 적용 중 오류가 발생했습니다.", str(e))


# ===== JSON 유틸 =====
def is_primitive(x: Any) -> bool:
    return isinstance(x, (str, int, float, bool)) or x is None

def _kind_label(v: Any) -> str:
    try:
        if isinstance(v, dict): return "object"
        if isinstance(v, list): return "array"
        if is_primitive(v): return type(v).__name__
        return type(v).__name__
    except Exception:
        return "unknown"

def build_json_tree(obj: Any, parent_item: QtWidgets.QTreeWidgetItem, path: str, max_children=200):
    try:
        if isinstance(obj, dict):
            for k, v in obj.items():
                child = QtWidgets.QTreeWidgetItem([str(k), _kind_label(v), f"{path}.{k}" if path else k])
                parent_item.addChild(child)
                build_json_tree(v, child, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj[:max_children]):
                child = QtWidgets.QTreeWidgetItem([f"[{i}]", _kind_label(v), f"{path}[{i}]"])
                parent_item.addChild(child)
                build_json_tree(v, child, f"{path}[{i}]")
            if len(obj) > max_children:
                more = QtWidgets.QTreeWidgetItem(["...", f"{len(obj)-max_children} more", path])
                parent_item.addChild(more)
    except Exception as e:
        _safe_message(None, "오류", "잘못된 파일입니다.", str(e))

def resolve_json_path(root: Any, path: str) -> Any:
    try:
        cur = root
        if not path:
            return cur
        tokens: List[Any] = []
        buf = ""
        i = 0
        while i < len(path):
            c = path[i]
            if c == '.':
                if buf: tokens.append(buf); buf = ""
                i += 1; continue
            elif c == '[':
                if buf: tokens.append(buf); buf = ""
                j = path.find(']', i)
                if j == -1: return None
                idx = int(path[i+1:j])
                tokens.append(idx)
                i = j + 1
                continue
            else:
                buf += c
                i += 1
        if buf: tokens.append(buf)

        for t in tokens:
            if isinstance(t, int):
                if isinstance(cur, list) and 0 <= t < len(cur):
                    cur = cur[t]
                else:
                    return None
            else:
                if isinstance(cur, dict) and t in cur:
                    cur = cur[t]
                else:
                    return None
        return cur
    except Exception as e:
        _safe_message(None, "오류", "잘못된 파일입니다.", str(e))
        return None


# ===== DataFrame 변환 (어떤 조각이든 안전하게) =====
def to_dataframe_any(obj: Any) -> pd.DataFrame:
    try:
        if isinstance(obj, list):
            if not obj:
                return pd.DataFrame()
            if all(isinstance(x, dict) for x in obj):
                return pd.json_normalize(obj, sep=".")
            if all(is_primitive(x) for x in obj):
                return pd.DataFrame({"value": obj})
            # 혼합형 → 문자열로라도 보여주기
            return pd.DataFrame({"value": [_to_display_str(x) for x in obj]})
        if isinstance(obj, dict):
            return pd.json_normalize(obj, sep=".")
        # primitive
        return pd.DataFrame({"value": [obj]})
    except Exception as e:
        _safe_message(None, "오류", "잘못된 파일입니다.", str(e))
        # 마지막 방어: 무엇이든 문자열로 한 셀에라도
        try:
            return pd.DataFrame({"value": [json.dumps(obj, ensure_ascii=False)]})
        except Exception:
            return pd.DataFrame({"value": [str(obj)]})


# ===== 표시용 안전 문자열 변환 =====
def _to_display_str(val: Any) -> str:
    try:
        # 결측값 처리
        if val is None:
            return ""
        if np is not None and isinstance(val, (float, np.floating)):
            try:
                if pd.isna(val):
                    return ""
            except Exception:
                pass
        # 구조 타입은 JSON 문자열
        if isinstance(val, (dict, list, tuple)):
            try:
                return json.dumps(val, ensure_ascii=False)
            except Exception:
                return str(val)
        return str(val)
    except Exception:
        try:
            return str(val)
        except Exception:
            return ""


# ===== 편집 가능한 모델(전면 방어) =====
class PandasTableModel(QtCore.QAbstractTableModel):
    def __init__(self, df: pd.DataFrame):
        super().__init__()
        try:
            self._df = df.copy()
        except Exception:
            self._df = pd.DataFrame()

    def rowCount(self, parent=QtCore.QModelIndex()):
        try:
            return len(self._df)
        except Exception:
            return 0

    def columnCount(self, parent=QtCore.QModelIndex()):
        try:
            return len(self._df.columns)
        except Exception:
            return 0

    def data(self, index, role=QtCore.Qt.DisplayRole):
        try:
            if not index or not index.isValid():
                return None
            if role not in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
                return None
            val = self._df.iat[index.row(), index.column()]
            return _to_display_str(val)
        except Exception as e:
            # 셀 하나 실패해도 전체는 살려야 함
            return ""

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        try:
            if role != QtCore.Qt.DisplayRole:
                return None
            if orientation == QtCore.Qt.Horizontal:
                return str(self._df.columns[section])
            return str(section + 1)
        except Exception:
            return None

    def flags(self, index):
        try:
            if not index or not index.isValid():
                return QtCore.Qt.ItemIsEnabled
            return QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable
        except Exception:
            return QtCore.Qt.ItemIsEnabled

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        try:
            if not index or not index.isValid() or role != QtCore.Qt.EditRole:
                return False
            text = value if isinstance(value, str) else str(value)

            # 1) JSON 파싱 시도
            try:
                v = json.loads(text)
            except Exception:
                # 2) 불리언/숫자 캐스팅
                low = text.strip().lower()
                if low in ("true", "false"):
                    v = (low == "true")
                else:
                    try:
                        v = float(text) if "." in text else int(text)
                    except Exception:
                        v = text  # 3) 원문

            self._df.iat[index.row(), index.column()] = v
            self.dataChanged.emit(index, index, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
            return True
        except Exception:
            _safe_message(None, "오류", "잘못된 파일입니다.")
            return False

    def insertRows(self, position, rows=1, parent=QtCore.QModelIndex()):
        try:
            self.beginInsertRows(QtCore.QModelIndex(), position, position + rows - 1)
            empty = {c: "" for c in list(self._df.columns)} if not self._df.empty else {}
            for _ in range(rows):
                if self._df.empty:
                    self._df = pd.DataFrame([empty])
                else:
                    self._df = pd.concat(
                        [self._df.iloc[:position], pd.DataFrame([empty]), self._df.iloc[position:]],
                        ignore_index=True
                    )
            self.endInsertRows()
            return True
        except Exception as e:
            self.endInsertRows()  # 안전
            _safe_message(None, "오류", "잘못된 파일입니다.", str(e))
            return False

    def removeRows(self, position, rows=1, parent=QtCore.QModelIndex()):
        try:
            if position < 0 or position + rows > len(self._df):
                return False
            self.beginRemoveRows(QtCore.QModelIndex(), position, position + rows - 1)
            self._df = self._df.drop(self._df.index[position:position+rows]).reset_index(drop=True)
            self.endRemoveRows()
            return True
        except Exception as e:
            self.endRemoveRows()  # 안전
            _safe_message(None, "오류", "잘못된 파일입니다.", str(e))
            return False

    def dataframe(self) -> pd.DataFrame:
        try:
            return self._df.copy()
        except Exception:
            return pd.DataFrame()


# ===== 워터마크 테이블 뷰(안전) =====
class WatermarkTableView(QtWidgets.QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self._pixmap: Optional[QtGui.QPixmap] = None
            self._opacity: float = 0.12
            # 대용량 대응: Interactive 기본
            self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
            self.horizontalHeader().setDefaultSectionSize(120)
            self.setAlternatingRowColors(True)
            self.setSortingEnabled(True)
            self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
            self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        except Exception as e:
            _safe_message(None, "오류", "테이블 초기화 중 오류가 발생했습니다.", str(e))

    def setWatermarkPixmap(self, pm: Optional[QtGui.QPixmap]):
        try:
            self._pixmap = pm
            self.viewport().update()
        except Exception:
            pass

    def setOpacity(self, value: float):
        try:
            self._opacity = max(0.0, min(1.0, value))
            self.viewport().update()
        except Exception:
            pass

    def paintEvent(self, e: QtGui.QPaintEvent):
        try:
            super().paintEvent(e)
            pm = self._pixmap
            if not pm or pm.isNull():
                return
            p = QtGui.QPainter(self.viewport())
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            p.setOpacity(self._opacity)
            vw, vh = self.viewport().width(), self.viewport().height()
            scale = min(vw / pm.width(), vh / pm.height()) * 0.6
            if scale <= 0:
                p.end(); return
            w, h = int(pm.width()*scale), int(pm.height()*scale)
            x, y = (vw - w)//2, (vh - h)//2
            p.drawPixmap(QtCore.QRect(x, y, w, h), pm)
            p.end()
        except Exception:
            # 그리기 실패해도 무시 (UI 유지)
            pass


# ===== 메인 윈도우 =====
class MainWindow(QtWidgets.QMainWindow):
    MAX_PREVIEW_COLUMNS = 200

    def __init__(self):
        super().__init__()
        try:
            self.setWindowTitle("JSON Table Editor — Pink Theme (Safe)")
            self.resize(1360, 840)
            self._root_json: Any = None

            splitter = QtWidgets.QSplitter(self)
            splitter.setOrientation(QtCore.Qt.Horizontal)

            # 좌측 트리
            left = QtWidgets.QWidget(self)
            left_layout = QtWidgets.QVBoxLayout(left)
            left_layout.setContentsMargins(8,8,8,8); left_layout.setSpacing(6)

            self.tree = QtWidgets.QTreeWidget()
            self.tree.setHeaderLabels(["Key/Index", "Type", "Path"])
            self.tree.setColumnWidth(0, 220)
            self.tree.setColumnWidth(1, 90)
            self.tree.setColumnHidden(2, True)  # 내부 경로 저장
            left_layout.addWidget(self.tree, 1)

            # 우측
            right = QtWidgets.QWidget(self)
            right_layout = QtWidgets.QVBoxLayout(right)
            right_layout.setContentsMargins(8,8,8,8); right_layout.setSpacing(6)

            # 상단 도구막대
            toolbar = QtWidgets.QHBoxLayout()
            self.btn_open = QtWidgets.QPushButton("JSON 열기")
            self.btn_save_json = QtWidgets.QPushButton("JSON 저장")
            self.btn_csv = QtWidgets.QPushButton("CSV로 내보내기")
            self.btn_xlsx = QtWidgets.QPushButton("엑셀(XLSX)로 내보내기")
            self.btn_add = QtWidgets.QPushButton("행 추가")
            self.btn_del = QtWidgets.QPushButton("선택 행 삭제")

            toolbar.addWidget(self.btn_open)
            toolbar.addSpacing(10)
            toolbar.addWidget(self.btn_save_json)
            toolbar.addWidget(self.btn_csv)
            toolbar.addWidget(self.btn_xlsx)
            toolbar.addSpacing(20)
            toolbar.addWidget(self.btn_add)
            toolbar.addWidget(self.btn_del)
            toolbar.addStretch(1)

            # 배경 투명도
            self.opacity_label = QtWidgets.QLabel("배경 투명도")
            self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.slider.setRange(0, 100); self.slider.setValue(12)
            toolbar.addWidget(self.opacity_label); toolbar.addWidget(self.slider)

            right_layout.addLayout(toolbar)

            self.table = WatermarkTableView(self)
            right_layout.addWidget(self.table, 1)

            self.status = QtWidgets.QLabel("파일을 열어 주세요."); self.status.setObjectName("statusLabel")
            right_layout.addWidget(self.status)

            splitter.addWidget(left); splitter.addWidget(right)
            splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1)
            self.setCentralWidget(splitter)

            # 시그널 (모두 try/except로 보호)
            self.btn_open.clicked.connect(lambda: self._safe_call(self.on_open))
            self.btn_save_json.clicked.connect(lambda: self._safe_call(self.on_save_json))
            self.btn_csv.clicked.connect(lambda: self._safe_call(self.on_export_csv))
            self.btn_xlsx.clicked.connect(lambda: self._safe_call(self.on_export_xlsx))
            self.btn_add.clicked.connect(lambda: self._safe_call(self.on_add_row))
            self.btn_del.clicked.connect(lambda: self._safe_call(self.on_del_rows))
            self.slider.valueChanged.connect(lambda v: self._safe_call(lambda: self.table.setOpacity(v/100.0)))
            self.tree.itemSelectionChanged.connect(lambda: self._safe_call(self.on_tree_selection_changed))

            self._apply_embedded_background()
        except Exception as e:
            _safe_message(self, "오류", "초기화 중 오류가 발생했습니다.", str(e))

    def _safe_call(self, fn):
        try:
            fn()
        except Exception as e:
            # 어떤 핸들러도 앱을 죽이지 않음
            _safe_message(self, "오류", "잘못된 파일입니다.", "".join(traceback.format_exception_only(type(e), e)))

    # --- 내장 배경 적용
    def _apply_embedded_background(self):
        try:
            raw = QtCore.QByteArray.fromBase64(BACKGROUND_IMAGE_B64.encode("ascii"))
            pm = QtGui.QPixmap()
            if pm.loadFromData(raw):
                self.table.setWatermarkPixmap(pm)
                self.status.setText("기본 배경 이미지가 적용되었습니다.")
        except Exception as e:
            _safe_message(self, "오류", "배경 이미지 적용 중 오류가 발생했습니다.", str(e))

    # --- 파일 열기
    def on_open(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "JSON 파일 선택", "", "JSON files (*.json);;All files (*)")
        if not path:
            return
        try:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._root_json = json.load(f)
            except UnicodeDecodeError:
                with open(path, "r", encoding="cp949") as f:
                    self._root_json = json.load(f)
        except Exception as e:
            self._root_json = None
            self._show_empty_table()
            _safe_message(self, "오류", "잘못된 파일입니다.", str(e))
            return

        # 트리 구성
        try:
            self.tree.clear()
            root_item = QtWidgets.QTreeWidgetItem(["<root>", _kind_label(self._root_json), ""])
            self.tree.addTopLevelItem(root_item)
            build_json_tree(self._root_json, root_item, "")
            self.tree.expandToDepth(1)
        except Exception as e:
            _safe_message(self, "오류", "잘못된 파일입니다.", str(e))

        # 루트 표시
        self._show_object_as_table(self._root_json)
        self.status.setText(f"로드 완료: {path}")

    def _show_empty_table(self):
        try:
            self.table.setModel(PandasTableModel(pd.DataFrame()))
            self.status.setText("표시할 데이터가 없습니다.")
        except Exception:
            pass

    # --- 트리 선택 변경
    def on_tree_selection_changed(self):
        if self._root_json is None:
            _safe_message(self, "오류", "잘못된 파일입니다.")
            return
        try:
            items = self.tree.selectedItems()
            target = self._root_json if not items else resolve_json_path(self._root_json, items[0].text(2))
            if target is None:
                _safe_message(self, "오류", "잘못된 파일입니다.")
                return
            self._show_object_as_table(target)
        except Exception as e:
            _safe_message(self, "오류", "잘못된 파일입니다.", str(e))

    # --- 객체 → 표 표시
    def _show_object_as_table(self, obj: Any):
        try:
            df = to_dataframe_any(obj)
            if len(df.columns) > self.MAX_PREVIEW_COLUMNS:
                df = df[df.columns[:self.MAX_PREVIEW_COLUMNS]]
                _safe_message(self, "알림", f"컬럼이 많아 처음 {self.MAX_PREVIEW_COLUMNS}개만 표시합니다.")
            self.table.setModel(PandasTableModel(df))
            self.status.setText(f"행 {len(df)}, 열 {len(df.columns)}")
        except Exception as e:
            self._show_empty_table()
            _safe_message(self, "오류", "잘못된 파일입니다.", str(e))

    # --- 현재 DF 얻기
    def _current_df(self) -> Optional[pd.DataFrame]:
        try:
            m = self.table.model()
            return m.dataframe() if isinstance(m, PandasTableModel) else None
        except Exception:
            return None

    # --- 저장/내보내기
    def on_save_json(self):
        df = self._current_df()
        if df is None:
            _safe_message(self, "오류", "잘못된 파일입니다.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "JSON로 저장", "", "JSON files (*.json)")
        if not path:
            return
        try:
            rows: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                obj: Dict[str, Any] = {}
                for c, v in row.items():
                    if isinstance(v, str):
                        # JSON/불리언/숫자 캐스팅 시도
                        try:
                            obj[c] = json.loads(v)
                        except Exception:
                            low = v.strip().lower()
                            if low in ("true", "false"):
                                obj[c] = (low == "true")
                            else:
                                try:
                                    obj[c] = float(v) if "." in v else int(v)
                                except Exception:
                                    obj[c] = v
                    else:
                        obj[c] = (None if (isinstance(v, float) and pd.isna(v)) else v)
                rows.append(obj)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            QtWidgets.QMessageBox.information(self, "완료", f"저장됨: {path}")
        except Exception as e:
            _safe_message(self, "오류", "잘못된 파일입니다.", str(e))

    def on_export_csv(self):
        df = self._current_df()
        if df is None:
            _safe_message(self, "오류", "잘못된 파일입니다.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "CSV로 저장", "", "CSV files (*.csv)")
        if not path:
            return
        try:
            df.to_csv(path, index=False, encoding="utf-8-sig")
            QtWidgets.QMessageBox.information(self, "완료", f"저장됨: {path}")
        except Exception as e:
            _safe_message(self, "오류", "잘못된 파일입니다.", str(e))

    def on_export_xlsx(self):
        df = self._current_df()
        if df is None:
            _safe_message(self, "오류", "잘못된 파일입니다.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "엑셀(xlsx)로 저장", "", "Excel Workbook (*.xlsx)")
        if not path:
            return
        try:
            df.to_excel(path, index=False)
            QtWidgets.QMessageBox.information(self, "완료", f"저장됨: {path}")
        except Exception as e:
            _safe_message(self, "오류", "잘못된 파일입니다.", str(e))

    # --- 행 조작
    def on_add_row(self):
        try:
            m = self.table.model()
            if isinstance(m, PandasTableModel):
                m.insertRows(m.rowCount(), 1)
                self.status.setText("행 1개 추가")
            else:
                _safe_message(self, "오류", "잘못된 파일입니다.")
        except Exception as e:
            _safe_message(self, "오류", "잘못된 파일입니다.", str(e))

    def on_del_rows(self):
        try:
            m = self.table.model()
            if not isinstance(m, PandasTableModel):
                _safe_message(self, "오류", "잘못된 파일입니다.")
                return
            sel = self.table.selectionModel().selectedRows()
            if not sel:
                _safe_message(self, "알림", "삭제할 행을 선택하세요.")
                return
            for r in sorted([s.row() for s in sel], reverse=True):
                m.removeRows(r, 1)
            self.status.setText(f"행 {len(sel)}개 삭제")
        except Exception as e:
            _safe_message(self, "오류", "잘못된 파일입니다.", str(e))


# ===== 엔트리 포인트 =====
def main():
    app = QtWidgets.QApplication(sys.argv)
    apply_pink_theme(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()