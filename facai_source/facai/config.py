import logging
import json
import time
import os
import sys
from datetime import datetime

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

def _is_writable_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, ".write_test.tmp")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except Exception:
        return False

USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "ShopAutomationGUI")
BASE_DIR = USER_DATA_DIR if getattr(sys, "frozen", False) else APP_DIR
os.makedirs(BASE_DIR, exist_ok=True)

class ShopAutomationLogger:
    def __init__(self, log_file=None):
        self.log_file = log_file or os.path.join(BASE_DIR, "automation.log")
        self.setup_logger()

    def setup_logger(self):
        self.logger = logging.getLogger("ShopAutomation")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

        target_log_file = os.path.abspath(self.log_file)
        for handler in self.logger.handlers:
            if isinstance(handler, logging.FileHandler) and os.path.abspath(handler.baseFilename) == target_log_file:
                return

        handler = logging.FileHandler(self.log_file, encoding="utf-8")
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    @staticmethod
    def stdout_enabled():
        value = os.environ.get("SHOP_AUTOMATION_QUIET_STDOUT", "").strip().lower()
        return value not in {"1", "true", "yes", "on"}

    def emit_stdout(self, prefix, msg):
        if not self.stdout_enabled():
            return
        print(f"{prefix} {msg}", flush=True)

    def info(self, msg):
        self.logger.info(msg)
        self.emit_stdout("[INFO]", msg)

    def success(self, msg):
        self.logger.info(f"SUCCESS: {msg}")
        self.emit_stdout("[SUCCESS]", msg)

    def error(self, msg):
        self.logger.error(msg)
        self.emit_stdout("[ERROR]", msg)

    def warning(self, msg):
        self.logger.warning(msg)
        self.emit_stdout("[WARN]", msg)

class ProductData:
    """用于存储商品数据的类"""
    def __init__(self, data_dict):
        self.data = data_dict
        self.logger = ShopAutomationLogger()

    def get_retail_price(self):
        """计算零售价 = 采集价格 * 7"""
        original_price = float(self.data.get('original_price', 0))
        return original_price * 7

    def get_value(self):
        """计算货值 = 采集价格 * 2"""
        original_price = float(self.data.get('original_price', 0))
        return original_price * 2

    def __repr__(self):
        return json.dumps(self.data, ensure_ascii=False, indent=2)

# 脚本配置（可被 runtime_config.json 覆盖）
CONFIG = {
    "category": "黑人化纤蕾丝发套",
    "template": "假发",
    "currency_template": "不包邮2",
    "service_template": "预设好的",
    "customs_item": "蕾丝假发",
    "customs_material": "高温纤维",
    "customs_process_mode": "按预设下拉选择",
    "stock": 5000,
    "weight": 0.14,
    "size": "26*16*6",
    "original_box": "是",
    "translation_type": "普通翻译",
    "language_pair": "中文-英文",
    "tax_included": "含关税报价",
    "european_responsible": "预设好的",
    "brand_manufacturer": "预设好的",
    "publish_action": "立即发布",
    "retail_multiplier": 7.0,
    "value_multiplier": 2.0,
    "max_items": 100,
    "delay_between_actions": 0.5,  # 操作之间的延迟（秒）
    "draft_search_keyword": "",
    "draft_search_type": "标题",
    "product_video_action": "删除",
    "description_image_mode": "保留前N张",
    "description_image_count": 5,
    "enable_ai_text": "否",
    "ai_text_api_url": "https://api.deepseek.com",
    "ai_text_api_key": "",
    "ai_text_model": "deepseek-v4-flash",
    "ai_text_prompt": "Translate and optimize the AliExpress title and SKU names into compliant English. Keep accurate product type, compatible brand/model words when present, avoid trademark infringement claims, and return strict JSON.",
    "enable_ai_image": "否",
    "ai_image_api_url": "https://ark.cn-beijing.volces.com/api/v3/images/generations",
    "ai_image_api_key": "",
    "ai_image_model": "doubao-seedream-5-0-260128",
    "ai_image_prompt": "保持商品主体完全不变，去除原背景和水印，将产品放在统一的浅灰色电商棚拍背景中。不要添加文字、logo、品牌标识、边框或装饰元素。画面干净真实，产品居中，1:1正方形构图，适合速卖通主图。",
    "ai_image_use_product_context": "否",
    "ai_image_size": "1K",
    "ai_image_count": 1,
    "ai_image_timeout_sec": 1800,
    "ai_image_poll_interval_sec": 15,
}

def load_runtime_config(config_path=None):
    config_path = config_path or os.path.join(BASE_DIR, "runtime_config.json")
    fallback_path = os.path.join(APP_DIR, "runtime_config.json")
    if (not getattr(sys, "frozen", False)) and not os.path.exists(config_path) and os.path.exists(fallback_path):
        config_path = fallback_path
    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            runtime_cfg = json.load(f)
        if isinstance(runtime_cfg, dict):
            CONFIG.update(runtime_cfg)
            return True
    except Exception:
        return False
    return False

logger = ShopAutomationLogger()
loaded = load_runtime_config()
logger.info("配置已加载")
logger.info(f"是否加载运行时配置: {loaded}")
safe_config = dict(CONFIG)
for key in list(safe_config.keys()):
    if "api_key" in key.lower() or key.lower().endswith("_key"):
        value = str(safe_config.get(key) or "")
        safe_config[key] = (value[:6] + "****") if value else ""
logger.info(f"配置内容: {json.dumps(safe_config, ensure_ascii=False, indent=2)}")
