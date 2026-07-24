import type {
  BasicInfoWritePayload,
  BasicInfoWriteResult,
  BrowserConnection,
  CategoryWritePayload,
  CategoryWriteResult,
  DropdownOptionsScanResult,
  ListScanResult,
  PageScanResult
} from "./automation/contracts";

declare global {
  interface Window {
    dxmAssistant?: {
      platform: string;
      version: string;
      getChromeStatus: () => Promise<BrowserConnection & { browser?: string; error?: string }>;
      launchDebugChrome: () => Promise<BrowserConnection & { browser?: string; error?: string }>;
      scanProductList: () => Promise<ListScanResult>;
      openTaskEditor: (rowIndex: number) => Promise<{ ok: boolean; text: string; url?: string; editPageReady?: boolean }>;
      scanEditPage: () => Promise<PageScanResult>;
      writeBasicInfo: (payload: BasicInfoWritePayload) => Promise<BasicInfoWriteResult>;
      writeCategory: (payload: CategoryWritePayload) => Promise<CategoryWriteResult>;
      scanDropdownOptions: () => Promise<DropdownOptionsScanResult>;
      diagnoseCategory: () => Promise<any>;
      diagnoseAttrTemplate: () => Promise<any>;
      writeDropdownOption: (fieldKey: string, value: string) => Promise<{ ok: boolean; fieldKey: string; written: boolean; selectedValue?: string; reason?: string; visibleOptions?: string[] }>;
      downloadImages: () => Promise<{ ok: boolean; dir: string; images: Array<{ index: number; url: string; file: string; size?: number; error?: string }> }>;
      uploadImage: (filePath: string) => Promise<{ ok: boolean; file: string }>;
      processImage: (params: { imagePath: string; apiUrl: string; apiKey: string; prompt?: string; size?: string; model?: string }) => Promise<{ ok: boolean; resultPath?: string; revisedPrompt?: string }>;
      generateMarketingImages: () => Promise<{ ok: boolean; reason?: string }>;
      fillSkuBatch: (params: { priceMultiplier: number; declaredValueMultiplier?: number; stock?: number; weight?: number; length?: number; width?: number; height?: number }) => Promise<{ ok: boolean; filled: any; originalPrice: number }>;
      setOriginalBox: () => Promise<{ ok: boolean; setCount: number }>;
      setLogisticsAttribute: () => Promise<{ ok: boolean; reason?: string }>;
      writeRegionalPricing: (value: string) => Promise<{ ok: boolean; allTexts?: string[] }>;
      generateWirelessDesc: () => Promise<{ ok: boolean; wasChecked: boolean; genClicked: boolean }>;
      fillPackaging: (params: { weight?: number; length?: number; width?: number; height?: number }) => Promise<{ ok: boolean; filled: any }>;
      scanCustomsLevels: () => Promise<{ ok: boolean; reason?: string; customs?: Array<{ index: number; levels: Array<{ level: number; items: string[] }> }> }>;
      writeCustoms: (pathArray: string[]) => Promise<{ ok: boolean; results: Array<{ index: number; selected: string[] }> }>;
    };
  }
}

export {};
