import type { CategoryPreset, ImageRule, PricingRule, ProductSnapshot, RunLog, WorkflowStep } from "./types";

export const workflowSteps: WorkflowStep[] = [
  {
    key: "basicInfo",
    title: "基本信息",
    summary: "识别正确类目，生成合规英文标题，保护标题不被二次翻译覆盖。",
    status: "ready",
    checks: ["类目必须选择到叶子类目", "标题无中文", "标题不包含侵权品牌", "标题长度符合平台限制"],
    automationNotes: ["监听 /api/smtCategory/searchCategory.json", "选择类目后重新扫描属性区"]
  },
  {
    key: "dxmInfo",
    title: "店小秘信息",
    summary: "保持不改，只读取来源 URL 作为商品识别、图片采集和类目判断信号。",
    status: "ready",
    checks: ["来源 URL 可读取", "不写入采购备注"],
    automationNotes: ["只读 sourceUrl", "失败不阻断主流程"]
  },
  {
    key: "attributeInfo",
    title: "属性信息",
    summary: "按类目选择预设属性模板，缺失模板时进入人工确认。",
    status: "pending",
    checks: ["模板存在", "品牌/产地/材质等必填项完整", "联动属性刷新后重新扫描"],
    automationNotes: ["读取 /api/smtAttributeTemplate/getTemplateListByCategory.json", "低置信度选项不自动点击"]
  },
  {
    key: "productInfo",
    title: "产品信息",
    summary: "处理主图、营销图、SKU 表格、价格库存尺寸和物流属性。",
    status: "pending",
    checks: ["主图已替换", "多 SKU 批量填充完成", "SKU 名称 <= 20 字符", "物流属性选择普货"],
    automationNotes: ["DOM 读取图片 URL", "图片上传先走页面 input#localFileUploadInp", "多 SKU 使用批量入口"]
  },
  {
    key: "regionalPricing",
    title: "区域调价信息",
    summary: "选择预设区域调价模板，模板缺失时记录为可人工处理错误。",
    status: "pending",
    checks: ["区域调价模板存在", "模板选择后无红字错误"],
    automationNotes: ["读取模板下拉框选项", "按模板名精确匹配"]
  },
  {
    key: "descriptionInfo",
    title: "描述信息",
    summary: "详情图保留前 N 张，中文描述翻译为英文，无线端使用老版编辑器后一键生成。",
    status: "pending",
    checks: ["详情无中文正文", "详情图数量符合配置", "无线端描述已生成"],
    automationNotes: ["进入 CKEditor iframe 读写 HTML", "处理弹窗确认"]
  },
  {
    key: "packageInfo",
    title: "包装信息",
    summary: "按规则填包装重量、尺寸、自定义计重。",
    status: "pending",
    checks: ["重量大于 0", "长宽高完整", "单位为 kg/cm"],
    automationNotes: ["从类目配置或价格规则取默认值"]
  },
  {
    key: "templateInfo",
    title: "模板信息",
    summary: "选择运费模板、服务模板，兼容复杂海关监管属性弹窗和多级联动下拉。",
    status: "pending",
    checks: ["运费模板已选", "服务模板已选", "海关监管属性完成或进入人工确认"],
    automationNotes: ["监听 freightList/allShopFreightList", "海关联动每次选择后重新扫描 DOM"]
  },
  {
    key: "otherInfo",
    title: "其他信息",
    summary: "设置关税报价、欧盟责任人、品牌制造商和商机/资质相关字段。",
    status: "pending",
    checks: ["关税报价已选择", "欧盟责任人已选择", "品牌制造商已选择"],
    automationNotes: ["读取责任人和制造商接口", "缺失配置时人工确认"]
  },
  {
    key: "translationCheck",
    title: "翻译与校验",
    summary: "先全局翻译再回写优化标题，或只做字段级翻译，最后收集红字错误。",
    status: "pending",
    checks: ["无红字错误", "标题未被一键翻译覆盖", "SKU 字符规则通过"],
    automationNotes: ["默认 global_then_restore_title", "校验所有 .ant-form-item-explain-error"]
  },
  {
    key: "publish",
    title: "发布/移入待发布",
    summary: "默认保存并移入待发布，稳定后可开启立即发布。",
    status: "pending",
    checks: ["P0/P1 错误为 0", "保存/发布按钮可用", "成功后记录商品状态"],
    automationNotes: ["建议第一阶段禁用立即发布", "成功/失败都保存截图和 DOM 快照"]
  }
];

export const categoryPresets: CategoryPreset[] = [
  {
    id: "key-case",
    name: "汽车钥匙包(Key Case for Car)",
    path: "汽车及零配件 > 内外饰配件 > 汽车钥匙包(Key Case for Car)",
    attributeTemplate: "汽车钥匙套通用属性",
    freightTemplate: "普货小包-标准",
    serviceTemplate: "默认服务模板",
    customsMode: "modal_cascade",
    customsDefaults: ["普通商品", "塑料/TPU", "汽车配件", "钥匙保护套"]
  },
  {
    id: "door-knob-cover",
    name: "门把手套",
    path: "家居用品 > 家居日用品 > 防尘保护罩 > 门把手套",
    attributeTemplate: "家居防尘罩通用属性",
    freightTemplate: "普货小包-标准",
    serviceTemplate: "默认服务模板",
    customsMode: "direct_add",
    customsDefaults: ["Household Cover", "Polyester", "Home Textile"]
  },
  {
    id: "phone-case",
    name: "手机壳",
    path: "手机通讯配件 > 手机保护套",
    attributeTemplate: "手机壳基础属性",
    freightTemplate: "普货小包-标准",
    serviceTemplate: "默认服务模板",
    customsMode: "modal_cascade",
    customsDefaults: ["Phone Case", "TPU", "Mobile Accessories"]
  }
];

export const pricingRules: PricingRule[] = [
  {
    id: "standard-small",
    name: "普货小件标准倍率",
    priceMultiplier: 2.8,
    declaredValueMultiplier: 0.35,
    stock: 100,
    weightKg: 0.12,
    packageSizeCm: [15, 12, 4],
    originalBox: false,
    logisticAttribute: "普货"
  },
  {
    id: "home-textile",
    name: "家纺/防尘罩倍率",
    priceMultiplier: 2.4,
    declaredValueMultiplier: 0.3,
    stock: 80,
    weightKg: 0.35,
    packageSizeCm: [28, 22, 6],
    originalBox: false,
    logisticAttribute: "普货"
  }
];

export const imageRules: ImageRule[] = [
  {
    id: "clean-studio",
    name: "统一浅灰白棚拍背景",
    mainImageCount: 6,
    detailImageCount: 6,
    backgroundPrompt:
      "Remove the original background and place the real product on a clean light gray studio background. Keep the product shape, color, material, quantity, and details unchanged. Do not add text, logos, props, hands, or extra accessories.",
    size: "1000x1000"
  },
  {
    id: "white-marketplace",
    name: "白底电商主图",
    mainImageCount: 6,
    detailImageCount: 5,
    backgroundPrompt:
      "Create a marketplace compliant white background product image. Preserve the exact product and all visible details. No text, no watermark, no decorative objects.",
    size: "1000x1000"
  }
];

export const sampleProduct: ProductSnapshot = {
  productId: "163252745167086065",
  sourceUrl: "https://detail.1688.com/offer/1016419333026.html",
  originalTitle: "专用于宝骏钥匙套510 730 310W车200E100壳560 530 630扣360全包",
  optimizedTitle: "Protective Car Key Case Cover for Baojun 510 730 310W 560 530 630 Remote Key Shell",
  categoryPath: "汽车及零配件 > 内饰配件 > 钥匙包",
  mainImages: [
    "https://cbu01.alicdn.com/img/ibank/O1CN01dUbsgU1ZXwViXOSJJ_!!2212379153205-0-cib.jpg",
    "https://cbu01.alicdn.com/img/ibank/O1CN01MxLT1K1ZXwVjRJCVz_!!2212379153205-0-cib.jpg",
    "https://cbu01.alicdn.com/img/ibank/O1CN01HkCb2C1ZXwVd6tpDF_!!2212379153205-0-cib.jpg"
  ],
  detailImages: [
    "https://cbu01.alicdn.com/img/ibank/O1CN01vDzpJe1ZXwVjRGvAZ_!!2212379153205-0-cib.jpg",
    "https://cbu01.alicdn.com/img/ibank/O1CN01Ehq1Iu1ZXwV71ZSQS_!!2212379153205-0-cib.jpg"
  ],
  skuNames: ["A-Black White Button", "C-Black White Button", "D-Black White Button"],
  priceCny: 3.79,
  validationErrors: [
    { severity: "P2", field: "title", message: "原始标题含中文，需先写入优化英文标题" },
    { severity: "P1", field: "category", message: "当前类目与商品识别结果差异较大，需确认" }
  ]
};

export const initialLogs: RunLog[] = [
  {
    id: "1",
    time: "16:42:11",
    module: "页面扫描",
    status: "success",
    message: "已识别 9 个模块、82 个按钮、248 个输入控件"
  },
  {
    id: "2",
    time: "16:43:02",
    module: "图片采集",
    status: "success",
    message: "已读取主图 14 张、详情图 13 张"
  },
  {
    id: "3",
    time: "16:44:20",
    module: "海关监管",
    status: "warning",
    severity: "P2",
    message: "海关字段存在多级联动，需要类目模板或人工预设"
  }
];
