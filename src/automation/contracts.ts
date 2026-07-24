import type { CategoryPreset, ImageRule, PricingRule, ProductSnapshot, ProductTask, RunLog, ValidationIssue } from "../types";

export interface BrowserConnection {
  port: number;
  status: "disconnected" | "connected" | "blocked";
  activeUrl?: string;
}

export interface PageScanResult {
  product: ProductSnapshot;
  modules: string[];
  visibleButtons: string[];
  dropdowns: Array<{
    module: string;
    label: string;
    currentValue: string;
    optionCount?: number;
  }>;
  redTextErrors: ValidationIssue[];
  scanDebug?: {
    scannerVersion: string;
    url: string;
    productCardFound: boolean;
    productImageCandidates: number;
    mainImageCandidates: number;
    productInputCount: number;
    skuCandidates: number;
  };
}

export interface ListScanResult {
  url: string;
  title: string;
  tasks: ProductTask[];
  visibleButtons: string[];
  totalRows: number;
}

export interface BasicInfoWritePayload {
  optimizedTitle: string;
  categoryPath: string;
  skuNames: Array<{
    original: string;
    suggested: string;
  }>;
}

export interface BasicInfoWriteResult {
  ok: boolean;
  titleWritten: boolean;
  skuWritten: number;
  skuTotal: number;
  skipped: string[];
  warnings: string[];
  url: string;
}

export interface CategoryWritePayload {
  categoryPath: string;
}

export interface CategoryWriteResult {
  ok: boolean;
  attemptedPath: string[];
  selectedPath: string[];
  currentValue: string;
  warnings: string[];
  url: string;
  attributeTemplateOptions?: string[];
}

export interface DropdownOptionGroup {
  fieldKey:
    | "category"
    | "attributeTemplate"
    | "freightTemplate"
    | "serviceTemplate"
    | "euResponsible"
    | "brandManufacturer"
    | "unknown";
  module: string;
  label: string;
  currentValue: string;
  options: string[];
}

export interface DropdownOptionsScanResult {
  url: string;
  groups: DropdownOptionGroup[];
  warnings: string[];
  _debug?: {
    totalControls: number;
    scanned: number;
    skipped: Array<{
      label: string;
      module: string;
      fieldKey: string;
    }>;
  };
}

export interface ProcessingPlan {
  categoryPreset: CategoryPreset;
  pricingRule: PricingRule;
  imageRule: ImageRule;
  translationMode: "global_then_restore_title" | "field_level_only";
  publishMode: "move_to_wait_publish" | "publish_now";
}

export interface AutomationResult {
  productId: string;
  success: boolean;
  logs: RunLog[];
  validationIssues: ValidationIssue[];
  screenshots: string[];
}

export interface AutomationAdapter {
  connect(): Promise<BrowserConnection>;
  scanCurrentEditPage(): Promise<PageScanResult>;
  runPlan(plan: ProcessingPlan): Promise<AutomationResult>;
}
