# firebase_service.py
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os
import json
import logging
import datetime # لاستخدامه مع الطوابع الزمنية في Firestore
import socket # لاسم الجهاز و IP المحلي
import platform # لنظام التشغيل
import getpass # لاسم المستخدم
import uuid # لإنشاء معرف فريد للجهاز إذا لم يكن موجودًا
import requests # لمحاولة الحصول على IP العام

# استيراد الثوابت من ملف config.py
from config import FIREBASE_SERVICE_ACCOUNT_KEY_FILE, ACTIVATION_STATUS_FILE, FIRESTORE_ACTIVATION_CODES_COLLECTION

logger = logging.getLogger(__name__)

class FirebaseService:
    def __init__(self):
        """
        تهيئة خدمة Firebase.
        تحاول تهيئة تطبيق Firebase Admin SDK باستخدام ملف مفتاح حساب الخدمة.
        """
        self.db = None
        self.app_initialized = False
        try:
            key_file_path = os.path.abspath(FIREBASE_SERVICE_ACCOUNT_KEY_FILE)
            logger.info(f"محاولة تهيئة Firebase باستخدام ملف المفتاح: {key_file_path}")

            if not firebase_admin._apps: 
                if os.path.exists(FIREBASE_SERVICE_ACCOUNT_KEY_FILE):
                    logger.info(f"ملف المفتاح '{FIREBASE_SERVICE_ACCOUNT_KEY_FILE}' موجود في المسار المتوقع.")
                    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_KEY_FILE)
                    firebase_admin.initialize_app(cred)
                    self.db = firestore.client()
                    self.app_initialized = True
                    logger.info("تم تهيئة Firebase Admin SDK بنجاح.")
                else:
                    logger.error(f"ملف مفتاح حساب خدمة Firebase '{FIREBASE_SERVICE_ACCOUNT_KEY_FILE}' (المسار المحسوب: {key_file_path}) غير موجود. لا يمكن تهيئة Firebase.")
            else: 
                self.db = firestore.client()
                self.app_initialized = True
                logger.info("تم استخدام تطبيق Firebase Admin SDK المهيأ مسبقًا.")

        except Exception as e:
            logger.exception(f"حدث خطأ أثناء تهيئة Firebase Admin SDK: {e}")
            if isinstance(e, ValueError) and "Could not deserialize credentials" in str(e):
                logger.error("خطأ في محتوى ملف مفتاح حساب الخدمة. تأكد من أن الملف بتنسيق JSON صحيح وغير تالف.")
            elif "Failed to parse private key" in str(e):
                 logger.error("فشل في تحليل المفتاح الخاص في ملف حساب الخدمة. تأكد من أن المفتاح صحيح.")


    def is_initialized(self):
        return self.app_initialized and self.db is not None

    def check_local_activation(self):
        if os.path.exists(ACTIVATION_STATUS_FILE):
            try:
                with open(ACTIVATION_STATUS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data.get("is_activated") and data.get("activation_code"):
                        logger.info(f"تم العثور على حالة تفعيل محلية صالحة بالكود: {data.get('activation_code')}")
                        return True, data.get("activation_code")
            except json.JSONDecodeError:
                logger.error(f"خطأ في فك ترميز ملف حالة التفعيل المحلي '{ACTIVATION_STATUS_FILE}'.")
            except Exception as e:
                logger.exception(f"خطأ غير متوقع عند قراءة ملف حالة التفعيل المحلي: {e}")
        logger.info("لم يتم العثور على حالة تفعيل محلية.")
        return False, None

    def save_local_activation(self, activation_code, device_info=None):
        """
        يحفظ حالة التفعيل محليًا بعد التحقق الناجح من Firebase.
        Args:
            activation_code (str): كود التفعيل الذي تم استخدامه.
            device_info (dict, optional): معلومات الجهاز.
        """
        data_to_save = {
            "is_activated": True,
            "activation_code": activation_code,
            "activated_at": datetime.datetime.now().isoformat(),
            "device_info": device_info if device_info else {} # حفظ معلومات الجهاز إذا توفرت
        }
        try:
            with open(ACTIVATION_STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=4)
            logger.info(f"تم حفظ حالة التفعيل المحلية بنجاح للكود: {activation_code}")
        except Exception as e:
            logger.exception(f"خطأ عند حفظ ملف حالة التفعيل المحلي: {e}")

    def verify_activation_code(self, code_to_verify):
        if not self.is_initialized():
            return False, "خدمة Firebase غير مهيأة. لا يمكن التحقق من الكود.", None

        if not code_to_verify or not code_to_verify.strip():
            return False, "كود التفعيل فارغ أو غير صالح.", None

        try:
            logger.debug(f"التحقق من كود التفعيل '{code_to_verify}' في مجموعة '{FIRESTORE_ACTIVATION_CODES_COLLECTION}'")
            code_ref = self.db.collection(FIRESTORE_ACTIVATION_CODES_COLLECTION).document(code_to_verify.strip())
            code_doc = code_ref.get()

            if code_doc.exists:
                code_data = code_doc.to_dict()
                status = code_data.get("status", "UNKNOWN").upper()
                
                expires_at_timestamp = code_data.get("expiresAt")
                if expires_at_timestamp:
                    if isinstance(expires_at_timestamp, datetime.datetime):
                        expires_at_dt = expires_at_timestamp
                    else: 
                        expires_at_dt = expires_at_timestamp.to_datetime()
                    
                    current_time_for_expiry_check = datetime.datetime.now(expires_at_dt.tzinfo if hasattr(expires_at_dt, 'tzinfo') else None)
                    if expires_at_dt < current_time_for_expiry_check:
                        logger.warning(f"كود التفعيل '{code_to_verify}' منتهي الصلاحية بتاريخ: {expires_at_dt}.")
                        return False, "كود التفعيل منتهي الصلاحية.", code_data

                if status == "UNUSED":
                    logger.info(f"كود التفعيل '{code_to_verify}' صالح وغير مستخدم.")
                    return True, "الكود صالح وجاهز للاستخدام.", code_data
                elif status == "ACTIVE":
                    logger.warning(f"كود التفعيل '{code_to_verify}' مستخدم بالفعل.")
                    # يمكن إرجاع بيانات الكود هنا حتى لو كان مستخدماً، ليتمكن main_app من فحص deviceID إذا أراد
                    return False, "كود التفعيل مستخدم بالفعل.", code_data 
                elif status == "EXPIRED":
                    logger.warning(f"كود التفعيل '{code_to_verify}' منتهي الصلاحية (حسب الحالة في Firebase).")
                    return False, "كود التفعيل منتهي الصلاحية.", code_data
                elif status == "REVOKED":
                    logger.warning(f"كود التفعيل '{code_to_verify}' تم سحبه.")
                    return False, "كود التفعيل تم سحبه من قبل المسؤول.", code_data
                else:
                    logger.warning(f"كود التفعيل '{code_to_verify}' بحالة غير معروفة: {status}.")
                    return False, f"حالة كود التفعيل غير صالحة: {status}.", code_data
            else:
                logger.warning(f"كود التفعيل '{code_to_verify}' غير موجود في قاعدة البيانات.")
                return False, "كود التفعيل غير صحيح أو غير موجود.", None
        except firebase_admin.exceptions.FirebaseError as fe:
            logger.exception(f"خطأ Firebase أثناء التحقق من كود التفعيل '{code_to_verify}': {fe}")
            if " UNAUTHENTICATED " in str(fe).upper() or "PERMISSION_DENIED" in str(fe).upper() or "invalid_grant" in str(fe).lower():
                 return False, f"خطأ في المصادقة مع Firebase: {fe}. تأكد من صحة مفتاح الخدمة ووقت النظام.", None
            return False, f"خطأ في قاعدة بيانات Firebase أثناء التحقق: {fe}", None
        except Exception as e:
            logger.exception(f"حدث خطأ عام أثناء التحقق من كود التفعيل '{code_to_verify}' في Firestore: {e}")
            return False, f"خطأ عام في الاتصال بقاعدة البيانات للتحقق من الكود: {e}", None

    def mark_code_as_used(self, code_to_mark, device_info=None):
        """
        يُحدّث حالة كود التفعيل في Firestore إلى 'ACTIVE' ويسجل وقت التفعيل ومعلومات الجهاز.
        Args:
            code_to_mark (str): الكود المراد تحديثه.
            device_info (dict, optional): قاموس يحتوي على معلومات الجهاز.
        Returns:
            bool: True إذا تم التحديث بنجاح، False خلاف ذلك.
        """
        if not self.is_initialized():
            logger.error("خدمة Firebase غير مهيأة. لا يمكن تحديث الكود.")
            return False

        try:
            code_ref = self.db.collection(FIRESTORE_ACTIVATION_CODES_COLLECTION).document(code_to_mark.strip())
            update_data = {
                "status": "ACTIVE",
                "activatedAt": firestore.SERVER_TIMESTAMP,
                "lastUsedAt": firestore.SERVER_TIMESTAMP
            }
            if device_info and isinstance(device_info, dict):
                update_data["activationDeviceInfo"] = device_info
                # إذا كنت تريد الاحتفاظ بـ activatedByDeviceID كحقل منفصل للمعرّف الأساسي
                if "generated_device_id" in device_info:
                    update_data["activatedByDeviceID"] = device_info["generated_device_id"]
            
            code_ref.update(update_data)
            logger.info(f"تم تحديث حالة كود التفعيل '{code_to_mark}' إلى ACTIVE في Firestore مع معلومات الجهاز.")
            return True
        except firebase_admin.exceptions.FirebaseError as fe:
            logger.exception(f"خطأ Firebase أثناء تحديث كود التفعيل '{code_to_mark}': {fe}")
            return False
        except Exception as e:
            logger.exception(f"حدث خطأ عام أثناء تحديث كود التفعيل '{code_to_mark}' في Firestore: {e}")
            return False

    def get_device_info(self):
        """
        يحاول الحصول على معلومات متنوعة عن الجهاز.
        Returns:
            dict: قاموس يحتوي على معلومات الجهاز.
        """
        device_info = {}
        
        # 1. المعرف الفريد للجهاز (UUID مخزن محليًا)
        local_device_id_file = "device_id.dat"
        generated_id = None
        try:
            if os.path.exists(local_device_id_file):
                with open(local_device_id_file, 'r') as f:
                    generated_id = f.read().strip()
            else:
                generated_id = str(uuid.uuid4())
                with open(local_device_id_file, 'w') as f:
                    f.write(generated_id)
                logger.info(f"تم إنشاء وتخزين معرف جهاز UUID جديد: {generated_id}")
            device_info["generated_device_id"] = generated_id
        except Exception as e:
            logger.error(f"خطأ في الحصول على أو إنشاء معرف UUID للجهاز: {e}")
            device_info["generated_device_id"] = "error_generating_uuid"

        # 2. اسم مستخدم النظام
        try:
            device_info["system_username"] = getpass.getuser()
        except Exception as e:
            logger.warning(f"لم يتمكن من الحصول على اسم مستخدم النظام: {e}")
            device_info["system_username"] = "N/A"

        # 3. اسم الجهاز (Hostname)
        try:
            device_info["hostname"] = socket.gethostname()
        except Exception as e:
            logger.warning(f"لم يتمكن من الحصول على اسم الجهاز (hostname): {e}")
            device_info["hostname"] = "N/A"
            
        # 4. عنوان IP المحلي (قد لا يكون مفيدًا دائمًا إذا كان خلف NAT)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80)) # الاتصال بخادم خارجي (لا يرسل بيانات فعلية)
            device_info["local_ip"] = s.getsockname()[0]
            s.close()
        except Exception as e:
            logger.warning(f"لم يتمكن من الحصول على عنوان IP المحلي: {e}")
            device_info["local_ip"] = "N/A"
            
        # 5. نظام التشغيل
        try:
            device_info["os_platform"] = platform.system()
            device_info["os_version"] = platform.version()
            device_info["os_release"] = platform.release()
            device_info["architecture"] = platform.machine()
        except Exception as e:
            logger.warning(f"لم يتمكن من الحصول على معلومات نظام التشغيل: {e}")
            device_info["os_platform"] = "N/A"

        # 6. عنوان IP العام (باستخدام خدمة خارجية)
        public_ip = "N/A"
        ip_services = ["https://api.ipify.org", "https://icanhazip.com", "https://ipinfo.io/ip"]
        for service_url in ip_services:
            try:
                response = requests.get(service_url, timeout=3) # مهلة قصيرة
                response.raise_for_status()
                public_ip = response.text.strip()
                logger.info(f"تم الحصول على عنوان IP العام: {public_ip} من {service_url}")
                break 
            except requests.exceptions.RequestException as e:
                logger.warning(f"فشل في الحصول على IP العام من {service_url}: {e}")
                public_ip = f"Error_from_{service_url.split('//')[1].split('/')[0]}" # مثال: Error_from_api.ipify.org
            if public_ip != "N/A" and not public_ip.startswith("Error_"):
                break
        device_info["public_ip"] = public_ip
        
        logger.info(f"معلومات الجهاز التي تم جمعها: {device_info}")
        return device_info


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG) 
    fb_service = FirebaseService()

    if fb_service.is_initialized():
        print("Firebase مهيأ.")
        
        print("\n--- اختبار جمع معلومات الجهاز ---")
        collected_info = fb_service.get_device_info()
        print("معلومات الجهاز المجمعة:")
        for key, value in collected_info.items():
            print(f"  {key}: {value}")
        
        print("\n--- اختبار تفعيل وهمي (لا يتم تحديث Firestore فعليًا هنا) ---")
        is_active_local, act_code_local = fb_service.check_local_activation()
        if is_active_local:
            print(f"البرنامج مفعل محليًا بالكود: {act_code_local}")
            is_still_valid, online_message, code_data = fb_service.verify_activation_code(act_code_local)
            print(f"التحقق عبر الإنترنت من الكود المحلي '{act_code_local}': {is_still_valid} - {online_message}")
            if code_data:
                print(f"بيانات الكود من Firebase: {code_data}")
        else:
            print("البرنامج غير مفعل محليًا.")
            
            # test_code_for_marking = "YOUR_UNUSED_TEST_CODE_FOR_MARKING" 
            # if test_code_for_marking != "YOUR_UNUSED_TEST_CODE_FOR_MARKING" and fb_service.is_initialized():
            #     print(f"\n--- محاولة وضع علامة على الكود '{test_code_for_marking}' كـ مستخدم (تتطلب كودًا صالحًا غير مستخدم) ---")
            #     is_valid_before_mark, msg_before_mark, _ = fb_service.verify_activation_code(test_code_for_marking)
            #     if is_valid_before_mark:
            #         print(f"الكود '{test_code_for_marking}' صالح للاستخدام قبل وضع العلامة.")
            #         if fb_service.mark_code_as_used(test_code_for_marking, collected_info):
            #             print(f"تم وضع علامة على الكود '{test_code_for_marking}' كـ مستخدم بنجاح مع معلومات الجهاز.")
            #             fb_service.save_local_activation(test_code_for_marking, collected_info)
            #         else:
            #             print(f"فشل وضع علامة على الكود '{test_code_for_marking}'.")
            #     else:
            #         print(f"لا يمكن وضع علامة على الكود '{test_code_for_marking}': {msg_before_mark}")
            # else:
            #     print("\nلتجربة `mark_code_as_used`, يرجى توفير كود اختبار غير مستخدم في `test_code_for_marking`.")

    else:
        print("فشل تهيئة Firebase.")

