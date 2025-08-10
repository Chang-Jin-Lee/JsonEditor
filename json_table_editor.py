# json_table_editor.py
# ------------------------------------------------------------
# 기능 요약
# - JSON 열기 → 테이블로 평탄화 표시 (배열[객체] 또는 객체 내부의 List[Dict] 경로 선택)
# - 셀 직접 편집 가능 (더블클릭/엔터)
# - 행 추가/삭제
# - CSV / XLSX / JSON 저장
# - 배경 워터마크 이미지 깔기(개발자 또는 사용자 지정), 투명도 슬라이더로 조절
# ------------------------------------------------------------

import json
import sys
import math
from typing import Any, List, Optional

import pandas as pd
from PySide6 import QtCore, QtGui, QtWidgets


# ---------------- 공용 유틸 ----------------
def find_record_paths(obj: Any, max_depth: int = 4) -> List[str]:
    """Dict 내부에서 List[Dict] 구조 경로를 'a.b.c' 형태로 탐색"""
    paths = []

    def _walk(node, path, depth):
        if depth > max_depth:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                new_path = f"{path}.{k}" if path else k
                if isinstance(v, list) and v and all(isinstance(i, dict) for i in v):
                    paths.append(new_path)
                _walk(v, new_path, depth + 1)
        elif isinstance(node, list):
            for i, v in enumerate(node[:5]):
                _walk(v, path, depth + 1)

    if isinstance(obj, dict):
        _walk(obj, "", 0)
    return paths


def get_by_path(d: dict, path: str):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# ---------------- 데이터 모델 ----------------
class PandasTableModel(QtCore.QAbstractTableModel):
    """편집 가능한 pandas DataFrame 모델"""
    def __init__(self, df: pd.DataFrame):
        super().__init__()
        self._df = df.copy()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self._df.columns)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        value = self._df.iat[index.row(), index.column()]
        if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
            if pd.isna(value):
                return ""
            return str(value)
        return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    def flags(self, index):
        if not index.isValid():
            return QtCore.Qt.ItemIsEnabled
        return (
            QtCore.Qt.ItemIsSelectable
            | QtCore.Qt.ItemIsEnabled
            | QtCore.Qt.ItemIsEditable
        )

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if not index.isValid() or role != QtCore.Qt.EditRole:
            return False
        # 단순 문자열 입력을 원형 타입으로 캐스팅 시도
        col = self._df.columns[index.column()]
        orig = self._df.iat[index.row(), index.column()]
        new_val = value
        # JSON 문자열 → dict/list 캐스팅 시도
        if isinstance(orig, (dict, list)):
            try:
                new_val = json.loads(value)
            except Exception:
                # 실패하면 그냥 문자열로 둔다
                new_val = value
        self._df.iat[index.row(), index.column()] = new_val
        self.dataChanged.emit(index, index, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
        return True

    # 행 조작
    def insertRows(self, position, rows=1, parent=QtCore.QModelIndex()):
        self.beginInsertRows(QtCore.QModelIndex(), position, position + rows - 1)
        empty_row = {c: "" for c in self._df.columns}
        for _ in range(rows):
            self._df = pd.concat(
                [self._df.iloc[:position], pd.DataFrame([empty_row]), self._df.iloc[position:]],
                ignore_index=True
            )
        self.endInsertRows()
        return True

    def removeRows(self, position, rows=1, parent=QtCore.QModelIndex()):
        if position < 0 or position + rows > len(self._df):
            return False
        self.beginRemoveRows(QtCore.QModelIndex(), position, position + rows - 1)
        self._df = self._df.drop(self._df.index[position:position+rows]).reset_index(drop=True)
        self.endRemoveRows()
        return True

    def dataframe(self) -> pd.DataFrame:
        return self._df.copy()


# ---------------- 워터마크 가능한 테이블뷰 ----------------
class WatermarkTableView(QtWidgets.QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._watermark_pixmap: Optional[QtGui.QPixmap] = None
        self._opacity: float = 0.10  # 0.0 ~ 1.0

        # 보기 편의 설정
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

    def setWatermark(self, pixmap: Optional[QtGui.QPixmap]):
        self._watermark_pixmap = pixmap
        self.viewport().update()

    def setOpacity(self, value: float):
        self._opacity = max(0.0, min(1.0, value))
        self.viewport().update()

    def paintEvent(self, event: QtGui.QPaintEvent):
        # 먼저 기본 페인트 (표) → 그 위에 "뒤면"에 보이도록 살짝
        super().paintEvent(event)
        if self._watermark_pixmap and not self._watermark_pixmap.isNull():
            painter = QtGui.QPainter(self.viewport())
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            painter.setOpacity(self._opacity)

            vw = self.viewport().width()
            vh = self.viewport().height()
            pm = self._watermark_pixmap

            # 중앙에 적당한 크기로 배치
            scale = min(vw / pm.width(), vh / pm.height()) * 0.6
            if scale <= 0:
                return
            w = int(pm.width() * scale)
            h = int(pm.height() * scale)
            x = (vw - w) // 2
            y = (vh - h) // 2

            target_rect = QtCore.QRect(x, y, w, h)
            painter.drawPixmap(target_rect, pm)
            painter.end()


# ---------------- 메인 윈도우 ----------------
class MainWindow(QtWidgets.QMainWindow):
    MAX_PREVIEW_COLUMNS = 200

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JSON Table Editor (편집 + 워터마크)")
        self.resize(1280, 800)

        self._df: Optional[pd.DataFrame] = None
        self._current_json_path: Optional[str] = None
        self._loaded_structure_note: str = ""  # 저장 안내용

        # 중앙 위젯 레이아웃
        central = QtWidgets.QWidget(self)
        vbox = QtWidgets.QVBoxLayout(central)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        # 상단 도구막대
        toolbar = QtWidgets.QHBoxLayout()
        self.btn_open = QtWidgets.QPushButton("JSON 열기")
        self.btn_save_json = QtWidgets.QPushButton("JSON 저장")
        self.btn_export_csv = QtWidgets.QPushButton("CSV로 내보내기")
        self.btn_export_xlsx = QtWidgets.QPushButton("엑셀(XLSX)로 내보내기")

        self.btn_add_row = QtWidgets.QPushButton("행 추가")
        self.btn_del_row = QtWidgets.QPushButton("선택 행 삭제")

        toolbar.addWidget(self.btn_open)
        toolbar.addSpacing(10)
        toolbar.addWidget(self.btn_save_json)
        toolbar.addWidget(self.btn_export_csv)
        toolbar.addWidget(self.btn_export_xlsx)
        toolbar.addSpacing(20)
        toolbar.addWidget(self.btn_add_row)
        toolbar.addWidget(self.btn_del_row)
        toolbar.addStretch(1)

        # 워터마크 설정
        self.btn_set_bg = QtWidgets.QPushButton("배경 이미지 설정")
        self.opacity_label = QtWidgets.QLabel("투명도:")
        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(12)  # 0.12 정도
        toolbar.addWidget(self.btn_set_bg)
        toolbar.addWidget(self.opacity_label)
        toolbar.addWidget(self.opacity_slider)

        vbox.addLayout(toolbar)

        # 테이블
        self.table = WatermarkTableView(self)
        vbox.addWidget(self.table, 1)

        # 상태바
        self.status = QtWidgets.QLabel("파일을 열어주세요.")
        vbox.addWidget(self.status)

        self.setCentralWidget(central)

        # 시그널
        self.btn_open.clicked.connect(self.on_open_json)
        self.btn_save_json.clicked.connect(self.on_save_json)
        self.btn_export_csv.clicked.connect(self.on_export_csv)
        self.btn_export_xlsx.clicked.connect(self.on_export_xlsx)
        self.btn_add_row.clicked.connect(self.on_add_row)
        self.btn_del_row.clicked.connect(self.on_del_row)

        self.btn_set_bg.clicked.connect(self.on_set_background)
        self.opacity_slider.valueChanged.connect(self.on_opacity_change)

    # ---------- 파일 로드/평탄화 ----------
    def _to_dataframe(self, data: Any) -> pd.DataFrame:
        if isinstance(data, list):
            if not data:
                return pd.DataFrame()
            if all(isinstance(x, dict) for x in data):
                return pd.json_normalize(data, sep=".")
            return pd.DataFrame({"value": data})

        if isinstance(data, dict):
            candidates = find_record_paths(data)
            if candidates:
                chosen, ok = QtWidgets.QInputDialog.getItem(
                    self, "경로 선택",
                    "표로 펼칠 리스트 경로를 선택하세요:",
                    candidates, 0, False
                )
                if ok and chosen:
                    records = get_by_path(data, chosen)
                    self._loaded_structure_note = f"(루트 Dict, 경로: {chosen})"
                    return pd.json_normalize(records, sep=".")
                else:
                    self._loaded_structure_note = "(루트 Dict, 단일행 평탄화)"
                    return pd.json_normalize(data, sep=".")
            else:
                self._loaded_structure_note = "(루트 Dict, 단일행 평탄화)"
                return pd.json_normalize(data, sep=".")

        return pd.DataFrame({"value": [data]})

    def on_open_json(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "JSON 파일 선택", "", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "에러", f"JSON 로드 실패: {e}")
            return

        self._current_json_path = path
        self.status.setText(f"로드 완료: {path}")

        try:
            df = self._to_dataframe(data)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "에러", f"표 변환 실패: {e}")
            return

        # 미리보기 컬럼 제한
        if len(df.columns) > self.MAX_PREVIEW_COLUMNS:
            QtWidgets.QMessageBox.information(
                self, "알림",
                f"컬럼이 {len(df.columns)}개 입니다. 미리보기로 처음 {self.MAX_PREVIEW_COLUMNS}개만 표시합니다."
            )
            df = df[df.columns[:self.MAX_PREVIEW_COLUMNS]]

        self._df = df
        model = PandasTableModel(self._df)
        self.table.setModel(model)
        self.status.setText(f"{path} {self._loaded_structure_note} | 행 {len(df)}, 열 {len(df.columns)}")

    # ---------- 저장/내보내기 ----------
    def _current_model_df(self) -> Optional[pd.DataFrame]:
        model = self.table.model()
        if not isinstance(model, PandasTableModel):
            return None
        return model.dataframe()

    def on_save_json(self):
        df = self._current_model_df()
        if df is None:
            QtWidgets.QMessageBox.information(self, "알림", "먼저 JSON을 여세요.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "JSON로 저장", "", "JSON files (*.json)"
        )
        if not path:
            return

        # 현재 테이블을 JSON 배열[객체]로 저장
        try:
            # 문자열로 저장된 dict/list를 복원 시도
            rows = []
            for _, row in df.iterrows():
                obj = {}
                for c, v in row.items():
                    if isinstance(v, str):
                        # dict/list 문자열이면 복원
                        try:
                            parsed = json.loads(v)
                            obj[c] = parsed
                        except Exception:
                            obj[c] = v
                    else:
                        obj[c] = v if pd.notna(v) else None
                rows.append(obj)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            QtWidgets.QMessageBox.information(self, "완료", f"저장됨: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "에러", f"저장 실패: {e}")

    def on_export_csv(self):
        df = self._current_model_df()
        if df is None:
            QtWidgets.QMessageBox.information(self, "알림", "먼저 JSON을 여세요.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "CSV로 저장", "", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            df.to_csv(path, index=False, encoding="utf-8-sig")
            QtWidgets.QMessageBox.information(self, "완료", f"저장됨: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "에러", f"저장 실패: {e}")

    def on_export_xlsx(self):
        df = self._current_model_df()
        if df is None:
            QtWidgets.QMessageBox.information(self, "알림", "먼저 JSON을 여세요.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "엑셀(xlsx)로 저장", "", "Excel Workbook (*.xlsx)"
        )
        if not path:
            return
        try:
            df.to_excel(path, index=False)
            QtWidgets.QMessageBox.information(self, "완료", f"저장됨: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "에러", f"저장 실패: {e}")

    # ---------- 행 조작 ----------
    def on_add_row(self):
        model = self.table.model()
        if not isinstance(model, PandasTableModel):
            return
        pos = model.rowCount()
        model.insertRows(pos, 1)
        self.status.setText("행 1개 추가")

    def on_del_row(self):
        model = self.table.model()
        if not isinstance(model, PandasTableModel):
            return
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            QtWidgets.QMessageBox.information(self, "알림", "삭제할 행을 선택하세요.")
            return
        rows = sorted([s.row() for s in sel], reverse=True)
        for r in rows:
            model.removeRows(r, 1)
        self.status.setText(f"행 {len(rows)}개 삭제")

    # ---------- 워터마크 ----------
    def on_set_background(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "배경 이미지 선택", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        pm = QtGui.QPixmap(path)
        if pm.isNull():
            QtWidgets.QMessageBox.warning(self, "경고", "이미지를 불러올 수 없습니다.")
            return
        self.table.setWatermark(pm)
        self.status.setText(f"배경 이미지 설정됨: {path}")

    def on_opacity_change(self, value: int):
        self.table.setOpacity(value / 100.0)


def main():
    app = QtWidgets.QApplication(sys.argv)
    # 폰트/룩앤필 약간 개선(선택)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
