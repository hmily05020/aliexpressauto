export type ModuleKey =
  | "basicInfo"
  | "dxmInfo"
  | "attributeInfo"
  | "productInfo"
  | "regionalPricing"
  | "descriptionInfo"
  | "packageInfo"
  | "templateInfo"
  | "otherInfo"
  | "translationCheck"
  | "publish";

export type StepStatus = "pending" | "ready" | "running" | "success" | "warning" | "failed";

export type Severity = "P0" | "P1" | "P2" | "P3";

export interface WorkflowStep {
  key: ModuleKey;
  title: string;
  summary: string;
  status: StepStatus;
  checks: string[];
  automationNotes: string[];
}

export interface CategoryPreset {
  id: string;
  name: string;
  path: string;
  attributeTemplate: string;
  freightTemplate: string;
  serviceTemplate: string;
  customsMode: "direct_add" | "modal_cascade" | "manual_review";
  customsDefaults: string[];
}

export interface PricingRule {
  id: string;
  name: string;
  priceMultiplier: number;
  declaredValueMultiplier: number;
  stock: number;
  weightKg: number;
  packageSizeCm: [number, number, number];
  originalBox: boolean;
  logisticAttribute: string;
}

export interface ImageRule {
  id: string;
  name: string;
  mainImageCount: number;
  detailImageCount: number;
  backgroundPrompt: string;
  size: string;
}

export interface ProductSnapshot {
  productId: string;
  sourceUrl: string;
  originalTitle: string;
  optimizedTitle: string;
  categoryPath: string;
  mainImages: string[];
  detailImages: string[];
  skuNames: string[];
  priceCny: number;
  validationErrors: ValidationIssue[];
}

export interface ProductTask {
  id: string;
  title: string;
  imageUrl: string;
  status: string;
  source: string;
  editText: string;
  rowIndex: number;
}

export interface ValidationIssue {
  severity: Severity;
  field: string;
  message: string;
}

export interface RunLog {
  id: string;
  time: string;
  module: string;
  status: StepStatus;
  message: string;
  severity?: Severity;
}

export interface SkuSuggestion {
  original: string;
  suggested: string;
  issues: ValidationIssue[];
}

export interface BasicInfoSuggestion {
  sourceTitle: string;
  optimizedTitle: string;
  titleIssues: ValidationIssue[];
  categoryPreset: CategoryPreset | null;
  currentCategoryPath: string;
  categoryConfidence: number;
  categoryReason: string;
  categoryMismatch: boolean;
  skuSuggestions: SkuSuggestion[];
  riskyTerms: string[];
  notes: string[];
}
