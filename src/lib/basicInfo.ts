import type { BasicInfoSuggestion, CategoryPreset, ProductSnapshot, SkuSuggestion, ValidationIssue } from "../types";
import { validateSkuName, validateTitle } from "./validators";

const chinesePattern = /[\u3400-\u9fff]/g;

const categoryRules = [
  {
    presetId: "key-case",
    keywords: ["钥匙", "钥匙套", "钥匙包", "钥匙扣", "遥控", "车钥匙", "全包", "壳", "key", "remote", "shell", "button"],
    title: "Protective Car Key Case Cover Remote Key Shell",
    reason: "标题包含车钥匙套/遥控钥匙壳相关词"
  },
  {
    presetId: "door-knob-cover",
    keywords: ["门把手", "门把手套", "把手套", "防尘罩", "door knob", "handle sleeve", "dust cover"],
    title: "Door Knob Dust Cover Protective Handle Sleeve",
    reason: "标题包含门把手套/防尘罩相关词"
  },
  {
    presetId: "phone-case",
    keywords: ["手机壳", "保护套", "手机套", "防摔壳"],
    title: "Shockproof Phone Case Protective Cover",
    reason: "标题包含手机壳/保护套相关词"
  }
];

const riskyTermMap: Record<string, string> = {
  宝骏: "Baojun",
  丰田: "Toyota",
  本田: "Honda",
  宝马: "BMW",
  奔驰: "Mercedes",
  奥迪: "Audi",
  大众: "Volkswagen",
  福特: "Ford",
  雪佛兰: "Chevrolet",
  标致: "Peugeot",
  现代: "Hyundai",
  起亚: "Kia",
  日产: "Nissan",
  苹果: "Apple",
  三星: "Samsung",
  迪士尼: "Disney",
  耐克: "Nike",
  阿迪达斯: "Adidas",
  JEEP: "Jeep"
};

const skuReplacements: Array<[RegExp, string]> = [
  [/黑色/g, "Black"],
  [/白色/g, "White"],
  [/白/g, "White"],
  [/浅灰色/g, "Light Gray"],
  [/深灰色/g, "Dark Gray"],
  [/灰色/g, "Gray"],
  [/浅绿色/g, "Light Green"],
  [/绿色/g, "Green"],
  [/鹅黄色/g, "Yellow"],
  [/黄色/g, "Yellow"],
  [/红色/g, "Red"],
  [/蓝色/g, "Blue"],
  [/粉色/g, "Pink"],
  [/紫色/g, "Purple"],
  [/棕色/g, "Brown"],
  [/橙色/g, "Orange"],
  [/透明/g, "Clear"],
  [/金色/g, "Gold"],
  [/银色/g, "Silver"],
  [/按键/g, "Button"],
  [/按钮/g, "Button"],
  [/包边/g, "Full Cover"],
  [/全包/g, "Full Cover"],
  [/款/g, "Style"],
  [/个/g, ""]
];

function countHits(text: string, keywords: string[]) {
  const lower = text.toLowerCase();
  return keywords.reduce((score, keyword) => (lower.includes(keyword.toLowerCase()) ? score + 1 : score), 0);
}

function normalizeSpaces(text: string) {
  return text.replace(/\s+/g, " ").trim();
}

function detectRiskyTerms(text: string) {
  const lower = text.toLowerCase();
  return Object.entries(riskyTermMap)
    .filter(([cn, en]) => text.includes(cn) || lower.includes(en.toLowerCase()))
    .map(([, en]) => en);
}

function extractCompatibility(text: string) {
  const brand = Object.entries(riskyTermMap).find(([cn, en]) => text.includes(cn) || new RegExp(en, "i").test(text));
  const models = Array.from(new Set(text.match(/[A-Za-z]*\d[A-Za-z0-9]{1,7}/g) ?? []))
    .filter((model) => !/^\d{1,2}$/.test(model))
    .slice(0, 8);

  return {
    brandName: brand?.[1] ?? "",
    models
  };
}

function stripRiskyTerms(text: string) {
  let cleaned = text;
  for (const [cn, en] of Object.entries(riskyTermMap)) {
    cleaned = cleaned.replace(new RegExp(cn, "g"), " ");
    cleaned = cleaned.replace(new RegExp(en, "gi"), " ");
  }
  return normalizeSpaces(cleaned);
}

function currentCategoryLooksLike(currentPath: string, preset: CategoryPreset) {
  if (!currentPath || !preset) {
    return false;
  }
  const haystack = currentPath.toLowerCase();
  if (preset.id === "key-case") {
    return /钥匙|key/.test(haystack);
  }
  if (preset.id === "door-knob-cover") {
    return /门把手|door knob|防尘/.test(haystack);
  }
  if (preset.id === "phone-case") {
    return /手机|phone/.test(haystack);
  }
  return currentPath.includes(preset.name);
}

function chooseCategoryPreset(product: ProductSnapshot, presets: CategoryPreset[]) {
  const productSignalText = `${product.originalTitle} ${product.optimizedTitle} ${product.skuNames.join(" ")}`;
  const compatibility = extractCompatibility(productSignalText);
  const hasVehicleSignal = Boolean(compatibility.brandName && compatibility.models.length);
  const ranked = categoryRules
    .map((rule) => {
      let score = countHits(productSignalText, rule.keywords);
      let reason = rule.reason;

      if (rule.presetId === "key-case" && hasVehicleSignal) {
        score += 8;
        reason = `识别到汽车品牌/车型信号：${compatibility.brandName} ${compatibility.models.join(" ")}`;
      }

      if (rule.presetId === "door-knob-cover" && hasVehicleSignal) {
        score -= 6;
      }

      return {
        rule: { ...rule, reason },
        score,
        preset: presets.find((preset) => preset.id === rule.presetId) ?? null
      };
    })
    .filter((item) => item.preset)
    .sort((a, b) => b.score - a.score);

  const best = ranked[0];
  if (!best || best.score === 0) {
    return {
      preset: null,
      confidence: 0,
      title: "General Product Protective Cover",
      reason: "没有命中已配置的类目关键词，需要人工确认"
    };
  }

  return {
    preset: best.preset,
    confidence: Math.min(95, 55 + best.score * 12),
    title: best.rule.title,
    reason: best.rule.reason
  };
}

function titleForPreset(preset: CategoryPreset) {
  const text = `${preset.id} ${preset.name} ${preset.path}`.toLowerCase();
  if (/key|钥匙/.test(text)) {
    return "Protective Car Key Case Cover Remote Key Shell";
  }
  if (/storage|收纳|储物/.test(text)) {
    return "Car Interior Storage Box Organizer";
  }
  if (/ornament|摆件|decor/.test(text)) {
    return "Car Interior Decorative Ornament";
  }
  if (/air freshener|香薰|香氛/.test(text)) {
    return "Car Air Freshener Interior Fragrance";
  }
  if (/door knob|门把手/.test(text)) {
    return "Door Knob Dust Cover Protective Handle Sleeve";
  }
  if (/phone|手机/.test(text)) {
    return "Shockproof Phone Case Protective Cover";
  }
  return `${preset.name.replace(/\(.+?\)/g, "").trim()} Product`.replace(/[\u3400-\u9fff]/g, "").trim() || "General Product";
}

function buildOptimizedTitle(product: ProductSnapshot, baseTitle: string) {
  const source = stripRiskyTerms(product.originalTitle);
  const compatibility = extractCompatibility(`${product.originalTitle} ${product.optimizedTitle}`);
  const hasTpu = /tpu|硅胶|塑料|软胶/i.test(source);
  const parts = [baseTitle];

  if (compatibility.brandName) {
    parts.push("Compatible with", compatibility.brandName);
  }

  if (compatibility.models.length) {
    parts.push(compatibility.models.join(" "));
  }

  if (hasTpu && !/tpu/i.test(baseTitle)) {
    parts.push("TPU");
  }

  return normalizeSpaces(parts.join(" ")).slice(0, 128);
}

export function translateSkuName(name: string): string {
  const prefixMatch = name.trim().match(/^([A-Za-z0-9]+)\s*[-_－—]?\s*(.*)$/);
  const prefix = prefixMatch?.[1] ?? "";
  let rest = prefixMatch?.[2] ?? name;

  for (const [pattern, replacement] of skuReplacements) {
    rest = rest.replace(pattern, ` ${replacement} `);
  }

  rest = rest.replace(chinesePattern, " ");
  rest = rest.replace(/[_－—/|,，;；]+/g, " ");
  rest = normalizeSpaces(rest).replace(/\b([A-Za-z]+)( \1\b)+/gi, "$1");

  let suggested = normalizeSpaces([prefix, rest].filter(Boolean).join("-"));
  suggested = suggested.replace(/\s*-\s*/g, "-");

  if (!suggested || /^[A-Za-z0-9]+$/.test(suggested)) {
    suggested = prefix ? `${prefix}-Option` : "Option";
  }

  if (suggested.length > 20) {
    const [head, tail] = suggested.split("-", 2);
    const compactTail = normalizeSpaces((tail || suggested).replace(/\bLight\b/g, "Lt").replace(/\bDark\b/g, "Dk"));
    suggested = head && tail ? `${head}-${compactTail}` : compactTail;
  }

  if (suggested.length > 20) {
    suggested = suggested.slice(0, 20).trim().replace(/[ .-]+$/g, "");
  }

  return suggested;
}

function suggestSkus(product: ProductSnapshot): SkuSuggestion[] {
  return product.skuNames.map((original) => {
    const suggested = translateSkuName(original);
    return {
      original,
      suggested,
      issues: validateSkuName(suggested)
    };
  });
}

export function suggestBasicInfo(product: ProductSnapshot, presets: CategoryPreset[], forcedPresetId = ""): BasicInfoSuggestion {
  const forcedPreset = forcedPresetId ? presets.find((preset) => preset.id === forcedPresetId) ?? null : null;
  const category = forcedPreset
    ? {
        preset: forcedPreset,
        confidence: 100,
        title: titleForPreset(forcedPreset),
        reason: `已锁定本批类目预设：${forcedPreset.name}`
      }
    : chooseCategoryPreset(product, presets);
  const optimizedTitle = buildOptimizedTitle(product, category.title);
  const riskyTerms = detectRiskyTerms(`${product.originalTitle} ${product.optimizedTitle}`);
  const titleIssues: ValidationIssue[] = validateTitle(optimizedTitle);
  const categoryMismatch = Boolean(category.preset && product.categoryPath && !currentCategoryLooksLike(product.categoryPath, category.preset));
  const skuSuggestions = suggestSkus(product);
  const notes = [
    "当前建议仅写入应用预览，不会修改店小秘页面。",
    "标题生成会保留品牌/车型搜索词，但统一使用 Compatible with/for 这类适配表达。",
    categoryMismatch ? "扫描到的当前类目与标题识别结果不一致，建议先人工确认类目后再自动填属性模板。" : "当前类目和识别结果没有明显冲突。"
  ];

  return {
    sourceTitle: product.originalTitle,
    optimizedTitle,
    titleIssues,
    categoryPreset: category.preset,
    currentCategoryPath: product.categoryPath,
    categoryConfidence: category.confidence,
    categoryReason: category.reason,
    categoryMismatch,
    skuSuggestions,
    riskyTerms,
    notes
  };
}
