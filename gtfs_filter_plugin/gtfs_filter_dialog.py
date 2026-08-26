# -*- coding: utf-8 -*-
"""
Interface du plugin GTFS Filter.
Construit dynamiquement les filtres disponibles selon le GTFS charge.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QFileDialog, QListWidget,
    QListWidgetItem, QAbstractItemView, QDateEdit, QTimeEdit,
    QCheckBox, QComboBox, QMessageBox, QScrollArea, QWidget,
    QTabWidget
)
from qgis.PyQt.QtCore import QDate, QTime
from qgis.utils import iface
from qgis.core import QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsProject, QgsRectangle

from . import gtfs_core


class GtfsFilterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GTFS Filter")
        self.resize(600, 700)

        self.tables = None
        self.original_names = None
        self.summary = None

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Fichier source ---
        file_box = QGroupBox("Fichier GTFS source")
        file_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        browse_btn = QPushButton("Parcourir…")
        browse_btn.clicked.connect(self._browse_input)
        load_btn = QPushButton("Charger")
        load_btn.clicked.connect(self._load_gtfs)
        file_layout.addWidget(self.input_edit)
        file_layout.addWidget(browse_btn)
        file_layout.addWidget(load_btn)
        file_box.setLayout(file_layout)
        main_layout.addWidget(file_box)

        self.status_label = QLabel("Aucun GTFS chargé.")
        main_layout.addWidget(self.status_label)

        # --- Onglets de filtres ---
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, stretch=1)

        self.tab_mode = self._make_scroll_tab()
        self.tab_lignes = self._make_scroll_tab()
        self.tab_temporel = self._make_scroll_tab()
        self.tab_spatial = self._make_scroll_tab()
        self.tab_confort = self._make_scroll_tab()

        self.tabs.addTab(self.tab_mode[0], "Mode / Agence")
        self.tabs.addTab(self.tab_lignes[0], "Lignes / Trips")
        self.tabs.addTab(self.tab_temporel[0], "Date / Horaire")
        self.tabs.addTab(self.tab_spatial[0], "Arrêts / Emprise")
        self.tabs.addTab(self.tab_confort[0], "Accessibilité / Vélo / Sens")

        self._build_tab_mode()
        self._build_tab_lignes()
        self._build_tab_temporel()
        self._build_tab_spatial()
        self._build_tab_confort()

        # --- Sortie + actions ---
        out_box = QGroupBox("Fichier de sortie")
        out_layout = QHBoxLayout()
        self.output_edit = QLineEdit()
        out_browse_btn = QPushButton("Parcourir…")
        out_browse_btn.clicked.connect(self._browse_output)
        out_layout.addWidget(self.output_edit)
        out_layout.addWidget(out_browse_btn)
        out_box.setLayout(out_layout)
        main_layout.addWidget(out_box)

        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("Filtrer et exporter")
        self.run_btn.clicked.connect(self._run_filter)
        close_btn = QPushButton("Fermer")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

    def _make_scroll_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        inner_layout = QVBoxLayout(inner)
        return widget, inner_layout

    def _build_tab_mode(self):
        _, layout = self.tab_mode
        layout.addWidget(QLabel("Modes de transport (route_type) :"))
        self.list_route_types = QListWidget()
        self.list_route_types.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.list_route_types)

        layout.addWidget(QLabel("Agences (agency_id) :"))
        self.list_agencies = QListWidget()
        self.list_agencies.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.list_agencies)
        layout.addStretch()

    def _build_tab_lignes(self):
        _, layout = self.tab_lignes
        layout.addWidget(QLabel("Lignes (route_short_name / route_long_name) :"))
        self.line_search = QLineEdit()
        self.line_search.setPlaceholderText("Filtrer la liste (recherche texte)…")
        self.line_search.textChanged.connect(self._filter_route_list)
        layout.addWidget(self.line_search)
        self.list_routes = QListWidget()
        self.list_routes.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.list_routes)

        layout.addWidget(QLabel("Trip ID précis (optionnel, séparés par virgule) :"))
        self.trip_id_edit = QLineEdit()
        self.trip_id_edit.setPlaceholderText("ex: VJ_123, VJ_456")
        layout.addWidget(self.trip_id_edit)
        layout.addStretch()

    def _build_tab_temporel(self):
        _, layout = self.tab_temporel
        form = QFormLayout()

        self.date_checkbox = QCheckBox("Filtrer par date précise")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setEnabled(False)
        self.date_checkbox.toggled.connect(self.date_edit.setEnabled)
        form.addRow(self.date_checkbox, self.date_edit)
        self.date_range_label = QLabel("")
        form.addRow(QLabel(""), self.date_range_label)

        self.time_checkbox = QCheckBox("Filtrer par plage horaire")
        self.start_time_edit = QTimeEdit(QTime(6, 0, 0))
        self.end_time_edit = QTimeEdit(QTime(9, 0, 0))
        self.start_time_edit.setEnabled(False)
        self.end_time_edit.setEnabled(False)
        self.time_checkbox.toggled.connect(self.start_time_edit.setEnabled)
        self.time_checkbox.toggled.connect(self.end_time_edit.setEnabled)
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("de"))
        time_layout.addWidget(self.start_time_edit)
        time_layout.addWidget(QLabel("à"))
        time_layout.addWidget(self.end_time_edit)
        form.addRow(self.time_checkbox, time_layout)

        layout.addLayout(form)
        layout.addStretch()

    def _build_tab_spatial(self):
        _, layout = self.tab_spatial
        layout.addWidget(QLabel(
            "Stop ID précis (optionnel, séparés par virgule) :"
        ))
        self.stop_id_edit = QLineEdit()
        self.stop_id_edit.setPlaceholderText("ex: STIF:StopPoint:Q:12345:")
        layout.addWidget(self.stop_id_edit)

        self.bbox_checkbox = QCheckBox("Restreindre à l'emprise actuelle de la carte QGIS")
        layout.addWidget(self.bbox_checkbox)
        self.bbox_label = QLabel("")
        layout.addWidget(self.bbox_label)
        layout.addStretch()

    def _build_tab_confort(self):
        _, layout = self.tab_confort
        form = QFormLayout()

        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["Peu importe", "Aller (0)", "Retour (1)"])
        form.addRow("Sens (direction_id) :", self.direction_combo)

        self.wheelchair_combo = QComboBox()
        self.wheelchair_combo.addItems([
            "Peu importe", "Non renseigné (0)", "Accessible (1)", "Non accessible (2)"
        ])
        form.addRow("Accessibilité fauteuil (trips) :", self.wheelchair_combo)

        self.bikes_combo = QComboBox()
        self.bikes_combo.addItems([
            "Peu importe", "Non renseigné (0)", "Vélos autorisés (1)", "Vélos interdits (2)"
        ])
        form.addRow("Vélos autorisés (trips) :", self.bikes_combo)

        layout.addLayout(form)
        layout.addStretch()

    # ------------------------------------------------------------- actions
    def _browse_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un GTFS", "", "GTFS zip (*.zip)")
        if path:
            self.input_edit.setText(path)

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer sous", "", "GTFS zip (*.zip)")
        if path:
            if not path.lower().endswith(".zip"):
                path += ".zip"
            self.output_edit.setText(path)

    def _load_gtfs(self):
        path = self.input_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "GTFS Filter", "Choisis d'abord un fichier GTFS.")
            return
        try:
            self.tables, self.original_names = gtfs_core.load_gtfs(path)
            self.summary = gtfs_core.summarize(self.tables)
        except Exception as e:
            QMessageBox.critical(self, "GTFS Filter", f"Erreur de lecture du GTFS :\n{e}")
            return

        self._populate_from_summary()
        n_routes = len(self.summary["routes"])
        n_stops = self.summary["n_stops"]
        self.status_label.setText(f"GTFS chargé : {n_routes} lignes, {n_stops} arrêts.")

    def _populate_from_summary(self):
        s = self.summary

        self.list_route_types.clear()
        for rt in s["route_types"]:
            label = gtfs_core.ROUTE_TYPE_LABELS.get(rt, f"Type {rt}")
            item = QListWidgetItem(f"{label} ({rt})")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, rt)
            self.list_route_types.addItem(item)

        self.list_agencies.clear()
        for aid in s["agency_ids"]:
            name = s["agency_names"].get(aid, "")
            item = QListWidgetItem(f"{name} ({aid})" if name else aid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, aid)
            self.list_agencies.addItem(item)

        self._all_routes = s["routes"]
        self._populate_route_list(self._all_routes)

        if s["date_min"] and s["date_max"]:
            self.date_range_label.setText(f"Plage disponible dans le feed : {s['date_min']} → {s['date_max']}")
            try:
                qd = QDate.fromString(s["date_min"], "yyyyMMdd")
                if qd.isValid():
                    self.date_edit.setDate(qd)
            except Exception:
                pass

        if s["bbox"]:
            min_lon, min_lat, max_lon, max_lat = s["bbox"]
            self.bbox_label.setText(
                f"Emprise des arrêts du feed : {min_lon:.4f}, {min_lat:.4f} → {max_lon:.4f}, {max_lat:.4f}"
            )

    def _populate_route_list(self, routes):
        self.list_routes.clear()
        for r in routes:
            label = f"{r['short_name']} — {r['long_name']}" if r['short_name'] else r['long_name'] or r['route_id']
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, r["route_id"])
            self.list_routes.addItem(item)

    def _filter_route_list(self, text):
        text = text.lower().strip()
        if not text:
            self._populate_route_list(self._all_routes)
            return
        filtered = [
            r for r in self._all_routes
            if text in (r["short_name"] or "").lower() or text in (r["long_name"] or "").lower()
        ]
        self._populate_route_list(filtered)

    def _get_checked_values(self, list_widget):
        values = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.checkState() == Qt.Checked:
                values.append(item.data(Qt.UserRole))
        return values

    def _get_current_canvas_bbox_wgs84(self):
        canvas = iface.mapCanvas()
        extent = canvas.extent()
        src_crs = canvas.mapSettings().destinationCrs()
        dst_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        if src_crs != dst_crs:
            transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            extent = transform.transformBoundingBox(extent)
        return (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())

    def _collect_filters(self):
        filters = {}

        route_types = self._get_checked_values(self.list_route_types)
        if route_types:
            filters["route_types"] = route_types

        agency_ids = self._get_checked_values(self.list_agencies)
        if agency_ids:
            filters["agency_ids"] = agency_ids

        route_ids = self._get_checked_values(self.list_routes)
        if route_ids:
            filters["route_ids"] = route_ids

        trip_text = self.trip_id_edit.text().strip()
        if trip_text:
            filters["trip_ids"] = [t.strip() for t in trip_text.split(",") if t.strip()]

        if self.date_checkbox.isChecked():
            filters["date"] = self.date_edit.date().toString("yyyyMMdd")

        if self.time_checkbox.isChecked():
            filters["start_time"] = self.start_time_edit.time().toString("HH:mm:ss")
            filters["end_time"] = self.end_time_edit.time().toString("HH:mm:ss")

        stop_text = self.stop_id_edit.text().strip()
        if stop_text:
            filters["stop_ids"] = [s.strip() for s in stop_text.split(",") if s.strip()]

        if self.bbox_checkbox.isChecked():
            filters["bbox"] = self._get_current_canvas_bbox_wgs84()

        if self.direction_combo.currentIndex() == 1:
            filters["direction_id"] = "0"
        elif self.direction_combo.currentIndex() == 2:
            filters["direction_id"] = "1"

        if self.wheelchair_combo.currentIndex() > 0:
            filters["wheelchair_trips"] = str(self.wheelchair_combo.currentIndex() - 1)

        if self.bikes_combo.currentIndex() > 0:
            filters["bikes_allowed"] = str(self.bikes_combo.currentIndex() - 1)

        return filters

    def _run_filter(self):
        if not self.tables:
            QMessageBox.warning(self, "GTFS Filter", "Charge d'abord un GTFS.")
            return
        output_path = self.output_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "GTFS Filter", "Choisis un fichier de sortie.")
            return

        filters = self._collect_filters()
        try:
            filtered_tables, stats = gtfs_core.apply_filters(self.tables, filters)
            gtfs_core.write_gtfs(filtered_tables, self.original_names, output_path)
        except Exception as e:
            QMessageBox.critical(self, "GTFS Filter", f"Erreur pendant le filtrage :\n{e}")
            return

        msg = "\n".join(f"{k} : {v[0]} / {v[1]}" for k, v in stats.items())
        QMessageBox.information(
            self, "GTFS Filter",
            f"Export terminé :\n{output_path}\n\n{msg}"
        )
