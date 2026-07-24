import type { ProductSnapshot, ValidationIssue } from "../types";

const chinesePattern = /[\u3400-\u9fff]/;
const skuAllowedPattern = /^[A-Za-z0-9 ().-]+$/;

const riskyBrandWords = [
  "baojun",
  "toyota",
  "honda",
  "bmw",
  "mercedes",
  "benz",
  "audi",
  "volkswagen",
  "ford",
  "chevrolet",
  "peugeot",
  "hyundai",
  "kia",
  "nissan",
  "jeep",
  "apple",
  "samsung",
  "disney",
  "lego",
  "nike",
  "adidas"
];

const highRiskClaimWords = ["original", "genuine", "official", "authentic", "oem", "licensed"];

function hasCompatibilityContext(title: string, brand: string) {
  const escapedBrand = brand.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(compatible\\s+with|fits?|for)\\s+.{0,24}\\b${escapedBrand}\\b`, "i").test(title);
}

export function validateTitle(title: string, maxLength = 128): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const normalized = title.trim();

  if (!normalized) {
    issues.push({ severity: "P0", field: "title", message: "标题为空" });
  }

  if (chinesePattern.test(normalized)) {
    issues.push({ severity: "P1", field: "title", message: "标题仍包含中文字符" });
  }

  if (normalized.length > maxLength) {
    issues.push({
      severity: "P1",
      field: "title",
      message: `标题超过 ${maxLength} 个字符`
    });
  }

  const lower = normalized.toLowerCase();
  const hits = riskyBrandWords.filter((word) => lower.includes(word) && !hasCompatibilityContext(normalized, word));
  const claimHits = highRiskClaimWords.filter((word) => lower.includes(word));
  if (hits.length || claimHits.length) {
    issues.push({
      severity: "P1",
      field: "title",
      message: `标题疑似包含高风险品牌/授权表达：${[...hits, ...claimHits].join(", ")}`
    });
  }

  return issues;
}

export function validateSkuName(name: string): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const normalized = name.trim();

  if (!normalized) {
    issues.push({ severity: "P1", field: "sku", message: "SKU 自定义名称为空" });
  }

  if (normalized.length > 20) {
    issues.push({
      severity: "P1",
      field: "sku",
      message: `SKU 自定义名称超过 20 个字符：${normalized}`
    });
  }

  if (!skuAllowedPattern.test(normalized)) {
    issues.push({
      severity: "P1",
      field: "sku",
      message: `SKU 自定义名称包含不允许字符：${normalized}`
    });
  }

  return issues;
}

export function validateProduct(product: ProductSnapshot): ValidationIssue[] {
  const issues = [
    ...validateTitle(product.optimizedTitle),
    ...product.skuNames.flatMap(validateSkuName),
    ...product.validationErrors
  ];

  if (!product.categoryPath) {
    issues.push({ severity: "P0", field: "category", message: "未选择目标类目" });
  }

  if (!product.mainImages.length) {
    issues.push({ severity: "P0", field: "images", message: "没有可发布主图" });
  }

  if (product.priceCny <= 0) {
    issues.push({ severity: "P0", field: "price", message: "价格必须大于 0" });
  }

  return issues;
}

export function hasBlockingIssue(issues: ValidationIssue[]) {
  return issues.some((issue) => issue.severity === "P0" || issue.severity === "P1");
}
