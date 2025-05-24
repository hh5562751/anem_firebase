# main_app.py
import sys
import json
import os
import logging
import random
import time 
import webbrowser 

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QMessageBox, QHeaderView, QStatusBar, QFrame, QAction, QStyle,
    QMenu, QLineEdit, QComboBox, QAbstractItemView, QDesktopWidget, QDialog
)
from PyQt5.QtCore import QTimer, Qt, QDateTime, QLocale, QStandardPaths, QUrl
from PyQt5.QtGui import QIcon, QColor, QPalette, QDesktopServices, QFontDatabase

from firebase_service import FirebaseService
from gui_components import ToastNotification, AddMemberDialog, EditMemberDialog, SettingsDialog, ViewMemberDialog, ActivationDialog

from api_client import AnemAPIClient
from member import Member 
from threads import FetchInitialInfoThread, MonitoringThread, SingleMemberCheckThread, DownloadAllPdfsThread 
from config import (
    LOG_FILE, DATA_FILE, STYLESHEET_FILE, SETTINGS_FILE,
    DEFAULT_SETTINGS, SETTING_MIN_MEMBER_DELAY, SETTING_MAX_MEMBER_DELAY,
    SETTING_MONITORING_INTERVAL, SETTING_BACKOFF_429, SETTING_BACKOFF_GENERAL,
    SETTING_REQUEST_TIMEOUT, MAX_ERROR_DISPLAY_LENGTH,
    FIREBASE_SERVICE_ACCOUNT_KEY_FILE 
)
from logger_setup import setup_logging
from utils import QColorConstants, get_icon_name_for_status 

logger = setup_logging()

def load_custom_fonts():
    font_dir = "fonts" 
    if not os.path.isdir(font_dir):
        logger.warning(f"مجلد الخطوط '{font_dir}' غير موجود. لن يتم تحميل الخطوط المخصصة.")
        return

    font_files = [
        "Tajawal-Regular.ttf", "Tajawal-Medium.ttf", "Tajawal-Bold.ttf",
        "Tajawal-ExtraBold.ttf", "Tajawal-Light.ttf", 
        "Tajawal-ExtraLight.ttf", "Tajawal-Black.ttf"     
    ]
    loaded_fonts_count = 0
    for font_file in font_files:
        font_path = os.path.join(font_dir, font_file)
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                font_families = QFontDatabase.applicationFontFamilies(font_id)
                if font_families:
                    logger.info(f"تم تحميل الخط بنجاح: {font_file} (العائلة: {font_families[0]})")
                    loaded_fonts_count +=1
            else: logger.warning(f"فشل تحميل الخط: {font_file} من المسار: {font_path}")
        else: logger.warning(f"ملف الخط غير موجود: {font_path}")
    if loaded_fonts_count > 0: logger.info(f"تم تحميل {loaded_fonts_count} خطوط مخصصة بنجاح.")
    else: logger.warning("لم يتم تحميل أي خطوط مخصصة.")

class AnemApp(QMainWindow):
    COL_ICON, COL_FULL_NAME_AR, COL_NIN, COL_WASSIT, COL_CCP, COL_PHONE_NUMBER, COL_STATUS, COL_RDV_DATE, COL_DETAILS = range(9)

    def __init__(self):
        super().__init__()
        self._should_initialize_ui = False 
        logger.info("AnemApp __init__: بدء التهيئة الأولية.")
        self._initialize_and_check_activation() 
        if not self.activation_successful:
            logger.critical("AnemApp __init__: فشل تفعيل البرنامج. لن يتم إكمال تهيئة واجهة المستخدم.")
            return 
        self._should_initialize_ui = True
        logger.info("AnemApp __init__: نجح التفعيل. جاري إكمال تهيئة واجهة المستخدم.")
        
        load_custom_fonts() 
        QApplication.setLayoutDirection(Qt.RightToLeft) 
        self.setWindowTitle("برنامج إدارة مواعيد منحة البطالة")
        desktop = QApplication.desktop()
        available_geometry = desktop.availableGeometry(self)
        self.setGeometry(available_geometry)
        self.setWindowState(Qt.WindowMaximized)
        logger.info("AnemApp __init__: تم ضبط النافذة.")

        self.settings = {}
        self.load_app_settings() 

        self.suppress_initial_messages = True 
        self.toast_notifications = [] 
        self.members_list = [] 
        self.filtered_members_list = [] 
        self.is_filter_active = False 
        
        self.api_client = AnemAPIClient(
            initial_backoff_general=self.settings.get(SETTING_BACKOFF_GENERAL, DEFAULT_SETTINGS[SETTING_BACKOFF_GENERAL]),
            initial_backoff_429=self.settings.get(SETTING_BACKOFF_429, DEFAULT_SETTINGS[SETTING_BACKOFF_429]),
            request_timeout=self.settings.get(SETTING_REQUEST_TIMEOUT, DEFAULT_SETTINGS[SETTING_REQUEST_TIMEOUT])
        )

        self.initial_fetch_threads = [] 
        self.single_check_thread = None 
        self.active_download_all_pdfs_threads = {} 
        self.active_spinner_row_in_view = -1 
        self.spinner_char_idx = 0
        self.spinner_chars = ['◐', '◓', '◑', '◒'] 
        self.row_spinner_timer = QTimer(self) 
        self.row_spinner_timer.timeout.connect(self.update_active_row_spinner_display)
        self.row_spinner_timer_interval = 150 

        self.monitoring_thread = MonitoringThread(self.members_list, self.settings.copy())
        self.monitoring_thread.update_member_gui_signal.connect(self.update_member_gui_in_table)
        self.monitoring_thread.new_data_fetched_signal.connect(self.update_member_name_in_table)
        self.monitoring_thread.global_log_signal.connect(self.update_status_bar_message) 
        self.monitoring_thread.member_being_processed_signal.connect(self.handle_member_processing_signal)
        self.monitoring_thread.countdown_update_signal.connect(self.update_countdown_timer_display) 

        self.init_ui() 
        self.load_stylesheet() 
        self.load_members_data() 
        QTimer.singleShot(0, self.apply_app_settings)
        logger.info("AnemApp __init__: اكتملت التهيئة الكاملة.")

    def _initialize_and_check_activation(self):
        logger.info("_initialize_and_check_activation: بدء تهيئة Firebase والتحقق من التفعيل.")
        self.firebase_service = FirebaseService()
        self.activation_successful = self._perform_activation_check_logic()
        logger.info(f"_initialize_and_check_activation: نتيجة التحقق من التفعيل: {self.activation_successful}")

    def _perform_activation_check_logic(self):
        logger.info("_perform_activation_check_logic: بدء التحقق من تفعيل البرنامج...")
        is_locally_activated, local_code = self.firebase_service.check_local_activation()
        if is_locally_activated:
            logger.info(f"_perform_activation_check_logic: البرنامج مفعل محليًا بالكود: {local_code}. يتم التحقق من صلاحية الكود عبر الإنترنت...")
            is_still_valid, online_message, code_data = self.firebase_service.verify_activation_code(local_code)
            
            is_status_ok_for_local = False
            if code_data and isinstance(code_data, dict):
                status_from_firebase = code_data.get("status", "").upper()
                logger.debug(f"_perform_activation_check_logic: حالة الكود المحلي '{local_code}' في Firebase هي: {status_from_firebase}")
                if status_from_firebase == "ACTIVE":
                    is_status_ok_for_local = True
            
            if is_still_valid and is_status_ok_for_local:
                logger.info(f"_perform_activation_check_logic: الكود المحلي '{local_code}' لا يزال صالحًا ومستخدمًا بشكل صحيح (ACTIVE في Firebase).")
                return True
            else:
                log_msg_invalid_local = f"_perform_activation_check_logic: الكود المحلي '{local_code}' لم يعد صالحًا (is_still_valid: {is_still_valid}, online_message: {online_message}, is_status_ok_for_local: {is_status_ok_for_local}). يتطلب إعادة تفعيل."
                if code_data: log_msg_invalid_local += f" Firebase status: {code_data.get('status')}"
                logger.warning(log_msg_invalid_local)
                try:
                    from config import ACTIVATION_STATUS_FILE as ASF_PATH 
                    if os.path.exists(ASF_PATH):
                        os.remove(ASF_PATH)
                    logger.info("_perform_activation_check_logic: تم حذف ملف التفعيل المحلي غير الصالح.")
                except Exception as e_remove:
                    logger.error(f"_perform_activation_check_logic: خطأ أثناء حذف ملف التفعيل المحلي غير الصالح: {e_remove}")
        
        logger.info("_perform_activation_check_logic: البرنامج غير مفعل محليًا أو الكود المحلي لم يعد صالحًا. يتطلب التفعيل عبر الإنترنت.")
        if not self.firebase_service.is_initialized():
            logger.critical(f"_perform_activation_check_logic: خدمة Firebase غير مهيأة. تأكد من وجود ملف '{FIREBASE_SERVICE_ACCOUNT_KEY_FILE}' وأنه صالح.")
            return False

        while True: 
            logger.debug("_perform_activation_check_logic: داخل حلقة طلب كود التفعيل.")
            activation_dialog = ActivationDialog(None) 
            screen_geometry = QApplication.desktop().screenGeometry()
            x = (screen_geometry.width() - activation_dialog.width()) // 2
            y = (screen_geometry.height() - activation_dialog.height()) // 2
            activation_dialog.move(x, y)
            
            logger.info("_perform_activation_check_logic: قبل استدعاء activation_dialog.exec_()") # رسالة تتبع جديدة
            result = activation_dialog.exec_() 
            logger.info(f"_perform_activation_check_logic: بعد استدعاء activation_dialog.exec_(). النتيجة: {result} (Accepted={QDialog.Accepted}, Rejected={QDialog.Rejected})") # رسالة تتبع جديدة

            if result == QDialog.Accepted: 
                entered_code = activation_dialog.get_activation_code()
                logger.info(f"_perform_activation_check_logic: المستخدم ضغط 'تفعيل'. الكود المدخل: '{entered_code}'")
                if not entered_code:
                    logger.warning("_perform_activation_check_logic: لم يتم إدخال كود تفعيل.")
                    QMessageBox.warning(None, "إدخال ناقص", "الرجاء إدخال كود التفعيل.")
                    continue 

                loading_msg_box = QMessageBox(QMessageBox.Information, "جاري التحقق", f"جاري التحقق من كود التفعيل: {entered_code}\nالرجاء الانتظار...", QMessageBox.NoButton, None)
                loading_msg_box.setStandardButtons(QMessageBox.NoButton)
                loading_msg_box.show()
                QApplication.processEvents() # السماح بتحديث الواجهة لإظهار الرسالة
                logger.debug(f"_perform_activation_check_logic: جاري استدعاء firebase_service.verify_activation_code('{entered_code}')")

                try:
                    is_valid, message, code_data_from_verify = self.firebase_service.verify_activation_code(entered_code)
                    logger.info(f"_perform_activation_check_logic: نتيجة verify_activation_code: is_valid={is_valid}, message='{message}'")
                except Exception as e_verify:
                    logger.exception(f"_perform_activation_check_logic: حدث خطأ استثنائي أثناء verify_activation_code: {e_verify}")
                    is_valid = False
                    message = "حدث خطأ غير متوقع أثناء التحقق من الكود. يرجى المحاولة مرة أخرى."
                finally:
                    loading_msg_box.close() 

                if is_valid:
                    device_id = self.firebase_service.get_device_id()
                    logger.info(f"_perform_activation_check_logic: كود صالح. جاري تحديث Firebase. Device ID: {device_id}")
                    mark_success = False
                    try:
                        mark_success = self.firebase_service.mark_code_as_used(entered_code, device_id)
                    except Exception as e_mark:
                        logger.exception(f"_perform_activation_check_logic: حدث خطأ استثنائي أثناء mark_code_as_used: {e_mark}")
                    
                    if mark_success:
                        self.firebase_service.save_local_activation(entered_code, device_id)
                        logger.info(f"_perform_activation_check_logic: تم تفعيل البرنامج بنجاح بالكود: {entered_code}")
                        QMessageBox.information(None, "نجاح التفعيل", "تم تفعيل البرنامج بنجاح!")
                        return True 
                    else:
                        logger.error(f"_perform_activation_check_logic: فشل تحديث حالة الكود '{entered_code}' في Firebase.")
                        QMessageBox.critical(None, "خطأ في الخادم", "حدث خطأ أثناء تحديث الكود على الخادم. يرجى المحاولة مرة أخرى أو الاتصال بالدعم.")
                        continue 
                else:
                    logger.warning(f"_perform_activation_check_logic: فشل التحقق من الكود '{entered_code}': {message}")
                    QMessageBox.warning(None, "فشل التحقق", message)
                    continue 
            
            elif result == QDialog.Rejected: 
                logger.warning("_perform_activation_check_logic: عملية التفعيل ألغيت من قبل المستخدم.")
                QMessageBox.information(None, "التفعيل مطلوب", "البرنامج يتطلب تفعيلًا للاستخدام. سيتم إغلاق التطبيق الآن.")
                return False
            else: # نتيجة غير متوقعة (مثل إغلاق النافذة بطريقة أخرى)
                logger.error(f"_perform_activation_check_logic: نتيجة غير متوقعة من activation_dialog.exec_(): {result}. سيتم اعتبار العملية ملغاة.")
                QMessageBox.information(None, "التفعيل مطلوب", "تم إلغاء عملية التفعيل. سيتم إغلاق التطبيق الآن.")
                return False
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10) 

        menubar = self.menuBar()
        file_menu = menubar.addMenu("ملف")
        settings_action = QAction(QIcon.fromTheme("preferences-system"), "الإعدادات...", self)
        settings_action.triggered.connect(self.open_settings_dialog)
        file_menu.addAction(settings_action)
        
        tools_menu = menubar.addMenu("أدوات") 
        self.toggle_search_filter_action = QAction("إظهار/إخفاء البحث والفلترة", self)
        self.toggle_search_filter_action.setCheckable(True)
        self.toggle_search_filter_action.setChecked(True) 
        self.toggle_search_filter_action.triggered.connect(self.toggle_search_filter_bar)
        tools_menu.addAction(self.toggle_search_filter_action)

        self.toggle_details_action = QAction("إظهار التفاصيل", self)
        self.toggle_details_action.setCheckable(True)
        self.toggle_details_action.setChecked(False) 
        self.toggle_details_action.triggered.connect(self.toggle_column_visibility)
        tools_menu.addAction(self.toggle_details_action)

        file_menu.addSeparator()
        exit_action = QAction(QIcon.fromTheme("application-exit"), "خروج", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        header_frame = QFrame(self)
        header_frame.setObjectName("HeaderFrame") 
        header_layout = QHBoxLayout(header_frame)
        app_title_label = QLabel("برنامج إدارة مواعيد منحة البطالة", self)
        header_layout.addWidget(app_title_label, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addStretch()
        self.datetime_label = QLabel(self)
        self.datetime_label.setObjectName("datetime_label")
        header_layout.addWidget(self.datetime_label, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.update_datetime() 
        self.datetime_timer = QTimer(self) 
        self.datetime_timer.timeout.connect(self.update_datetime)
        self.datetime_timer.start(1000)
        main_layout.addWidget(header_frame)

        self.search_filter_frame = QFrame(self)
        self.search_filter_frame.setObjectName("SearchFilterFrame")
        search_filter_layout = QHBoxLayout(self.search_filter_frame)
        search_filter_layout.setSpacing(10)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("بحث بالاسم, NIN, الوسيط...")
        self.search_input.textChanged.connect(self.apply_filter_and_search) 
        search_filter_layout.addWidget(self.search_input, 2) 

        self.filter_by_combo = QComboBox(self)
        self.filter_by_combo.addItem("فلترة حسب...", None) 
        self.filter_by_combo.addItem("الحالة", "status")
        self.filter_by_combo.addItem("لديه موعد", "has_rdv")
        self.filter_by_combo.addItem("مستفيد حاليًا", "have_allocation")
        self.filter_by_combo.addItem("تم تحميل PDF التعهد", "pdf_honneur")
        self.filter_by_combo.addItem("تم تحميل PDF الموعد", "pdf_rdv")
        self.filter_by_combo.currentIndexChanged.connect(self.on_filter_by_changed)
        search_filter_layout.addWidget(self.filter_by_combo, 1)

        self.filter_value_combo = QComboBox(self) 
        self.filter_value_combo.setVisible(False) 
        self.filter_value_combo.currentIndexChanged.connect(self.apply_filter_and_search)
        search_filter_layout.addWidget(self.filter_value_combo, 1)
        
        self.clear_filter_button = QPushButton("مسح الفلتر", self)
        self.clear_filter_button.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        self.clear_filter_button.clicked.connect(self.clear_filter_and_search)
        search_filter_layout.addWidget(self.clear_filter_button)
        
        main_layout.addWidget(self.search_filter_frame)

        main_controls_frame = QFrame(self)
        main_controls_layout = QHBoxLayout(main_controls_frame)
        section_title_label = QLabel("إدارة المستفيدين", self)
        section_title_label.setObjectName("section_title_label")
        main_controls_layout.addWidget(section_title_label, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        main_controls_layout.addStretch()
        main_layout.addWidget(main_controls_frame)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.status_bar_label = QLabel("جاهز.")
        self.last_scan_label = QLabel("") 
        self.countdown_label = QLabel("") 
        self.statusBar.addWidget(self.status_bar_label, 1) 
        self.statusBar.addPermanentWidget(self.countdown_label) 
        self.statusBar.addPermanentWidget(self.last_scan_label) 

        self.table = QTableWidget(self)
        self.table.setColumnCount(self.COL_DETAILS + 1) 
        self.table.setHorizontalHeaderLabels([
            "أيقونة", "الاسم الكامل", "رقم التعريف", "رقم الوسيط",
            "الحساب البريدي", "رقم الهاتف", "الحالة", "تاريخ الموعد", "آخر تحديث/خطأ" 
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive) 
        self.table.setAlternatingRowColors(True) 
        self.table.setEditTriggers(QTableWidget.NoEditTriggers) 
        self.table.setContextMenuPolicy(Qt.CustomContextMenu) 
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)

        self.toggle_column_visibility(self.toggle_details_action.isChecked())

        header.setSectionResizeMode(self.COL_ICON, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_FULL_NAME_AR, QHeaderView.ResizeToContents) 
        header.setSectionResizeMode(self.COL_PHONE_NUMBER, QHeaderView.ResizeToContents) 
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeToContents)
        header.setMinimumSectionSize(150) 
        header.setSectionResizeMode(self.COL_RDV_DATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_DETAILS, QHeaderView.Stretch) 

        self.table.setSelectionBehavior(QTableWidget.SelectRows) 
        self.table.verticalHeader().setDefaultSectionSize(30) 
        self.table.itemDoubleClicked.connect(self.edit_member_details)
        self.table.verticalHeader().setVisible(True) 
        main_layout.addWidget(self.table)

        bottom_controls_layout = QHBoxLayout()
        self.add_member_button = QPushButton("إضافة عضو", self)
        self.add_member_button.setObjectName("add_member_button")
        self.add_member_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        self.add_member_button.clicked.connect(self.add_member)
        bottom_controls_layout.addWidget(self.add_member_button)
        self.remove_member_button = QPushButton("حذف المحدد", self)
        self.remove_member_button.setObjectName("remove_member_button")
        self.remove_member_button.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.remove_member_button.clicked.connect(self.remove_member)
        bottom_controls_layout.addWidget(self.remove_member_button)
        bottom_controls_layout.addStretch()
        self.start_button = QPushButton("بدء المراقبة", self)
        self.start_button.setObjectName("start_button")
        self.start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.start_button.clicked.connect(self.start_monitoring)
        bottom_controls_layout.addWidget(self.start_button)
        self.stop_button = QPushButton("إيقاف المراقبة", self)
        self.stop_button.setObjectName("stop_button")
        self.stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_button.setEnabled(False) 
        self.stop_button.clicked.connect(self.stop_monitoring)
        bottom_controls_layout.addWidget(self.stop_button)
        main_layout.addLayout(bottom_controls_layout)
        
        self.update_status_bar_message("التطبيق جاهز.", is_general_message=True)
        logger.info("init_ui: اكتملت تهيئة واجهة المستخدم.")

    def toggle_search_filter_bar(self, checked):
        self.search_filter_frame.setVisible(checked)
        self.toggle_search_filter_action.setChecked(checked) 

    def on_filter_by_changed(self, index):
        filter_key = self.filter_by_combo.itemData(index)
        self.filter_value_combo.clear()
        self.filter_value_combo.setVisible(False)

        if filter_key == "status":
            statuses = sorted(list(set(m.status for m in self.members_list)))
            self.filter_value_combo.addItem("اختر الحالة...", None)
            for status in statuses:
                self.filter_value_combo.addItem(status, status)
            self.filter_value_combo.setVisible(True)
        elif filter_key in ["has_rdv", "have_allocation", "pdf_honneur", "pdf_rdv"]:
            self.filter_value_combo.addItem("اختر القيمة...", None)
            self.filter_value_combo.addItem("نعم", True)
            self.filter_value_combo.addItem("لا", False)
            self.filter_value_combo.setVisible(True)
        
        self.apply_filter_and_search() 

    def clear_filter_and_search(self):
        self.search_input.clear()
        self.filter_by_combo.setCurrentIndex(0) 
        self.filter_value_combo.clear()
        self.filter_value_combo.setVisible(False)
        self.is_filter_active = False
        self.update_table() 
        self._show_toast("تم مسح الفلتر بنجاح.", type="info") 
        self.update_status_bar_message("تم مسح الفلتر.", is_general_message=True)

    def apply_filter_and_search(self):
        search_term = self.search_input.text().lower().strip()
        filter_key = self.filter_by_combo.itemData(self.filter_by_combo.currentIndex())
        filter_value_data = self.filter_value_combo.itemData(self.filter_value_combo.currentIndex())

        current_list_to_filter = list(self.members_list) 
        
        self.is_filter_active = bool(search_term or (filter_key and filter_value_data is not None))

        if not self.is_filter_active:
            self.filtered_members_list = list(self.members_list) 
            self.update_table()
            if hasattr(self, '_last_filter_applied') and self._last_filter_applied: 
                self.update_status_bar_message("تم عرض جميع الأعضاء.", is_general_message=True)
                self._last_filter_applied = False
            return

        temp_filtered_list = []

        for member in current_list_to_filter:
            match_search = True
            if search_term:
                match_search = (search_term in (member.nin or "").lower() or
                                search_term in (member.wassit_no or "").lower() or
                                search_term in (member.get_full_name_ar() or "").lower() or
                                search_term in (member.nom_fr or "").lower() or
                                search_term in (member.prenom_fr or "").lower() or
                                search_term in (member.phone_number or "").lower() or
                                search_term in (member.ccp or "").lower())
            
            match_filter = True
            if filter_key and filter_value_data is not None:
                if filter_key == "status":
                    match_filter = member.status == filter_value_data
                elif filter_key == "has_rdv":
                    match_filter = member.already_has_rdv == filter_value_data
                elif filter_key == "have_allocation":
                    match_filter = member.have_allocation == filter_value_data
                elif filter_key == "pdf_honneur":
                    match_filter = bool(member.pdf_honneur_path) == filter_value_data
                elif filter_key == "pdf_rdv":
                    match_filter = bool(member.pdf_rdv_path) == filter_value_data
            
            if match_search and match_filter:
                temp_filtered_list.append(member)
        
        self.filtered_members_list = temp_filtered_list
        self.update_table() 
        self.update_status_bar_message(f"تم تطبيق الفلتر. عدد النتائج: {len(self.filtered_members_list)}", is_general_message=True) 
        self._last_filter_applied = True 

    def show_table_context_menu(self, position):
        selected_items = self.table.selectedItems()
        item_at_pos = self.table.itemAt(position) 

        if not item_at_pos and not selected_items: 
            return
        
        row_index_in_table = -1 
        if item_at_pos:
            row_index_in_table = item_at_pos.row()
        elif selected_items:
            row_index_in_table = selected_items[0].row()

        if row_index_in_table < 0: return

        current_list_for_context = self.filtered_members_list if self.is_filter_active else self.members_list
        if row_index_in_table >= len(current_list_for_context): return
            
        member = current_list_for_context[row_index_in_table]
        try:
            original_member_index = self.members_list.index(member)
        except ValueError:
            logger.error(f"العضو {member.nin} من القائمة المفلترة غير موجود في القائمة الرئيسية.")
            self._show_toast(f"خطأ: العضو {self._get_member_display_name_with_index(member, original_member_index)} غير موجود بشكل صحيح.", type="error")
            return

        menu = QMenu(self)
        member_display_name_with_index = self._get_member_display_name_with_index(member, original_member_index)
        
        view_action = QAction(QIcon.fromTheme("document-properties"), f"عرض معلومات {member_display_name_with_index}", self)
        view_action.triggered.connect(lambda: self.view_member_info(original_member_index)) 
        menu.addAction(view_action)

        check_now_action = QAction(QIcon.fromTheme("system-search"), f"فحص الآن لـ {member_display_name_with_index}", self)
        check_now_action.triggered.connect(lambda: self.check_member_now(original_member_index)) 
        menu.addAction(check_now_action)
        
        can_download_any_pdf = bool(member.pre_inscription_id) and \
                               member.status in ["لديه موعد مسبق", "تم الحجز", "مكتمل", "فشل تحميل PDF", "مستفيد حاليًا من المنحة"]
        
        download_all_action = QAction(QIcon.fromTheme("document-save-all", QIcon.fromTheme("document-save")), "تحميل جميع الشهادات", self) 
        download_all_action.setEnabled(can_download_any_pdf)
        download_all_action.triggered.connect(lambda: self.download_all_member_pdfs(original_member_index))
        menu.addAction(download_all_action)

        menu.addSeparator()
        
        edit_action = QAction(QIcon.fromTheme("document-edit"), f"تعديل بيانات {member_display_name_with_index}", self)
        edit_action.triggered.connect(lambda: self.edit_member_details(self.table.item(row_index_in_table, 0))) 
        menu.addAction(edit_action)

        delete_action = QAction(QIcon.fromTheme("edit-delete"), f"حذف {member_display_name_with_index}", self)
        delete_action.triggered.connect(lambda: self.remove_specific_member(original_member_index)) 
        menu.addAction(delete_action)

        menu.exec_(self.table.viewport().mapToGlobal(position))

    def view_member_info(self, original_member_index): 
        if 0 <= original_member_index < len(self.members_list):
            member = self.members_list[original_member_index]
            member_display_name = self._get_member_display_name_with_index(member, original_member_index)
            logger.info(f"طلب عرض معلومات العضو: {member_display_name}")
            self.update_status_bar_message(f"عرض معلومات العضو: {member_display_name}", is_general_message=True) 
            dialog = ViewMemberDialog(member, self) 
            dialog.exec_()
        else:
            logger.warning(f"view_member_info: فهرس خاطئ {original_member_index}")
            self._show_toast("خطأ في عرض معلومات العضو (فهرس غير صالح).", type="error") 

    def check_member_now(self, original_member_index): 
        if 0 <= original_member_index < len(self.members_list):
            member = self.members_list[original_member_index]
            member_display_name = self._get_member_display_name_with_index(member, original_member_index)
            
            if member.is_processing:
                 self._show_toast(f"العضو '{member_display_name}' قيد المعالجة حاليًا. يرجى الانتظار.", type="warning")
                 return

            if self.single_check_thread and self.single_check_thread.isRunning():
                self._show_toast("فحص آخر قيد التنفيذ بالفعل. يرجى الانتظار.", type="warning")
                return

            logger.info(f"طلب فحص فوري للعضو: {member_display_name}")
            self.update_status_bar_message(f"بدء الفحص الفوري للعضو: {member_display_name}...", is_general_message=False) 
            self._show_toast(f"بدء الفحص الفوري للعضو: {member_display_name}", type="info")
            
            self.single_check_thread = SingleMemberCheckThread(member, original_member_index, self.api_client, self.settings.copy())
            self.single_check_thread.update_member_gui_signal.connect(self.update_member_gui_in_table)
            self.single_check_thread.new_data_fetched_signal.connect(self.update_member_name_in_table) 
            self.single_check_thread.member_processing_started_signal.connect(lambda idx: self.handle_member_processing_signal(idx, True))
            self.single_check_thread.member_processing_finished_signal.connect(lambda idx: self.handle_member_processing_signal(idx, False))
            self.single_check_thread.global_log_signal.connect(self.update_status_bar_message) 
            self.single_check_thread.start()
        else:
            logger.warning(f"check_member_now: فهرس خاطئ {original_member_index}")
            self._show_toast("خطأ في بدء الفحص الفوري (فهرس غير صالح).", type="error") 

    def download_all_member_pdfs(self, original_member_index): 
        if not (0 <= original_member_index < len(self.members_list)):
            self._show_toast("فهرس عضو غير صالح لتحميل الشهادات.", type="error")
            return

        member = self.members_list[original_member_index]
        member_display_name = self._get_member_display_name_with_index(member, original_member_index)

        if member.is_processing and self.active_download_all_pdfs_threads.get(original_member_index):
            self._show_toast(f"تحميل شهادات العضو '{member_display_name}' قيد التنفيذ بالفعل.", type="warning")
            return
        
        if self.active_download_all_pdfs_threads.get(original_member_index) and self.active_download_all_pdfs_threads[original_member_index].isRunning():
            self._show_toast(f"تحميل شهادات العضو '{member_display_name}' قيد التنفيذ بالفعل.", type="warning")
            return

        if not member.pre_inscription_id:
            self._show_toast(f"ID التسجيل المسبق مفقود للعضو {member_display_name}. لا يمكن تحميل الشهادات.", type="error")
            return

        logger.info(f"طلب تحميل جميع الشهادات للعضو: {member_display_name}")
        self.update_status_bar_message(f"بدء تحميل جميع الشهادات لـ {member_display_name}...", is_general_message=False) 
        self._show_toast(f"بدء تحميل جميع الشهادات لـ {member_display_name}", type="info")

        all_pdfs_thread = DownloadAllPdfsThread(member, original_member_index, self.api_client)
        all_pdfs_thread.all_pdfs_download_finished_signal.connect(self.handle_all_pdfs_download_finished)
        all_pdfs_thread.individual_pdf_status_signal.connect(self.handle_individual_pdf_status) 
        all_pdfs_thread.member_processing_started_signal.connect(lambda idx: self.handle_member_processing_signal(idx, True))
        all_pdfs_thread.member_processing_finished_signal.connect(lambda idx, ri=original_member_index: self._clear_active_download_thread(ri))
        all_pdfs_thread.global_log_signal.connect(self.update_status_bar_message) 
        
        self.active_download_all_pdfs_threads[original_member_index] = all_pdfs_thread
        all_pdfs_thread.start()

    def _clear_active_download_thread(self, original_member_index): 
        if original_member_index in self.active_download_all_pdfs_threads:
            del self.active_download_all_pdfs_threads[original_member_index]
        self.handle_member_processing_signal(original_member_index, False)
        if 0 <= original_member_index < len(self.members_list):
            member = self.members_list[original_member_index]
            member_display_name = self._get_member_display_name_with_index(member, original_member_index)
            self.update_status_bar_message(f"انتهت معالجة تحميل الشهادات للعضو: {member_display_name}", is_general_message=True)


    def handle_individual_pdf_status(self, original_member_index, pdf_type, file_path_or_status_msg_from_thread, success, error_msg_for_toast_from_thread):
        if not (0 <= original_member_index < len(self.members_list)):
            return
        member = self.members_list[original_member_index]
        
        pdf_type_ar = "التعهد" if pdf_type == "HonneurEngagementReport" else "الموعد"
        member_name_display = self._get_member_display_name_with_index(member, original_member_index)
        
        if success:
            file_path = file_path_or_status_msg_from_thread
            if pdf_type == "HonneurEngagementReport":
                member.pdf_honneur_path = file_path
            elif pdf_type == "RdvReport":
                member.pdf_rdv_path = file_path
            
            activity_detail = f"تم تحميل شهادة {pdf_type_ar} بنجاح إلى {os.path.basename(file_path)}."
            member.set_activity_detail(file_path_or_status_msg_from_thread if os.path.exists(file_path_or_status_msg_from_thread) else activity_detail) 
            toast_msg = f"للعضو {member_name_display}: {activity_detail}\nالمسار: {file_path}" 
            self._show_toast(toast_msg, type="success", duration=5000) 
            self.update_status_bar_message(f"تم تحميل شهادة {pdf_type_ar} للعضو {member_name_display}.", is_general_message=True) 
        else:
            activity_detail = file_path_or_status_msg_from_thread 
            member.set_activity_detail(activity_detail, is_error=True)
            toast_msg = f"للعضو {member_name_display}: فشل تحميل شهادة {pdf_type_ar}. السبب: {error_msg_for_toast_from_thread or activity_detail}" 
            self._show_toast(toast_msg, type="error", duration=6000) 
            self.update_status_bar_message(f"فشل تحميل شهادة {pdf_type_ar} للعضو {member_name_display}.", is_general_message=True) 
        
        self.update_member_gui_in_table(original_member_index, member.status, member.last_activity_detail, get_icon_name_for_status(member.status))
        self.save_members_data() 

    def handle_all_pdfs_download_finished(self, original_member_index, honneur_path, rdv_path, overall_status_msg, all_success, first_error_msg):
        if not (0 <= original_member_index < len(self.members_list)):
            logger.warning(f"handle_all_pdfs_download_finished: فهرس خاطئ {original_member_index}")
            return

        member = self.members_list[original_member_index]
        member_name_display = self._get_member_display_name_with_index(member, original_member_index)
        
        if honneur_path: member.pdf_honneur_path = honneur_path 
        if rdv_path: member.pdf_rdv_path = rdv_path       
        
        if all_success:
            if member.status != "مستفيد حاليًا من المنحة":
                if (member.pdf_honneur_path and member.pdf_rdv_path) or \
                   (member.pdf_honneur_path and not (member.already_has_rdv or member.rdv_id or member.status == "تم الحجز")):
                    member.status = "مكتمل"
                elif member.pdf_honneur_path or member.pdf_rdv_path : 
                     member.status = "تم الحجز" 
            
            member.set_activity_detail(overall_status_msg)
            final_toast_msg = f"للعضو {member_name_display}: {overall_status_msg}" 
            self._show_toast(final_toast_msg, type="success", duration=7000)
            self.update_status_bar_message(f"اكتمل تحميل شهادات العضو {member_name_display}.", is_general_message=True) 

            folder_to_open = None
            if honneur_path: folder_to_open = os.path.dirname(honneur_path)
            elif rdv_path: folder_to_open = os.path.dirname(rdv_path)
            
            if not folder_to_open and member.pre_inscription_id: 
                documents_location = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
                base_app_dir_name = "ملفات_المنحة_البرنامج"
                member_name_for_folder_path = member.get_full_name_ar()
                if not member_name_for_folder_path or member_name_for_folder_path.isspace(): 
                    member_name_for_folder_path = member.nin 
                safe_folder_name_part = "".join(c for c in member_name_for_folder_path if c.isalnum() or c in (' ', '_', '-')).rstrip().replace(" ", "_")
                if not safe_folder_name_part: safe_folder_name_part = member.nin 
                folder_to_open = os.path.join(documents_location, base_app_dir_name, safe_folder_name_part)

            if folder_to_open and os.path.exists(folder_to_open):
                reply = QMessageBox.question(self, 'فتح المجلد', f"تم حفظ الملفات بنجاح في المجلد:\n{folder_to_open}\n\nهل تريد فتح هذا المجلد؟",
                                           QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if reply == QMessageBox.Yes:
                    try:
                        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.realpath(folder_to_open)))
                    except Exception as e_open:
                        logger.error(f"فشل فتح مجلد الملفات: {e_open}")
                        self._show_toast(f"فشل فتح مجلد الملفات: {e_open}", type="warning")
        else:
            if "فشل تحميل PDF" not in member.status and member.status != "مستفيد حاليًا من المنحة": 
                member.status = "فشل تحميل PDF"
            
            final_detail_msg = overall_status_msg
            if first_error_msg and first_error_msg not in final_detail_msg: 
                final_detail_msg += f" (الخطأ الأول: {first_error_msg.split(':')[0]})" 
            member.set_activity_detail(final_detail_msg, is_error=True)
            final_toast_msg = f"للعضو {member_name_display}: فشل تحميل بعض الشهادات.\n{overall_status_msg}" 
            self._show_toast(final_toast_msg, type="error", duration=7000)
            self.update_status_bar_message(f"فشل تحميل بعض شهادات العضو {member_name_display}.", is_general_message=True) 

        self.update_member_gui_in_table(original_member_index, member.status, member.last_activity_detail, get_icon_name_for_status(member.status))
        self.save_members_data() 


    def remove_specific_member(self, original_member_index): 
        if not (0 <= original_member_index < len(self.members_list)):
            self._show_toast("فهرس عضو غير صالح للحذف.", type="error")
            return

        member_to_remove = self.members_list[original_member_index]
        member_display_name = self._get_member_display_name_with_index(member_to_remove, original_member_index)
        confirm_delete = QMessageBox.question(self, "تأكيد الحذف",
                                              f"هل أنت متأكد أنك تريد حذف العضو '{member_display_name}'؟",
                                              QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm_delete == QMessageBox.No:
            return
        
        removed_member_info = self.members_list.pop(original_member_index)
        
        if self.is_filter_active:
            self.apply_filter_and_search() 
        else:
            self.update_table()

        logger.info(f"تم حذف العضو: {member_display_name}")
        self.update_status_bar_message(f"تم حذف العضو: {member_display_name}", is_general_message=True) 
        self._show_toast(f"تم حذف العضو: {member_display_name}", type="info") 
        self.save_members_data() 
        
        if self.monitoring_thread and self.monitoring_thread.current_member_index_to_process >= len(self.members_list):
            self.monitoring_thread.current_member_index_to_process = 0

    def load_app_settings(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    self.settings = json.load(f)
                for key, default_value in DEFAULT_SETTINGS.items():
                    if key not in self.settings:
                        self.settings[key] = default_value
                logger.info(f"تم تحميل الإعدادات من {SETTINGS_FILE}")
            else:
                self.settings = DEFAULT_SETTINGS.copy()
                logger.info("ملف الإعدادات غير موجود، تم استخدام الإعدادات الافتراضية.")
                self.save_app_settings()
        except json.JSONDecodeError:
            logger.error(f"خطأ في قراءة ملف الإعدادات {SETTINGS_FILE}. تم استخدام الإعدادات الافتراضية.")
            self.settings = DEFAULT_SETTINGS.copy()
            self._show_toast(f"خطأ في ملف الإعدادات {SETTINGS_FILE}. تم استعادة الإعدادات الافتراضية.", type="error") 
        except Exception as e:
            logger.exception(f"خطأ غير متوقع عند تحميل الإعدادات: {e}. تم استخدام الإعدادات الافتراضية.")
            self.settings = DEFAULT_SETTINGS.copy()
            self._show_toast(f"خطأ عند تحميل الإعدادات. تم استعادة الإعدادات الافتراضية.", type="error") 

    def save_app_settings(self):
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
            logger.info(f"تم حفظ الإعدادات في {SETTINGS_FILE}")
        except Exception as e:
            logger.exception(f"خطأ عند حفظ الإعدادات: {e}")
            self._show_toast(f"فشل حفظ الإعدادات: {e}", type="error")

    def open_settings_dialog(self):
        dialog = SettingsDialog(self.settings.copy(), self)
        if dialog.exec_() == SettingsDialog.Accepted:
            new_settings = dialog.get_settings()
            self.settings.update(new_settings)
            self.save_app_settings()
            self.apply_app_settings()
            self._show_toast("تم حفظ الإعدادات بنجاح وتطبيقها.", type="success") 
            logger.info("تم تحديث إعدادات التطبيق.")
            self.update_status_bar_message("تم تحديث الإعدادات.", is_general_message=True)

    def apply_app_settings(self):
        self.api_client = AnemAPIClient(
            initial_backoff_general=self.settings.get(SETTING_BACKOFF_GENERAL, DEFAULT_SETTINGS[SETTING_BACKOFF_GENERAL]),
            initial_backoff_429=self.settings.get(SETTING_BACKOFF_429, DEFAULT_SETTINGS[SETTING_BACKOFF_429]),
            request_timeout=self.settings.get(SETTING_REQUEST_TIMEOUT, DEFAULT_SETTINGS[SETTING_REQUEST_TIMEOUT])
        )
        logger.info("تم تحديث AnemAPIClient الرئيسي بالإعدادات الجديدة.")

        if self.monitoring_thread.isRunning():
            logger.info("المراقبة جارية، سيتم تحديث إعدادات خيط المراقبة.")
            self.monitoring_thread.update_thread_settings(self.settings.copy())
            monitoring_interval_minutes = self.settings.get(SETTING_MONITORING_INTERVAL, DEFAULT_SETTINGS[SETTING_MONITORING_INTERVAL])
            self.update_status_bar_message(f"المراقبة جارية (الدورة كل {monitoring_interval_minutes} دقيقة)...", is_general_message=False)
        else:
            self.monitoring_thread.settings = self.settings.copy() 
            self.monitoring_thread._apply_settings() 

        logger.info(f"MonitoringThread settings applied from main app: Interval={self.settings.get(SETTING_MONITORING_INTERVAL)}min, MemberDelay=[{self.settings.get(SETTING_MIN_MEMBER_DELAY)}-{self.settings.get(SETTING_MAX_MEMBER_DELAY)}]s")
        logger.info("تم تطبيق الإعدادات الجديدة على مكونات التطبيق.")

    def _get_member_display_name_with_index(self, member, original_index):
        name_part = member.get_full_name_ar()
        if not name_part or name_part.isspace():
            name_part = member.nin 
        return f"{name_part} (رقم {original_index + 1})"

    def _show_toast(self, message, type="info", duration=4000, member_obj=None, original_idx_if_member=None):
        max_toast_len = 150 
        display_message = message
        
        if member_obj is not None and original_idx_if_member is not None:
            member_display_intro = self._get_member_display_name_with_index(member_obj, original_idx_if_member)
            full_message_with_member = f"{member_display_intro}: {message}"
            if len(full_message_with_member) > max_toast_len:
                remaining_len = max_toast_len - len(member_display_intro) - 5 
                if remaining_len > 10 : 
                     display_message = f"{member_display_intro}: {message[:remaining_len]}..."
                else: 
                     display_message = f"{member_display_intro}..."
                logger.debug(f"Toast message (with member) truncated. Original: {message}")
            else:
                display_message = full_message_with_member
        elif len(message) > max_toast_len:
            display_message = message[:max_toast_len] + "..."
            logger.debug(f"Toast message (general) truncated. Original: {message}")

        toast = ToastNotification(self)
        self.toast_notifications.append(toast)
        toast.showMessage(display_message, type, duration, parent_window=self)
        toast.timer.timeout.connect(lambda t=toast: self._remove_toast_reference(t))

    def _remove_toast_reference(self, toast_instance):
        if toast_instance in self.toast_notifications:
            self.toast_notifications.remove(toast_instance)

    def load_stylesheet(self):
        try:
            with open(STYLESHEET_FILE, "r", encoding="utf-8") as f:
                style = f.read()
                self.setStyleSheet(style)
                logger.info(f"تم تحميل ملف التنسيق بنجاح: {STYLESHEET_FILE}")
        except FileNotFoundError:
            logger.warning(f"ملف التنسيق {STYLESHEET_FILE} غير موجود. سيتم استخدام التنسيق الافتراضي.")
            self._show_toast(f"ملف التنسيق {STYLESHEET_FILE} غير موجود.", type="warning") 
        except Exception as e:
            logger.error(f"خطأ في تحميل ملف التنسيق {STYLESHEET_FILE}: {e}")
            self._show_toast(f"خطأ في تحميل ملف التنسيق: {e}", type="error") 
            
    def update_datetime(self):
        now = QDateTime.currentDateTime()
        arabic_locale = QLocale(QLocale.Arabic, QLocale.Algeria) 
        self.datetime_label.setText(arabic_locale.toString(now, "dddd, dd MMMM yyyy - hh:mm:ss AP")) # تصحيح التنسيق
    
    def toggle_column_visibility(self, checked):
        logger.info(f"تبديل إظهار التفاصيل: {'إظهار' if checked else 'إخفاء'}")
        self.table.setColumnHidden(self.COL_NIN, not checked)
        self.table.setColumnHidden(self.COL_WASSIT, not checked)
        self.table.setColumnHidden(self.COL_CCP, not checked)
        self.table.setColumnHidden(self.COL_PHONE_NUMBER, not checked) 
        self.toggle_details_action.setText("إخفاء التفاصيل" if checked else "إظهار التفاصيل")
        self.update_status_bar_message(f"تم {'إظهار' if checked else 'إخفاء'} الأعمدة التفصيلية.", is_general_message=True) 

    def update_active_row_spinner_display(self):
        if self.active_spinner_row_in_view == -1 or not (0 <= self.active_spinner_row_in_view < self.table.rowCount()):
            return
        
        current_list_displayed = self.filtered_members_list if self.is_filter_active else self.members_list
        
        if self.active_spinner_row_in_view >= len(current_list_displayed):
            self.row_spinner_timer.stop()
            self.active_spinner_row_in_view = -1
            return

        member = current_list_displayed[self.active_spinner_row_in_view]
        try:
            original_member_index = self.members_list.index(member)
        except ValueError: 
            self.row_spinner_timer.stop()
            self.active_spinner_row_in_view = -1
            return

        if not member.is_processing: 
            is_still_pdf_downloading = self.active_download_all_pdfs_threads.get(original_member_index) and \
                                       self.active_download_all_pdfs_threads[original_member_index].isRunning()
            is_still_single_checking = self.single_check_thread and \
                                       self.single_check_thread.isRunning() and \
                                       self.single_check_thread.index == original_member_index
            
            if not is_still_pdf_downloading and not is_still_single_checking:
                self.row_spinner_timer.stop()
                self.active_spinner_row_in_view = -1
            self.update_member_gui_in_table(original_member_index, member.status, member.last_activity_detail, get_icon_name_for_status(member.status))
            return
        
        self.spinner_char_idx = (self.spinner_char_idx + 1) % len(self.spinner_chars)
        char = self.spinner_chars[self.spinner_char_idx]
        
        icon_item_in_table = self.table.item(self.active_spinner_row_in_view, self.COL_ICON)
        if icon_item_in_table:
            icon_item_in_table.setText(char) 
            icon_item_in_table.setIcon(QIcon()) 

    def handle_member_processing_signal(self, original_member_index, is_processing_now):
        logger.debug(f"HMP Signal RECEIVED: original_idx={original_member_index}, is_processing={is_processing_now}")
        if not (0 <= original_member_index < len(self.members_list)):
            logger.warning(f"HMP Signal: فهرس العضو الأصلي غير صالح {original_member_index}")
            return
        
        member = self.members_list[original_member_index]
        member.is_processing = is_processing_now 
        logger.debug(f"HMP Signal: Member {member.nin} is_processing set to {member.is_processing}")

        row_in_table_to_update = -1
        current_list_displayed = self.filtered_members_list if self.is_filter_active else self.members_list
        try:
            row_in_table_to_update = current_list_displayed.index(member)
            logger.debug(f"HMP Signal: Member {member.nin} found at row {row_in_table_to_update} in current_list_displayed.")
        except ValueError:
            logger.debug(f"HMP Signal: العضو {member.nin} ليس في القائمة المعروضة حاليًا. لا يمكن تحديث الصف أو تحديد المؤشر.")
            return 

        if not (0 <= row_in_table_to_update < self.table.rowCount()):
             logger.warning(f"HMP Signal: فهرس الجدول المحسوب {row_in_table_to_update} خارج الحدود لـ {self.table.rowCount()} صفوف.")
             return

        member_display_name = self._get_member_display_name_with_index(member, original_member_index)
        if is_processing_now:
            logger.debug(f"HMP Signal: Processing STARTED for member {member_display_name} at table row {row_in_table_to_update}")
            self.active_spinner_row_in_view = row_in_table_to_update 
            self.spinner_char_idx = 0 
            
            self.table.selectRow(row_in_table_to_update)
            logger.debug(f"HMP Signal: Row {row_in_table_to_update} selected for {member_display_name}")
            first_column_item = self.table.item(row_in_table_to_update, 0)
            if first_column_item:
                self.table.scrollToItem(first_column_item, QAbstractItemView.EnsureVisible)
                logger.debug(f"HMP Signal: Scrolled to row {row_in_table_to_update} for {member_display_name}")
            else:
                logger.warning(f"HMP Signal: No item at ({row_in_table_to_update}, 0) to scroll to for {member_display_name}.")

            icon_item = self.table.item(row_in_table_to_update, self.COL_ICON)
            if icon_item:
                icon_item.setText(self.spinner_chars[self.spinner_char_idx])
                icon_item.setIcon(QIcon()) 
                logger.debug(f"HMP Signal: Initial spinner char set for row {row_in_table_to_update}")

            self.highlight_processing_row(row_in_table_to_update, force_processing_display=True)
            
            if not self.row_spinner_timer.isActive():
                self.row_spinner_timer.start(self.row_spinner_timer_interval)
                logger.debug(f"HMP Signal: Spinner timer started for row {row_in_table_to_update}")
            
            self.update_status_bar_message(f"جاري معالجة العضو: {member_display_name}...", is_general_message=False)

        else: 
            logger.debug(f"HMP Signal: Processing FINISHED for member {member_display_name} at table row {row_in_table_to_update}")
            is_still_pdf_downloading = self.active_download_all_pdfs_threads.get(original_member_index) and \
                                       self.active_download_all_pdfs_threads[original_member_index].isRunning()
            is_still_single_checking = self.single_check_thread and \
                                       self.single_check_thread.isRunning() and \
                                       self.single_check_thread.index == original_member_index
            
            if not is_still_pdf_downloading and not is_still_single_checking:
                if self.active_spinner_row_in_view == row_in_table_to_update: 
                    self.row_spinner_timer.stop()
                    self.active_spinner_row_in_view = -1
                    logger.debug(f"HMP Signal: Spinner timer stopped for row {row_in_table_to_update}")
                    icon_item = self.table.item(row_in_table_to_update, self.COL_ICON)
                    if icon_item: 
                        icon_item.setText("") 
            
            self.highlight_processing_row(row_in_table_to_update, force_processing_display=False)


    def highlight_processing_row(self, row_index_in_table, force_processing_display=None):
        logger.debug(f"Highlight CALLED: row_in_table={row_index_in_table}, force_processing_display={force_processing_display}")
        if not (0 <= row_index_in_table < self.table.rowCount()):
            logger.warning(f"Highlight: فهرس الصف {row_index_in_table} خارج الحدود.")
            return
        
        current_list_displayed = self.filtered_members_list if self.is_filter_active else self.members_list
        if row_index_in_table >= len(current_list_displayed): 
            logger.warning(f"Highlight: فهرس الصف {row_index_in_table} خارج حدود القائمة المعروضة (len={len(current_list_displayed)}).")
            return
            
        member = current_list_displayed[row_index_in_table]
        is_processing_flag = force_processing_display if force_processing_display is not None else member.is_processing
        
        item_for_selection_check = self.table.item(row_index_in_table, 0) 
        is_row_selected_by_user_or_code = False
        if item_for_selection_check:
            is_row_selected_by_user_or_code = item_for_selection_check.isSelected()

        logger.debug(f"Highlight: row={row_index_in_table}, member_nin={member.nin}, effective_is_processing={is_processing_flag}, is_row_selected={is_row_selected_by_user_or_code}")

        default_bg_color = self.table.palette().color(QPalette.Base) 
        alternate_bg_color = QColor(self.table.palette().color(QPalette.AlternateBase)) if self.table.alternatingRowColors() else default_bg_color
        processing_bg_color = QColorConstants.PROCESSING_ROW_DARK_THEME 
        selection_bg_color_from_qss = QColor("#00A2E8") 

        for col in range(self.table.columnCount()):
            item = self.table.item(row_index_in_table, col)
            if item:
                if is_processing_flag:
                    logger.debug(f"Highlight: Applying processing_bg_color to row {row_index_in_table}, col {col}")
                    item.setBackground(processing_bg_color)
                    item.setForeground(Qt.white) 
                elif is_row_selected_by_user_or_code: 
                    logger.debug(f"Highlight: Row {row_index_in_table}, col {col} is selected. Applying QSS selection color.")
                    if item.background() != selection_bg_color_from_qss:
                         item.setBackground(selection_bg_color_from_qss)
                    if item.foreground().color() != Qt.white: 
                         item.setForeground(Qt.white)
                else: 
                    status_text_for_color = member.status
                    specific_color = None
                    if status_text_for_color == "مستفيد حاليًا من المنحة": specific_color = QColorConstants.BENEFITING_GREEN_DARK_THEME
                    elif status_text_for_color == "بيانات الإدخال خاطئة": specific_color = QColorConstants.PINK_DARK_THEME
                    elif status_text_for_color == "لديه موعد مسبق": specific_color = QColorConstants.LIGHT_BLUE_DARK_THEME
                    elif status_text_for_color == "غير مؤهل للحجز": specific_color = QColorConstants.ORANGE_RED_DARK_THEME
                    elif status_text_for_color == "مكتمل": specific_color = QColorConstants.LIGHT_GREEN_DARK_THEME
                    elif "فشل" in status_text_for_color or "غير مؤهل" in status_text_for_color or "خطأ" in status_text_for_color:
                        specific_color = QColorConstants.LIGHT_PINK_DARK_THEME
                    elif "يتطلب تسجيل مسبق" in status_text_for_color: specific_color = QColorConstants.LIGHT_YELLOW_DARK_THEME
                    
                    if specific_color:
                        item.setBackground(specific_color)
                    else:
                        if self.table.alternatingRowColors() and row_index_in_table % 2 != 0 :
                            item.setBackground(alternate_bg_color)
                        else:
                            item.setBackground(default_bg_color)
                    item.setForeground(self.table.palette().color(QPalette.Text))


    def add_member(self):
        dialog = AddMemberDialog(self)
        if dialog.exec_() == AddMemberDialog.Accepted:
            data = dialog.get_data()
            if not (data["nin"] and data["wassit_no"] and data["ccp"]): 
                self._show_toast("يرجى ملء حقول رقم التعريف، رقم الوسيط، والحساب البريدي.", type="warning")
                return
            if len(data["nin"]) != 18:
                self._show_toast("رقم التعريف الوطني يجب أن يتكون من 18 رقمًا.", type="error")
                return
            if len(data["ccp"]) != 12: 
                self._show_toast("رقم الحساب البريدي يجب أن يتكون من 12 رقمًا (10 للحساب + 2 للمفتاح).", type="error")
                return
            for idx, m in enumerate(self.members_list):
                if m.nin == data["nin"] or m.wassit_no == data["wassit_no"]:
                    member_name_display = self._get_member_display_name_with_index(m, idx)
                    msg = f"العضو '{member_name_display}' موجود بالفعل ببيانات مشابهة." 
                    self._show_toast(msg, type="warning")
                    logger.warning(f"محاولة إضافة عضو مكرر: {data['nin']}/{data['wassit_no']} - {msg}")
                    return
            member = Member(data["nin"], data["wassit_no"], data["ccp"], data["phone_number"])
            self.members_list.append(member) 
            
            if self.is_filter_active:
                self.apply_filter_and_search()
            else:
                self.update_table() 

            current_original_index = self.members_list.index(member) 
            member_display_name_add = self._get_member_display_name_with_index(member, current_original_index)
            logger.info(f"تمت إضافة العضو: {member_display_name_add}, Phone={data['phone_number']}")
            self.update_status_bar_message(f"تمت إضافة العضو: {member_display_name_add}. جاري جلب المعلومات الأولية...", is_general_message=False) 
            self._show_toast(f"تمت إضافة العضو: {member_display_name_add}. جاري جلب المعلومات الأولية...", type="info") 
            
            fetch_thread = FetchInitialInfoThread(member, current_original_index, self.api_client, self.settings.copy())
            fetch_thread.update_member_gui_signal.connect(self.update_member_gui_in_table)
            fetch_thread.new_data_fetched_signal.connect(self.update_member_name_in_table)
            fetch_thread.member_processing_started_signal.connect(lambda idx: self.handle_member_processing_signal(idx, True))
            fetch_thread.member_processing_finished_signal.connect(lambda idx: self.handle_member_processing_signal(idx, False))
            self.initial_fetch_threads.append(fetch_thread)
            fetch_thread.start()

    def edit_member_details(self, item): 
        row_in_table = -1
        if not item: 
            selected_rows = self.table.selectionModel().selectedRows()
            if not selected_rows: return
            row_in_table = selected_rows[0].row() 
        else:
            row_in_table = item.row()

        current_list_for_edit = self.filtered_members_list if self.is_filter_active else self.members_list
        if not (0 <= row_in_table < len(current_list_for_edit)): return

        member_to_edit_from_display = current_list_for_edit[row_in_table]
        try:
            original_member_index = self.members_list.index(member_to_edit_from_display)
            member_to_edit = self.members_list[original_member_index] 
        except ValueError:
            member_display_name_err = self._get_member_display_name_with_index(member_to_edit_from_display, -1) 
            logger.error(f"فشل العثور على العضو {member_display_name_err} في القائمة الرئيسية عند التعديل.")
            self._show_toast(f"خطأ: فشل العثور على العضو {member_display_name_err} للتعديل.", type="error") 
            return
        
        member_display_name_edit_title = self._get_member_display_name_with_index(member_to_edit, original_member_index)
        logger.info(f"فتح نافذة تعديل للعضو: {member_display_name_edit_title}")
        dialog = EditMemberDialog(member_to_edit, self) 
        if dialog.exec_() == EditMemberDialog.Accepted:
            new_data = dialog.get_data()
            if not (new_data["nin"] and new_data["wassit_no"] and new_data["ccp"]):
                self._show_toast("يرجى ملء حقول رقم التعريف، رقم الوسيط، والحساب البريدي.", type="warning")
                return
            if len(new_data["nin"]) != 18:
                self._show_toast("رقم التعريف الوطني يجب أن يتكون من 18 رقمًا.", type="error")
                return
            if len(new_data["ccp"]) != 12: 
                self._show_toast("رقم الحساب البريدي يجب أن يتكون من 12 رقمًا (10 للحساب + 2 للمفتاح).", type="error")
                return
                
            nin_changed = member_to_edit.nin != new_data["nin"]
            wassit_changed = member_to_edit.wassit_no != new_data["wassit_no"]
            
            if nin_changed or wassit_changed:
                for idx, m in enumerate(self.members_list):
                    if idx == original_member_index: 
                        continue
                    if m.nin == new_data["nin"] or m.wassit_no == new_data["wassit_no"]:
                        conflicting_member_display = self._get_member_display_name_with_index(m, idx)
                        self._show_toast(f"البيانات الجديدة (NIN أو رقم الوسيط) تتعارض مع العضو '{conflicting_member_display}'. لم يتم الحفظ.", type="error") 
                        logger.warning(f"فشل تعديل العضو {member_display_name_edit_title} بسبب تكرار مع {conflicting_member_display}")
                        return
                
            logger.info(f"حفظ التعديلات للعضو: {member_display_name_edit_title} -> NIN={new_data['nin']}, Phone: {new_data['phone_number']}")
            member_to_edit.nin = new_data["nin"]
            member_to_edit.wassit_no = new_data["wassit_no"]
            member_to_edit.ccp = new_data["ccp"]
            member_to_edit.phone_number = new_data["phone_number"] 

            member_display_after_edit = self._get_member_display_name_with_index(member_to_edit, original_member_index) 

            if nin_changed or wassit_changed:
                logger.info(f"تم تغيير المعرفات الرئيسية للعضو {member_display_after_edit}. إعادة تعيين الحالة وجلب المعلومات.")
                member_to_edit.status = "جديد" 
                member_to_edit.set_activity_detail("تم تعديل المعرفات، يتطلب إعادة التحقق.")
                member_to_edit.nom_fr = ""
                member_to_edit.prenom_fr = ""
                member_to_edit.nom_ar = ""
                member_to_edit.prenom_ar = ""
                member_to_edit.pre_inscription_id = None
                member_to_edit.demandeur_id = None
                member_to_edit.structure_id = None
                member_to_edit.rdv_date = None
                member_to_edit.rdv_id = None
                member_to_edit.rdv_source = None 
                member_to_edit.pdf_honneur_path = None
                member_to_edit.pdf_rdv_path = None
                member_to_edit.has_actual_pre_inscription = False
                member_to_edit.already_has_rdv = False
                member_to_edit.consecutive_failures = 0
                member_to_edit.is_processing = False 
                member_to_edit.have_allocation = False 
                member_to_edit.allocation_details = {}
                
                if self.is_filter_active: self.apply_filter_and_search()
                else: self.update_table_row(original_member_index, member_to_edit) 
                
                self.update_status_bar_message(f"تم تعديل بيانات العضو {member_display_after_edit}. جاري إعادة جلب المعلومات...", is_general_message=False) 
                self._show_toast(f"تم تعديل بيانات العضو {member_display_after_edit}. جاري إعادة جلب المعلومات...", type="info") 
                
                fetch_thread = FetchInitialInfoThread(member_to_edit, original_member_index, self.api_client, self.settings.copy())
                fetch_thread.update_member_gui_signal.connect(self.update_member_gui_in_table)
                fetch_thread.new_data_fetched_signal.connect(self.update_member_name_in_table)
                fetch_thread.member_processing_started_signal.connect(lambda idx: self.handle_member_processing_signal(idx, True))
                fetch_thread.member_processing_finished_signal.connect(lambda idx: self.handle_member_processing_signal(idx, False))
                self.initial_fetch_threads.append(fetch_thread)
                fetch_thread.start()
            else:
                if self.is_filter_active: self.apply_filter_and_search()
                else: self.update_table_row(original_member_index, member_to_edit) 
                self.update_status_bar_message(f"تم تعديل بيانات العضو: {member_display_after_edit}", is_general_message=True) 
                self._show_toast(f"تم تعديل بيانات العضو: {member_display_after_edit}", type="success") 
            
            self.save_members_data()


    def remove_member(self): 
        selected_rows_in_table = self.table.selectionModel().selectedRows()
        if not selected_rows_in_table:
            self._show_toast("يرجى تحديد عضو واحد على الأقل لحذفه.", type="warning") 
            return
        
        confirm_msg = f"هل أنت متأكد أنك تريد حذف {len(selected_rows_in_table)} عضو/أعضاء محددين؟"
        if len(selected_rows_in_table) == 1:
            row_in_table = selected_rows_in_table[0].row()
            current_list_for_display = self.filtered_members_list if self.is_filter_active else self.members_list
            if 0 <= row_in_table < len(current_list_for_display):
                member_to_remove_display_obj = current_list_for_display[row_in_table]
                original_idx_for_display_remove = -1
                try:
                    original_idx_for_display_remove = self.members_list.index(member_to_remove_display_obj)
                except ValueError:
                    pass 
                member_to_remove_display_name = self._get_member_display_name_with_index(member_to_remove_display_obj, original_idx_for_display_remove)
                confirm_msg = f"هل أنت متأكد أنك تريد حذف العضو '{member_to_remove_display_name}'؟"

        confirm_delete = QMessageBox.question(self, "تأكيد الحذف", confirm_msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm_delete == QMessageBox.No:
            return
        
        members_to_delete_from_display = []
        for index_obj in selected_rows_in_table:
            row_in_table = index_obj.row()
            current_list_for_display = self.filtered_members_list if self.is_filter_active else self.members_list
            if 0 <= row_in_table < len(current_list_for_display):
                members_to_delete_from_display.append(current_list_for_display[row_in_table])

        deleted_count = 0 
        for member_to_delete in members_to_delete_from_display:
            if member_to_delete in self.members_list:
                original_idx_before_delete = self.members_list.index(member_to_delete) 
                deleted_member_display_name = self._get_member_display_name_with_index(member_to_delete, original_idx_before_delete)
                self.members_list.remove(member_to_delete)
                logger.info(f"تم حذف العضو: {deleted_member_display_name}")
                deleted_count +=1
            else:
                logger.warning(f"محاولة حذف عضو {member_to_delete.nin} غير موجود في القائمة الرئيسية.")

        if self.is_filter_active:
            self.apply_filter_and_search()
        else:
            self.update_table()
        
        if deleted_count > 0: 
            self.update_status_bar_message(f"تم حذف {deleted_count} عضو/أعضاء.", is_general_message=True)
            self._show_toast(f"تم حذف {deleted_count} عضو/أعضاء بنجاح.", type="info")
        
        self.save_members_data() 
        if self.monitoring_thread and self.monitoring_thread.current_member_index_to_process >= len(self.members_list):
            self.monitoring_thread.current_member_index_to_process = 0


    def update_table(self):
        self.table.setRowCount(0) 
        
        list_to_display = self.filtered_members_list if self.is_filter_active else self.members_list
        
        for row_idx, member_obj in enumerate(list_to_display):
            self.table.insertRow(row_idx)
            self.update_table_row(row_idx, member_obj) 
        
        if not self.is_filter_active: 
            self.save_members_data() 

    def update_table_row(self, row_in_table, member): 
        item_icon = QTableWidgetItem()
        item_icon.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row_in_table, self.COL_ICON, item_icon) 

        item_full_name_ar = QTableWidgetItem(member.get_full_name_ar())
        item_full_name_ar.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row_in_table, self.COL_FULL_NAME_AR, item_full_name_ar)

        item_nin = QTableWidgetItem(member.nin)
        item_nin.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row_in_table, self.COL_NIN, item_nin)

        item_wassit = QTableWidgetItem(member.wassit_no)
        item_wassit.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row_in_table, self.COL_WASSIT, item_wassit)

        ccp_display = member.ccp
        if len(member.ccp) == 12: 
             ccp_display = f"{member.ccp[:10]} {member.ccp[10:]}"
        item_ccp = QTableWidgetItem(ccp_display)
        item_ccp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row_in_table, self.COL_CCP, item_ccp)

        item_phone = QTableWidgetItem(member.phone_number or "") 
        item_phone.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row_in_table, self.COL_PHONE_NUMBER, item_phone)

        item_status = QTableWidgetItem() 
        item_status.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row_in_table, self.COL_STATUS, item_status) 

        rdv_date_display_text = member.rdv_date if member.rdv_date else ""
        if member.rdv_date:
            if member.rdv_source == "system":
                rdv_date_display_text += " (نظام)"
            elif member.rdv_source == "discovered":
                rdv_date_display_text += " (مكتشف)"
        item_rdv = QTableWidgetItem(rdv_date_display_text)
        item_rdv.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        self.table.setItem(row_in_table, self.COL_RDV_DATE, item_rdv)
        
        detail_to_show = member.last_activity_detail 
        item_details = QTableWidgetItem(detail_to_show)
        item_details.setToolTip(member.full_last_activity_detail) 
        item_details.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row_in_table, self.COL_DETAILS, item_details)

        try:
            original_member_index = self.members_list.index(member)
            self.update_member_gui_in_table(original_member_index, member.status, member.last_activity_detail, get_icon_name_for_status(member.status))
        except ValueError:
            logger.error(f"خطأ: العضو {member.nin} غير موجود في القائمة الرئيسية عند تحديث الصف.")
            status_item = self.table.item(row_in_table, self.COL_STATUS)
            if status_item: status_item.setText(member.status)
            icon_item = self.table.item(row_in_table, self.COL_ICON)
            if icon_item:
                qt_icon = self.style().standardIcon(getattr(QStyle, get_icon_name_for_status(member.status), QStyle.SP_CustomBase))
                icon_item.setIcon(qt_icon)
                icon_item.setText("")
        
    def update_member_gui_in_table(self, original_member_index, status_text, detail_text, icon_name_str):
        if not (0 <= original_member_index < len(self.members_list)):
            logger.warning(f"update_member_gui_in_table: فهرس أصلي غير صالح {original_member_index}")
            return
        
        member = self.members_list[original_member_index]
        
        row_in_table_to_update = -1
        current_list_displayed = self.filtered_members_list if self.is_filter_active else self.members_list
        try:
            row_in_table_to_update = current_list_displayed.index(member)
        except ValueError:
            logger.debug(f"العضو {self._get_member_display_name_with_index(member, original_member_index)} ليس في القائمة المعروضة حاليًا، لا يتم تحديث واجهة المستخدم للجدول مباشرة.")
            return

        if not (0 <= row_in_table_to_update < self.table.rowCount()):
             logger.warning(f"update_member_gui_in_table: فهرس الجدول المحسوب غير صالح {row_in_table_to_update}")
             return

        self.table.item(row_in_table_to_update, self.COL_FULL_NAME_AR).setText(member.get_full_name_ar())
        self.table.item(row_in_table_to_update, self.COL_NIN).setText(member.nin)
        self.table.item(row_in_table_to_update, self.COL_WASSIT).setText(member.wassit_no)
        ccp_display = member.ccp
        if len(member.ccp) == 12: ccp_display = f"{member.ccp[:10]} {member.ccp[10:]}"
        self.table.item(row_in_table_to_update, self.COL_CCP).setText(ccp_display)
        self.table.item(row_in_table_to_update, self.COL_PHONE_NUMBER).setText(member.phone_number or "") 
        
        rdv_date_display_text = member.rdv_date if member.rdv_date else ""
        if member.rdv_date:
            if member.rdv_source == "system":
                rdv_date_display_text += " (نظام)"
            elif member.rdv_source == "discovered":
                rdv_date_display_text += " (مكتشف)"
        self.table.item(row_in_table_to_update, self.COL_RDV_DATE).setText(rdv_date_display_text)


        detail_to_show_gui = member.last_activity_detail 
        self.table.item(row_in_table_to_update, self.COL_DETAILS).setText(detail_to_show_gui)
        self.table.item(row_in_table_to_update, self.COL_DETAILS).setToolTip(member.full_last_activity_detail) 

        icon_item = self.table.item(row_in_table_to_update, self.COL_ICON)
        status_text_item = self.table.item(row_in_table_to_update, self.COL_STATUS)
        status_text_item.setText(status_text) 

        if icon_item:
            if self.active_spinner_row_in_view == row_in_table_to_update and member.is_processing:
                icon_item.setIcon(QIcon()) 
            else:
                qt_icon = self.style().standardIcon(getattr(QStyle, icon_name_str, QStyle.SP_CustomBase))
                icon_item.setIcon(qt_icon)
                icon_item.setText("") 
        
        self.highlight_processing_row(row_in_table_to_update, force_processing_display=None) 

        msg_attr_prefix = f"_toast_shown_{original_member_index}_" 
        if not self.suppress_initial_messages: 
            member_display_for_toast = self._get_member_display_name_with_index(member, original_member_index)
            current_status_for_toast = status_text 
            
            if "فشل" in current_status_for_toast or "خطأ" in current_status_for_toast or "غير مؤهل" in current_status_for_toast:
                error_attr = msg_attr_prefix + current_status_for_toast.replace(" ", "_") 
                if not hasattr(self, error_attr) or not getattr(self, error_attr):
                    self._show_toast(f"{member.full_last_activity_detail}", type="error", duration=5000, member_obj=member, original_idx_if_member=original_member_index)
                    setattr(self, error_attr, True)
                    for attr_suffix in ["input_error", "has_rdv", "booking_ineligible", "completed_or_benefiting", "success_generic"]:
                        if hasattr(self, msg_attr_prefix + attr_suffix):
                            delattr(self, msg_attr_prefix + attr_suffix)
            elif current_status_for_toast == "مكتمل" or current_status_for_toast == "مستفيد حاليًا من المنحة" or current_status_for_toast == "تم الحجز":
                success_attr = msg_attr_prefix + "success_generic"
                if not hasattr(self, success_attr) or not getattr(self, success_attr):
                    self._show_toast(f"{detail_text}", type="success", duration=5000, member_obj=member, original_idx_if_member=original_member_index)
                    setattr(self, success_attr, True)
                    for attr_suffix in ["input_error", "has_rdv", "booking_ineligible", "error_generic"]:
                         if hasattr(self, msg_attr_prefix + attr_suffix):
                            delattr(self, msg_attr_prefix + attr_suffix)
            else: 
                for attr_suffix in ["input_error", "has_rdv", "booking_ineligible", "completed_or_benefiting", "success_generic", "error_generic"] + [current_status_for_toast.replace(" ", "_")]:
                    if hasattr(self, msg_attr_prefix + attr_suffix):
                        delattr(self, msg_attr_prefix + attr_suffix)
        
    def update_member_name_in_table(self, original_member_index, nom_ar, prenom_ar): 
        if 0 <= original_member_index < len(self.members_list):
            member = self.members_list[original_member_index]
            member.nom_ar = nom_ar
            member.prenom_ar = prenom_ar
            member_display_name = self._get_member_display_name_with_index(member, original_member_index)
            logger.info(f"تحديث اسم ولقب العضو (عربي) {member_display_name}")
            
            row_in_table_to_update = -1
            current_list_displayed = self.filtered_members_list if self.is_filter_active else self.members_list
            try:
                row_in_table_to_update = current_list_displayed.index(member)
                if 0 <= row_in_table_to_update < self.table.rowCount():
                    full_name_item = self.table.item(row_in_table_to_update, self.COL_FULL_NAME_AR)
                    if full_name_item: 
                        full_name_item.setText(member.get_full_name_ar())
                    if not self.suppress_initial_messages:
                        self._show_toast(f"تم تحديث اسم العضو.", type="info", member_obj=member, original_idx_if_member=original_member_index)
            except ValueError:
                logger.debug(f"العضو {member_display_name} ليس في القائمة المعروضة حاليًا، لا يتم تحديث الاسم في الجدول مباشرة.")

            self.save_members_data() 

    def update_status_bar_message(self, message, is_general_message=True, member_obj=None, original_idx_if_member=None):
        final_message = message
        if member_obj and original_idx_if_member is not None and original_idx_if_member >= 0: 
            member_display = self._get_member_display_name_with_index(member_obj, original_idx_if_member)
            final_message = f"{member_display}: {message}"
        
        logger.info(f"رسالة شريط الحالة: {final_message}")
        
        if hasattr(self, 'status_bar_label'):
            self.status_bar_label.setText(final_message)
        
        if hasattr(self, 'last_scan_label'): 
            if not is_general_message or "انتهاء دورة الفحص" in message or "بدء دورة فحص جديدة" in message or "استئناف المراقبة" in message or "الموقع لا يزال غير متاح" in message or "اكتمل الفحص الأولي" in message:
                self.last_scan_label.setText(f"آخر تحديث: {time.strftime('%H:%M:%S')}")
            elif is_general_message: 
                self.last_scan_label.setText("")
        
        if hasattr(self, 'countdown_label'): 
            if is_general_message and hasattr(self, 'last_scan_label') and self.last_scan_label.text() == "": 
                 self.countdown_label.setText("")


    def update_countdown_timer_display(self, time_remaining_str):
        if hasattr(self, 'countdown_label'): 
            self.countdown_label.setText(time_remaining_str)


    def start_monitoring(self):
        if not self.members_list:
            self._show_toast("يرجى إضافة أعضاء أولاً لبدء المراقبة.", type="warning") 
            return
        if not self.monitoring_thread.isRunning():
            logger.info("بدء المراقبة...")
            self.monitoring_thread.members_list_ref = self.members_list 
            self.monitoring_thread.is_running = True
            self.monitoring_thread.is_connection_lost_mode = False 
            self.monitoring_thread.current_member_index_to_process = 0 
            self.monitoring_thread.consecutive_network_error_trigger_count = 0 
            self.monitoring_thread.update_thread_settings(self.settings.copy()) 
            self.monitoring_thread.start()
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.add_member_button.setEnabled(False) 
            self.remove_member_button.setEnabled(False)
            monitoring_interval_minutes = self.settings.get(SETTING_MONITORING_INTERVAL, DEFAULT_SETTINGS[SETTING_MONITORING_INTERVAL])
            self.update_status_bar_message(f"بدأت المراقبة (الدورة كل {monitoring_interval_minutes} دقيقة)...", is_general_message=False) 
            self._show_toast(f"بدأت المراقبة (الدورة كل {monitoring_interval_minutes} دقيقة).", type="info")
        else:
            logger.info("المراقبة جارية بالفعل.")
            self._show_toast("المراقبة جارية بالفعل.", type="info") 
            self.update_status_bar_message("المراقبة جارية بالفعل.", is_general_message=True)

    def stop_monitoring(self):
        if self.monitoring_thread.isRunning():
            logger.info("تم طلب إيقاف المراقبة.")
            self.monitoring_thread.stop_monitoring() 
            if self.row_spinner_timer.isActive():
                self.row_spinner_timer.stop()
                if self.active_spinner_row_in_view != -1 and self.active_spinner_row_in_view < self.table.rowCount(): 
                    current_list_displayed = self.filtered_members_list if self.is_filter_active else self.members_list
                    if self.active_spinner_row_in_view < len(current_list_displayed):
                        member_at_spinner = current_list_displayed[self.active_spinner_row_in_view]
                        try:
                            original_member_index = self.members_list.index(member_at_spinner)
                            if 0 <= original_member_index < len(self.members_list):
                                member = self.members_list[original_member_index]
                                member.is_processing = False 
                                self.update_member_gui_in_table(original_member_index, member.status, member.last_activity_detail, get_icon_name_for_status(member.status))
                        except ValueError:
                             logger.warning(f"StopMonitoring: لم يتم العثور على العضو في active_spinner_row_in_view ({self.active_spinner_row_in_view}) في القائمة الرئيسية.")
                    else:
                        logger.warning(f"StopMonitoring: active_spinner_row_in_view ({self.active_spinner_row_in_view}) خارج حدود current_list_displayed.")
                self.active_spinner_row_in_view = -1

            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.add_member_button.setEnabled(True)
            self.remove_member_button.setEnabled(True)
            self.update_status_bar_message("تم إيقاف المراقبة بنجاح.", is_general_message=True) 
            self._show_toast("تم إيقاف المراقبة.", type="info")
            self.update_countdown_timer_display("") 
            for i in range(len(self.members_list)):
                if self.members_list[i].is_processing: 
                    self.members_list[i].is_processing = False
                    self.update_member_gui_in_table(i, self.members_list[i].status, self.members_list[i].last_activity_detail, get_icon_name_for_status(self.members_list[i].status))
        else:
            logger.info("المراقبة ليست جارية.")
            self._show_toast("المراقبة ليست جارية حاليًا.", type="info") 
            self.update_status_bar_message("المراقبة ليست جارية.", is_general_message=True)

    def load_members_data(self):
        self.suppress_initial_messages = True 
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data_list = json.load(f)
                    self.members_list = [Member.from_dict(data) for data in data_list]
                    for member in self.members_list:
                        member.is_processing = False
                self.filtered_members_list = list(self.members_list) 
                self.update_table() 
                logger.info(f"تم تحميل بيانات {len(self.members_list)} أعضاء من {DATA_FILE}")
                self.update_status_bar_message(f"تم تحميل بيانات {len(self.members_list)} أعضاء من {DATA_FILE}", is_general_message=True)
            else:
                self.members_list = []
                self.filtered_members_list = []
                self.update_table() 
                logger.info(f"ملف البيانات {DATA_FILE} غير موجود، سيبدأ البرنامج بقائمة فارغة.")
                self.update_status_bar_message(f"ملف البيانات {DATA_FILE} غير موجود. يمكنك إضافة أعضاء جدد.", is_general_message=True) 
        except json.JSONDecodeError:
            logger.error(f"خطأ في قراءة ملف البيانات {DATA_FILE}. قد يكون الملف تالفًا.")
            self.update_status_bar_message(f"خطأ في قراءة ملف البيانات {DATA_FILE}. يرجى التحقق من الملف.", is_general_message=True) 
            self._show_toast(f"خطأ في ملف البيانات {DATA_FILE}. قد يكون الملف تالفًا. تم بدء البرنامج بقائمة فارغة.", type="error", duration=6000) 
            self.members_list = []
            self.filtered_members_list = []
            self.update_table()
        except Exception as e:
            logger.exception(f"خطأ غير متوقع عند تحميل البيانات: {e}")
            self.update_status_bar_message(f"خطأ غير متوقع عند تحميل البيانات: {e}", is_general_message=True)
            self._show_toast(f"خطأ غير متوقع عند تحميل البيانات: {e}", type="error", duration=6000) 
            self.members_list = []
            self.filtered_members_list = []
            self.update_table()
        finally:
            QTimer.singleShot(200, lambda: setattr(self, 'suppress_initial_messages', False)) 

    def save_members_data(self):
        try:
            data_to_save = []
            for member in self.members_list: 
                member_dict = member.to_dict()
                member_dict['is_processing'] = False 
                data_to_save.append(member_dict)
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=4)
            logger.debug(f"تم حفظ بيانات الأعضاء في {DATA_FILE}") 
        except Exception as e:
            logger.exception(f"خطأ عند حفظ البيانات: {e}")
            self.update_status_bar_message(f"خطأ عند حفظ البيانات: {e}", is_general_message=True)
            self._show_toast(f"فشل حفظ بيانات الأعضاء: {e}", type="error") 

    def closeEvent(self, event):
        logger.info("إغلاق التطبيق...")
        self.update_status_bar_message("جاري إغلاق التطبيق...", is_general_message=True) 
        if self.monitoring_thread.isRunning():
            logger.info("إيقاف المراقبة قبل الإغلاق...")
            self.monitoring_thread.stop_monitoring() 
            if not self.monitoring_thread.wait(3000): 
                logger.warning("خيط المراقبة لم ينتهِ في الوقت المناسب.")
        
        self.save_members_data() 
        self.save_app_settings() 
        
        logger.info("انتظار إنهاء خيوط الجلب الأولي...")
        for thread in self.initial_fetch_threads:
            if thread.isRunning():
                thread.quit() 
                if not thread.wait(2000): 
                    logger.warning(f"الخيط {thread} لم ينتهِ في الوقت المناسب عند الإغلاق.")
        
        if self.single_check_thread and self.single_check_thread.isRunning():
            logger.info("إيقاف خيط الفحص الفردي قبل الإغلاق...")
            self.single_check_thread.quit() 
            if not self.single_check_thread.wait(1000): 
                 logger.warning("خيط الفحص الفردي لم ينته في الوقت المناسب.")
        
        active_pdf_dl_threads_copy = list(self.active_download_all_pdfs_threads.values())
        if active_pdf_dl_threads_copy:
            logger.info(f"إيقاف {len(active_pdf_dl_threads_copy)} خيوط تحميل PDF نشطة...")
            for pdf_thread in active_pdf_dl_threads_copy:
                if pdf_thread.isRunning():
                    pdf_thread.stop() 
                    if not pdf_thread.wait(2000): 
                        logger.warning(f"خيط تحميل جميع ملفات PDF {pdf_thread} لم ينتهِ في الوقت المناسب.")
            self.active_download_all_pdfs_threads.clear()


        if hasattr(self, 'datetime_timer') and self.datetime_timer.isActive(): self.datetime_timer.stop() # التحقق قبل الإيقاف
        if hasattr(self, 'row_spinner_timer') and self.row_spinner_timer.isActive(): self.row_spinner_timer.stop()  # التحقق قبل الإيقاف
        logger.info("تم إغلاق التطبيق.")
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = AnemApp()
    if not hasattr(main_window, '_should_initialize_ui') or not main_window._should_initialize_ui:
        logger.critical("__main__: لم يتم تحديد _should_initialize_ui أو قيمته False. الخروج من التطبيق.")
        if hasattr(main_window, 'activation_successful') and not main_window.activation_successful:
             if hasattr(main_window, 'firebase_service') and not main_window.firebase_service.is_initialized():
                 QMessageBox.critical(None, "خطأ فادح في Firebase",
                                     f"لا يمكن تهيئة خدمة Firebase. الرجاء التأكد من وجود ملف '{FIREBASE_SERVICE_ACCOUNT_KEY_FILE}' وأنه صالح.\nسيتم إغلاق البرنامج.",
                                     QMessageBox.Ok)
             elif not (hasattr(main_window, 'firebase_service') and main_window.firebase_service.is_initialized()):
                 QMessageBox.critical(None, "خطأ فادح", "حدث خطأ غير متوقع أثناء تهيئة خدمات البرنامج.\nسيتم إغلاق البرنامج.", QMessageBox.Ok)
        sys.exit(1) 
    
    logger.info("__main__: نجح التفعيل. جاري إظهار النافذة الرئيسية.")
    main_window.show()
    sys.exit(app.exec_())

