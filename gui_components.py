# gui_components.py
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QDialog, QFormLayout, QDialogButtonBox,
    QSpinBox, QStyle, QApplication, QDesktopWidget, QTextEdit,
    QScrollArea, QFrame,QSizePolicy # تمت إضافة QFrame و QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QPoint, QEasingCurve, QPropertyAnimation, QRegularExpression
from PyQt5.QtGui import QIcon, QRegularExpressionValidator, QColor, QPixmap, QFont # تمت إضافة QPixmap و QFont

from utils import QColorConstants


class ToastNotification(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.ToolTip | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0) 

        self.background_widget = QWidget(self)
        self.background_widget.setObjectName("toastBackground") 

        toast_layout = QHBoxLayout(self.background_widget)
        toast_layout.setContentsMargins(10, 8, 10, 8) 
        toast_layout.setSpacing(8)

        self.icon_label = QLabel(self.background_widget)
        self.icon_label.setObjectName("toastIconLabel") 
        toast_layout.addWidget(self.icon_label)

        self.message_label = QLabel(self.background_widget)
        self.message_label.setObjectName("toastMessageLabel") 
        self.message_label.setWordWrap(True)
        toast_layout.addWidget(self.message_label)

        self.layout.addWidget(self.background_widget) 

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._start_fade_out)

        self.animation = QPropertyAnimation(self, b"windowOpacity", self)
        self.animation.setDuration(500) 
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.animation.finished.connect(self._on_animation_finished)

    def _on_animation_finished(self):
        if self.windowOpacity() == 0: 
            self.hide()

    def _start_fade_out(self):
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.start()

    def showMessage(self, message, type="info", duration=4000, parent_window=None):
        self.message_label.setText(message)
        self.setWindowOpacity(0.0) 

        self.background_widget.setProperty("toastType", type)
        self.message_label.setProperty("toastType", type) 
        self.icon_label.setProperty("toastType", type)   

        self.style().unpolish(self.background_widget)
        self.style().polish(self.background_widget)
        self.style().unpolish(self.message_label)
        self.style().polish(self.message_label)
        self.style().unpolish(self.icon_label)
        self.style().polish(self.icon_label)
        
        icon = QIcon() 
        if type == "error":
            icon = self.style().standardIcon(QStyle.SP_MessageBoxCritical)
        elif type == "warning":
            icon = self.style().standardIcon(QStyle.SP_MessageBoxWarning)
        elif type == "success":
            icon = self.style().standardIcon(QStyle.SP_DialogApplyButton) 
        else: 
            icon = self.style().standardIcon(QStyle.SP_MessageBoxInformation)
        
        self.icon_label.setPixmap(icon.pixmap(24, 24)) 

        self.adjustSize() 

        if parent_window:
            parent_geo = parent_window.geometry()
            screen_geo = QApplication.desktop().availableGeometry(parent_window)

            pos_x = parent_geo.left() + 15
            pos_y = parent_geo.bottom() - self.height() - 15
            
            if pos_x + self.width() > screen_geo.right() - 10:
                 pos_x = screen_geo.right() - self.width() - 10
            
            if pos_y + self.height() > screen_geo.bottom() - 40 or \
               parent_window.isMinimized() or parent_geo.width() < 200 or parent_geo.height() < 100:
                
                pos_x = screen_geo.left() + 20
                if pos_x + self.width() > screen_geo.right() - 20 : 
                     pos_x = screen_geo.right() - self.width() - 20
                pos_y = screen_geo.bottom() - self.height() - 50 
            
            self.move(QPoint(int(pos_x), int(pos_y))) 
        else:
            screen_geo = QApplication.desktop().availableGeometry()
            self.move(screen_geo.width() - self.width() - 20, screen_geo.height() - self.height() - 50)

        self.show()
        self.animation.setStartValue(0.0) 
        self.animation.setEndValue(1.0)   
        self.animation.start() 
        self.timer.start(duration)


class AddMemberDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة عضو جديد")
        self.setModal(True)
        self.setLayoutDirection(Qt.RightToLeft) 
        layout = QFormLayout(self)
        layout.setLabelAlignment(Qt.AlignRight) 

        self.nin_input = QLineEdit(self)
        self.nin_input.setMaxLength(18) 
        self.nin_input.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9]{1,18}")))

        self.wassit_no_input = QLineEdit(self) 
        self.ccp_input = QLineEdit(self)
        self.ccp_input.setMaxLength(13) 
        self.ccp_input.textChanged.connect(self.format_ccp_input) 

        self.phone_number_input = QLineEdit(self) 
        self.phone_number_input.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[0-9\s\+\-\(\)]{0,20}$")))
        self.phone_number_input.setMaxLength(20)


        layout.addRow("رقم التعريف الوطني (NIN):", self.nin_input)
        layout.addRow("رقم طالب الشغل (الوسيط):", self.wassit_no_input)
        layout.addRow("رقم الحساب البريدي (CCP):", self.ccp_input)
        layout.addRow("رقم الهاتف:", self.phone_number_input) 

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self)
        self.buttons.button(QDialogButtonBox.Ok).setText("إضافة")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def format_ccp_input(self, text):
        cleaned_text = ''.join(filter(str.isdigit, text))
        if len(cleaned_text) > 12:
            cleaned_text = cleaned_text[:12]
        if len(cleaned_text) > 10:
            formatted_text = f"{cleaned_text[:10]} {cleaned_text[10:]}"
        else:
            formatted_text = cleaned_text
        self.ccp_input.blockSignals(True)
        self.ccp_input.setText(formatted_text)
        self.ccp_input.setCursorPosition(len(formatted_text)) 
        self.ccp_input.blockSignals(False)

    def get_data(self):
        ccp_raw = self.ccp_input.text().replace(" ", "") 
        return {
            "nin": self.nin_input.text().strip(),
            "wassit_no": self.wassit_no_input.text().strip(),
            "ccp": ccp_raw, 
            "phone_number": self.phone_number_input.text().strip() 
        }

class EditMemberDialog(QDialog):
    def __init__(self, member, parent=None): 
        super().__init__(parent)
        self.member = member 
        self.setWindowTitle(f"تعديل بيانات العضو: {member.get_full_name_ar() or member.nin}".strip()) 
        self.setModal(True)
        self.setMinimumWidth(450) 
        self.setLayoutDirection(Qt.RightToLeft)

        layout = QFormLayout(self)
        layout.setLabelAlignment(Qt.AlignRight)

        self.full_name_label = QLabel(f"<b>الاسم الكامل:</b> {member.get_full_name_ar() or '(غير متوفر بعد)'}", self)
        layout.addRow(self.full_name_label)

        self.nin_input = QLineEdit(member.nin, self)
        self.nin_input.setMaxLength(18)
        self.nin_input.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9]{1,18}")))

        self.wassit_no_input = QLineEdit(member.wassit_no, self)
        self.ccp_input = QLineEdit(self) 
        self.ccp_input.setMaxLength(13)
        self.ccp_input.textChanged.connect(self.format_ccp_input_edit)
        self.format_ccp_input_edit(member.ccp) 

        self.phone_number_input = QLineEdit(member.phone_number, self) 
        self.phone_number_input.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[0-9\s\+\-\(\)]{0,20}$")))
        self.phone_number_input.setMaxLength(20)

        layout.addRow("رقم التعريف الوطني (NIN):", self.nin_input)
        layout.addRow("رقم طالب الشغل (الوسيط):", self.wassit_no_input)
        layout.addRow("رقم الحساب البريدي (CCP):", self.ccp_input)
        layout.addRow("رقم الهاتف:", self.phone_number_input) 

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, Qt.Horizontal, self)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def format_ccp_input_edit(self, text):
        cleaned_text = ''.join(filter(str.isdigit, text))
        if len(cleaned_text) > 12:
            cleaned_text = cleaned_text[:12]
        if len(cleaned_text) > 10:
            formatted_text = f"{cleaned_text[:10]} {cleaned_text[10:]}"
        else:
            formatted_text = cleaned_text
        
        current_cursor_pos = self.ccp_input.cursorPosition()
        self.ccp_input.blockSignals(True)
        self.ccp_input.setText(formatted_text)
        if len(text) == len(formatted_text): 
            self.ccp_input.setCursorPosition(current_cursor_pos)
        else: 
            self.ccp_input.setCursorPosition(len(formatted_text))
        self.ccp_input.blockSignals(False)


    def get_data(self):
        ccp_raw = self.ccp_input.text().replace(" ", "")
        return {
            "nin": self.nin_input.text().strip(),
            "wassit_no": self.wassit_no_input.text().strip(),
            "ccp": ccp_raw,
            "phone_number": self.phone_number_input.text().strip() 
        }

class SettingsDialog(QDialog):
    def __init__(self, current_settings, parent=None): 
        super().__init__(parent)
        self.setWindowTitle("إعدادات التطبيق")
        self.setModal(True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(400)

        from config import (
            SETTING_MIN_MEMBER_DELAY, SETTING_MAX_MEMBER_DELAY,
            SETTING_MONITORING_INTERVAL, SETTING_BACKOFF_429,
            SETTING_BACKOFF_GENERAL, SETTING_REQUEST_TIMEOUT, DEFAULT_SETTINGS
        )

        self.current_settings = current_settings
        layout = QFormLayout(self)
        layout.setLabelAlignment(Qt.AlignRight)

        self.min_delay_spin = QSpinBox(self)
        self.min_delay_spin.setRange(1, 300) 
        self.min_delay_spin.setValue(self.current_settings.get(SETTING_MIN_MEMBER_DELAY, DEFAULT_SETTINGS[SETTING_MIN_MEMBER_DELAY]))
        self.min_delay_spin.setSuffix(" ثانية")

        self.max_delay_spin = QSpinBox(self)
        self.max_delay_spin.setRange(1, 600) 
        self.max_delay_spin.setValue(self.current_settings.get(SETTING_MAX_MEMBER_DELAY, DEFAULT_SETTINGS[SETTING_MAX_MEMBER_DELAY]))
        self.max_delay_spin.setSuffix(" ثانية")

        self.monitoring_interval_spin = QSpinBox(self)
        self.monitoring_interval_spin.setRange(1, 120) 
        self.monitoring_interval_spin.setValue(self.current_settings.get(SETTING_MONITORING_INTERVAL, DEFAULT_SETTINGS[SETTING_MONITORING_INTERVAL]))
        self.monitoring_interval_spin.setSuffix(" دقيقة")

        self.backoff_429_spin = QSpinBox(self)
        self.backoff_429_spin.setRange(10, 3600) 
        self.backoff_429_spin.setValue(self.current_settings.get(SETTING_BACKOFF_429, DEFAULT_SETTINGS[SETTING_BACKOFF_429]))
        self.backoff_429_spin.setSuffix(" ثانية")

        self.backoff_general_spin = QSpinBox(self)
        self.backoff_general_spin.setRange(1, 300) 
        self.backoff_general_spin.setValue(self.current_settings.get(SETTING_BACKOFF_GENERAL, DEFAULT_SETTINGS[SETTING_BACKOFF_GENERAL]))
        self.backoff_general_spin.setSuffix(" ثانية")
        
        self.request_timeout_spin = QSpinBox(self)
        self.request_timeout_spin.setRange(5, 120) 
        self.request_timeout_spin.setValue(self.current_settings.get(SETTING_REQUEST_TIMEOUT, DEFAULT_SETTINGS[SETTING_REQUEST_TIMEOUT]))
        self.request_timeout_spin.setSuffix(" ثانية")


        layout.addRow("أقل تأخير بين الأعضاء:", self.min_delay_spin)
        layout.addRow("أقصى تأخير بين الأعضاء:", self.max_delay_spin)
        layout.addRow("الفاصل الزمني لدورة المراقبة:", self.monitoring_interval_spin)
        layout.addRow("تأخير أولي لخطأ 429 (طلبات كثيرة):", self.backoff_429_spin)
        layout.addRow("تأخير أولي للأخطاء العامة:", self.backoff_general_spin)
        layout.addRow("مهلة الطلب للواجهة البرمجية (API):", self.request_timeout_spin)


        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, Qt.Horizontal, self)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ الإعدادات")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def get_settings(self):
        from config import (
            SETTING_MIN_MEMBER_DELAY, SETTING_MAX_MEMBER_DELAY,
            SETTING_MONITORING_INTERVAL, SETTING_BACKOFF_429,
            SETTING_BACKOFF_GENERAL, SETTING_REQUEST_TIMEOUT
        )
        min_val = self.min_delay_spin.value()
        max_val = self.max_delay_spin.value()
        if min_val > max_val:
            min_val = max_val 
            self.min_delay_spin.setValue(min_val) 

        return {
            SETTING_MIN_MEMBER_DELAY: min_val,
            SETTING_MAX_MEMBER_DELAY: max_val,
            SETTING_MONITORING_INTERVAL: self.monitoring_interval_spin.value(),
            SETTING_BACKOFF_429: self.backoff_429_spin.value(),
            SETTING_BACKOFF_GENERAL: self.backoff_general_spin.value(),
            SETTING_REQUEST_TIMEOUT: self.request_timeout_spin.value()
        }

class ViewMemberDialog(QDialog):
    def __init__(self, member, parent=None):
        super().__init__(parent)
        self.member = member
        self.setWindowTitle(f"عرض معلومات العضو: {self.member.get_full_name_ar() or self.member.nin}")
        self.setModal(True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(550) 
        self.setMinimumHeight(400) 
        
        main_dialog_layout = QVBoxLayout(self)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded) 
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)   

        content_widget = QWidget()
        form_layout = QFormLayout(content_widget) 
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setSpacing(10)

        def add_read_only_field(label_text, value_text):
            value_edit = QLineEdit(str(value_text) if value_text is not None else "")
            value_edit.setReadOnly(True)
            value_edit.setStyleSheet("QLineEdit:read-only { background-color: #3E4A5C; color: #E0E0E0; border: 1px solid #4A5568; }")
            form_layout.addRow(label_text, value_edit)

        add_read_only_field("الاسم الكامل (عربي):", self.member.get_full_name_ar())
        add_read_only_field("الاسم (لاتيني):", self.member.nom_fr)
        add_read_only_field("اللقب (لاتيني):", self.member.prenom_fr)
        add_read_only_field("رقم التعريف الوطني (NIN):", self.member.nin)
        add_read_only_field("رقم طالب الشغل (الوسيط):", self.member.wassit_no)
        
        ccp_display = self.member.ccp
        if len(self.member.ccp) == 12:
             ccp_display = f"{self.member.ccp[:10]} {self.member.ccp[10:]}"
        add_read_only_field("رقم الحساب البريدي (CCP):", ccp_display)
        add_read_only_field("رقم الهاتف:", self.member.phone_number)
        add_read_only_field("الحالة الحالية:", self.member.status)
        
        rdv_date_display = self.member.rdv_date or "لا يوجد"
        if self.member.rdv_date:
            if self.member.rdv_source == "system":
                rdv_date_display += " (نظام)"
            elif self.member.rdv_source == "discovered":
                 rdv_date_display += " (مكتشف)"
        add_read_only_field("تاريخ الموعد:", rdv_date_display)
        
        details_label = QLabel("آخر تحديث/خطأ (كامل):")
        self.details_text_edit = QTextEdit(self.member.full_last_activity_detail or "لا يوجد")
        self.details_text_edit.setReadOnly(True)
        self.details_text_edit.setFixedHeight(80) 
        self.details_text_edit.setStyleSheet("QTextEdit:read-only { background-color: #3E4A5C; color: #E0E0E0; border: 1px solid #4A5568; }")
        form_layout.addRow(details_label, self.details_text_edit)

        add_read_only_field("ID التسجيل المسبق:", self.member.pre_inscription_id or "N/A")
        add_read_only_field("ID طالب الشغل:", self.member.demandeur_id or "N/A")
        add_read_only_field("ID الهيكل:", self.member.structure_id or "N/A")
        add_read_only_field("ID الموعد:", self.member.rdv_id or "N/A")
        add_read_only_field("مصدر الموعد:", self.member.rdv_source or "غير محدد")
        add_read_only_field("مسار ملف الالتزام:", self.member.pdf_honneur_path or "لم يتم التحميل")
        add_read_only_field("مسار ملف الموعد:", self.member.pdf_rdv_path or "لم يتم التحميل")
        add_read_only_field("لديه تسجيل مسبق فعلي؟:", "نعم" if self.member.has_actual_pre_inscription else "لا")
        add_read_only_field("لديه موعد بالفعل؟:", "نعم" if self.member.already_has_rdv else "لا")
        add_read_only_field("عدد مرات الفشل المتتالية:", str(self.member.consecutive_failures))
        add_read_only_field("مستفيد حاليًا من المنحة؟:", "نعم" if self.member.have_allocation else "لا")
        
        if self.member.have_allocation and self.member.allocation_details:
            allocation_details_str = ", ".join(f"{key}: {value}" for key, value in self.member.allocation_details.items())
            add_read_only_field("تفاصيل الاستفادة:", allocation_details_str or "لا توجد تفاصيل")

        scroll_area.setWidget(content_widget)
        main_dialog_layout.addWidget(scroll_area) 

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.close_button = QPushButton("إغلاق")
        self.close_button.clicked.connect(self.accept) 
        button_layout.addWidget(self.close_button)
        button_layout.addStretch()
        main_dialog_layout.addLayout(button_layout) 

class ActivationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تفعيل البرنامج")
        self.setModal(True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(400) # زيادة العرض قليلًا
        self.setObjectName("ActivationDialog") # لتمكين التنسيق الخاص

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20) # إضافة هوامش
        main_layout.setSpacing(15) # زيادة التباعد

        # --- إطار علوي للشعار والعنوان ---
        header_frame = QFrame(self)
        header_frame.setObjectName("ActivationHeaderFrame")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0,0,0,0)

        # شعار (أيقونة مفتاح أو قفل)
        self.icon_label = QLabel(self)
        # يمكنك استخدام أيقونة من QStyle أو تحميل صورة
        key_icon = self.style().standardIcon(QStyle.SP_ComputerIcon) #  SP_DriveHDICon أو SP_ComputerIcon كأمثلة
        if not key_icon.isNull():
             self.icon_label.setPixmap(key_icon.pixmap(48, 48)) # حجم مناسب
        self.icon_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.icon_label)

        title_font = QFont("Tajawal Medium", 16) # استخدام خط Tajawal Medium
        title_font.setBold(True)
        self.title_label = QLabel("تفعيل البرنامج", self)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setObjectName("ActivationTitleLabel")
        header_layout.addWidget(self.title_label)
        
        header_layout.setStretch(1,1) # لجعل العنوان يتمدد
        main_layout.addWidget(header_frame)
        
        # --- رسالة التعليمات ---
        self.instruction_label = QLabel("الرجاء إدخال كود التفعيل الخاص بك للمتابعة:", self)
        self.instruction_label.setAlignment(Qt.AlignCenter)
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setObjectName("ActivationInstructionLabel")
        main_layout.addWidget(self.instruction_label)

        # --- حقل إدخال الكود ---
        self.activation_code_input = QLineEdit(self)
        self.activation_code_input.setPlaceholderText("أدخل كود التفعيل هنا")
        self.activation_code_input.setAlignment(Qt.AlignCenter) # محاذاة النص في الوسط
        self.activation_code_input.setMinimumHeight(35) # زيادة ارتفاع الحقل
        self.activation_code_input.setObjectName("ActivationCodeInput")
        # يمكنك إضافة QValidator هنا إذا كان للكود تنسيق معين
        main_layout.addWidget(self.activation_code_input)

        # --- رسالة الحالة ---
        self.status_label = QLabel("", self) 
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(30) # حجز مساحة لرسالة الحالة
        self.status_label.setObjectName("ActivationStatusLabel")
        main_layout.addWidget(self.status_label)
        
        # --- فاصل ---
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line)

        # --- الأزرار ---
        self.buttons_layout = QHBoxLayout() # تخطيط أفقي للأزرار
        self.buttons_layout.setSpacing(10)

        self.activate_button = QPushButton("تفعيل", self)
        self.activate_button.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.activate_button.setObjectName("ActivationActivateButton")
        self.buttons_layout.addWidget(self.activate_button)

        self.cancel_button = QPushButton("إلغاء", self)
        self.cancel_button.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
        self.cancel_button.setObjectName("ActivationCancelButton")
        self.buttons_layout.addWidget(self.cancel_button)
        
        main_layout.addLayout(self.buttons_layout)

        # ربط الإشارات
        self.activate_button.clicked.connect(self._handle_activate_clicked)
        self.cancel_button.clicked.connect(self.reject) # QDialog.reject() سيغلق النافذة

        # تطبيق بعض التنسيقات الأولية
        self.setStyleSheet("""
            QDialog#ActivationDialog {
                background-color: #2E2E2E; /* لون خلفية أغمق قليلاً */
            }
            QFrame#ActivationHeaderFrame {
                border-bottom: 1px solid #4A4A4A;
                padding-bottom: 10px;
                margin-bottom: 5px;
            }
            QLabel#ActivationTitleLabel {
                color: #00A2E8; /* لون أزرق مميز للعنوان */
                font-family: "Tajawal Bold"; /* تأكيد استخدام الخط العريض */
            }
            QLabel#ActivationInstructionLabel {
                color: #D0D0D0; /* لون أفتح قليلاً للتعليمات */
                font-size: 10pt;
                font-family: "Tajawal Regular";
            }
            QLineEdit#ActivationCodeInput {
                font-size: 12pt; /* خط أكبر لحقل الإدخال */
                font-family: "Tajawal Medium";
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px;
            }
            QLineEdit#ActivationCodeInput:focus {
                border: 1px solid #00A2E8;
            }
            QLabel#ActivationStatusLabel {
                font-size: 9pt;
                font-family: "Tajawal Regular";
                font-weight: bold;
            }
            QPushButton#ActivationActivateButton {
                background-color: #27AE60; /* أخضر للتفعيل */
                font-family: "Tajawal Bold";
                padding: 10px 20px;
            }
            QPushButton#ActivationActivateButton:hover {
                background-color: #2ECC71;
            }
            QPushButton#ActivationCancelButton {
                background-color: #7F8C8D; /* رمادي للإلغاء */
                font-family: "Tajawal Bold";
                padding: 10px 20px;
            }
            QPushButton#ActivationCancelButton:hover {
                background-color: #95A5A6;
            }
        """)

    def _handle_activate_clicked(self):
        """معالجة الضغط على زر التفعيل."""
        # سيتم استدعاء self.accept() من main_app.py بعد التحقق الناجح
        # هنا فقط نقوم بإعلام main_app.py بأن المستخدم ضغط "تفعيل"
        self.accept() 

    def get_activation_code(self):
        return self.activation_code_input.text().strip()

    def show_status_message(self, message, is_error=False):
        self.status_label.setText(message)
        if is_error:
            self.status_label.setStyleSheet("color: #E74C3C; font-weight: bold; font-family: 'Tajawal Regular';")
        else:
            self.status_label.setStyleSheet("color: #2ECC71; font-weight: bold; font-family: 'Tajawal Regular';")
        
        if "جاري التحقق" in message:
             self.status_label.setStyleSheet("color: #E0E0E0; font-family: 'Tajawal Regular';") # لون محايد للتحميل

