# firebase_service.py
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os
import json
import logging
import datetime # لاستخدامه مع الطوابع الزمنية في Firestore

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
            if not firebase_admin._apps: # تحقق مما إذا كان التطبيق قد تم تهيئته بالفعل
                if os.path.exists(FIREBASE_SERVICE_ACCOUNT_KEY_FILE):
                    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_KEY_FILE)
                    firebase_admin.initialize_app(cred)
                    self.db = firestore.client()
                    self.app_initialized = True
                    logger.info("تم تهيئة Firebase Admin SDK بنجاح.")
                else:
                    logger.error(f"ملف مفتاح حساب خدمة Firebase '{FIREBASE_SERVICE_ACCOUNT_KEY_FILE}' غير موجود. لا يمكن تهيئة Firebase.")
            else: # إذا كان التطبيق مهيأ بالفعل، فقط احصل على عميل قاعدة البيانات
                self.db = firestore.client()
                self.app_initialized = True
                logger.info("تم استخدام تطبيق Firebase Admin SDK المهيأ مسبقًا.")

        except Exception as e:
            logger.exception(f"حدث خطأ أثناء تهيئة Firebase Admin SDK: {e}")

    def is_initialized(self):
        """
        للتحقق مما إذا تم تهيئة Firebase بنجاح.
        """
        return self.app_initialized and self.db is not None

    def check_local_activation(self):
        """
        يتحقق من وجود حالة تفعيل صالحة مخزنة محليًا.
        Returns:
            bool: True إذا كان البرنامج مفعلًا محليًا، False خلاف ذلك.
            str: كود التفعيل إذا كان مفعلًا، None خلاف ذلك.
        """
        if os.path.exists(ACTIVATION_STATUS_FILE):
            try:
                with open(ACTIVATION_STATUS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # يمكن إضافة المزيد من التحققات هنا، مثل تاريخ انتهاء الصلاحية المحلي إذا أردت
                    if data.get("is_activated") and data.get("activation_code"):
                        logger.info(f"تم العثور على حالة تفعيل محلية صالحة بالكود: {data.get('activation_code')}")
                        return True, data.get("activation_code")
            except json.JSONDecodeError:
                logger.error(f"خطأ في فك ترميز ملف حالة التفعيل المحلي '{ACTIVATION_STATUS_FILE}'.")
                # يمكن حذف الملف التالف هنا إذا أردت
            except Exception as e:
                logger.exception(f"خطأ غير متوقع عند قراءة ملف حالة التفعيل المحلي: {e}")
        logger.info("لم يتم العثور على حالة تفعيل محلية.")
        return False, None

    def save_local_activation(self, activation_code, device_id=None):
        """
        يحفظ حالة التفعيل محليًا بعد التحقق الناجح من Firebase.
        Args:
            activation_code (str): كود التفعيل الذي تم استخدامه.
            device_id (str, optional): معرف الجهاز (إذا تم استخدامه).
        """
        data_to_save = {
            "is_activated": True,
            "activation_code": activation_code,
            "activated_at": datetime.datetime.now().isoformat(), # حفظ وقت التفعيل
            "device_id": device_id
        }
        try:
            with open(ACTIVATION_STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=4)
            logger.info(f"تم حفظ حالة التفعيل المحلية بنجاح للكود: {activation_code}")
        except Exception as e:
            logger.exception(f"خطأ عند حفظ ملف حالة التفعيل المحلي: {e}")

    def verify_activation_code(self, code_to_verify):
        """
        يتحقق من كود التفعيل مقابل Firestore.
        Args:
            code_to_verify (str): الكود المراد التحقق منه.
        Returns:
            tuple: (bool, str, dict)
                   - bool: True إذا كان الكود صالحًا وغير مستخدم، False خلاف ذلك.
                   - str: رسالة توضح نتيجة التحقق.
                   - dict: بيانات الكود من Firestore إذا وُجد، None خلاف ذلك.
        """
        if not self.is_initialized():
            return False, "خدمة Firebase غير مهيأة. لا يمكن التحقق من الكود.", None

        if not code_to_verify or not code_to_verify.strip():
            return False, "كود التفعيل فارغ أو غير صالح.", None

        try:
            code_ref = self.db.collection(FIRESTORE_ACTIVATION_CODES_COLLECTION).document(code_to_verify.strip())
            code_doc = code_ref.get()

            if code_doc.exists:
                code_data = code_doc.to_dict()
                status = code_data.get("status", "UNKNOWN").upper()
                
                # التحقق من تاريخ انتهاء الصلاحية (إذا كان موجودًا)
                expires_at_timestamp = code_data.get("expiresAt")
                if expires_at_timestamp:
                    # Firestore قد يعيد الطابع الزمني كـ datetime.datetime أو كـ google.cloud.firestore_v1.base_timestamp.Timestamp
                    if isinstance(expires_at_timestamp, datetime.datetime):
                        expires_at_dt = expires_at_timestamp
                    else: # نفترض أنه google.cloud.firestore_v1.base_timestamp.Timestamp
                        expires_at_dt = expires_at_timestamp.to_datetime()
                    
                    # تأكد من أن expires_at_dt هو timezone-aware إذا كان datetime.datetime.now() كذلك، أو العكس.
                    # للتبسيط، نفترض أن expires_at_dt و datetime.datetime.utcnow() كلاهما naive UTC أو aware UTC.
                    # إذا كنت تستخدم timezones، يجب التعامل معها بحذر هنا.
                    if expires_at_dt < datetime.datetime.now(expires_at_dt.tzinfo): # استخدام tzinfo من الطابع الزمني للمقارنة
                        logger.warning(f"كود التفعيل '{code_to_verify}' منتهي الصلاحية بتاريخ: {expires_at_dt}.")
                        return False, "كود التفعيل منتهي الصلاحية.", code_data

                if status == "UNUSED":
                    logger.info(f"كود التفعيل '{code_to_verify}' صالح وغير مستخدم.")
                    return True, "الكود صالح وجاهز للاستخدام.", code_data
                elif status == "ACTIVE":
                    logger.warning(f"كود التفعيل '{code_to_verify}' مستخدم بالفعل.")
                    # يمكنك هنا التحقق من activatedByDeviceID إذا كنت تريد السماح بإعادة التفعيل على نفس الجهاز
                    return False, "كود التفعيل مستخدم بالفعل.", code_data
                elif status == "EXPIRED":
                    logger.warning(f"كود التفعيل '{code_to_verify}' منتهي الصلاحية (حسب الحالة).")
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
        except Exception as e:
            logger.exception(f"حدث خطأ أثناء التحقق من كود التفعيل '{code_to_verify}' في Firestore: {e}")
            return False, f"خطأ في الاتصال بقاعدة البيانات للتحقق من الكود: {e}", None

    def mark_code_as_used(self, code_to_mark, device_id=None):
        """
        يُحدّث حالة كود التفعيل في Firestore إلى 'ACTIVE' ويسجل وقت التفعيل.
        Args:
            code_to_mark (str): الكود المراد تحديثه.
            device_id (str, optional): معرف الجهاز الذي قام بالتفعيل.
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
                "activatedAt": firestore.SERVER_TIMESTAMP # استخدام طابع الخادم الزمني
            }
            if device_id:
                update_data["activatedByDeviceID"] = device_id
            
            code_ref.update(update_data)
            logger.info(f"تم تحديث حالة كود التفعيل '{code_to_mark}' إلى ACTIVE في Firestore.")
            return True
        except Exception as e:
            logger.exception(f"حدث خطأ أثناء تحديث كود التفعيل '{code_to_mark}' في Firestore: {e}")
            return False

    def get_device_id(self):
        """
        يحاول الحصول على معرف فريد للجهاز.
        هذه دالة مبسطة، وقد تحتاج إلى طريقة أكثر قوة وموثوقية حسب نظام التشغيل.
        Returns:
            str: معرف الجهاز أو None إذا لم يتمكن من الحصول عليه.
        """
        # مثال بسيط باستخدام عنوان MAC (قد لا يعمل دائمًا أو يتطلب صلاحيات)
        # أو يمكن استخدام UUID يتم إنشاؤه مرة واحدة وتخزينه محليًا.
        try:
            # هذه طريقة غير موثوقة عبر المنصات المختلفة وبدون مكتبات خارجية
            # import uuid
            # return str(uuid.getnode()) # قد يعيد قيمة عشوائية إذا لم يتمكن من الحصول على MAC
            
            # بديل: إنشاء UUID وتخزينه محليًا إذا لم يكن موجودًا
            # هذا أبسط وأكثر توافقية مبدئيًا
            local_device_id_file = "device_id.dat"
            if os.path.exists(local_device_id_file):
                with open(local_device_id_file, 'r') as f:
                    return f.read().strip()
            else:
                import uuid
                new_id = str(uuid.uuid4())
                with open(local_device_id_file, 'w') as f:
                    f.write(new_id)
                return new_id
        except Exception as e:
            logger.error(f"خطأ في الحصول على معرف الجهاز: {e}")
            return None

# مثال للاستخدام (يمكن إزالته لاحقًا)
if __name__ == '__main__':
    # يتطلب وجود ملف firebase_service_account_key.json صالح في نفس المجلد
    # وتهيئة مشروع Firebase مع مجموعة 'activation_codes'
    logging.basicConfig(level=logging.INFO)
    fb_service = FirebaseService()

    if fb_service.is_initialized():
        print("Firebase مهيأ.")
        
        # اختبار التحقق المحلي
        is_active_local, act_code_local = fb_service.check_local_activation()
        if is_active_local:
            print(f"البرنامج مفعل محليًا بالكود: {act_code_local}")
        else:
            print("البرنامج غير مفعل محليًا.")

            # اختبار التحقق من كود (افترض أن 'TESTCODE123' موجود وحالته 'UNUSED')
            # test_code = "YOUR_UNUSED_TEST_CODE" 
            # is_valid, message, data = fb_service.verify_activation_code(test_code)
            # print(f"نتيجة التحقق من الكود '{test_code}': {is_valid} - {message}")

            # if is_valid:
            #     device_id = fb_service.get_device_id()
            #     print(f"معرف الجهاز: {device_id}")
            #     if fb_service.mark_code_as_used(test_code, device_id):
            #         print(f"تم تحديث الكود '{test_code}' كـ مستخدم.")
            #         fb_service.save_local_activation(test_code, device_id)
            #     else:
            #         print(f"فشل تحديث الكود '{test_code}'.")
    else:
        print("فشل تهيئة Firebase.")

