import {
  AlertTriangle,
  Bot,
  Camera,
  CheckCircle2,
  ChevronRight,
  Circle,
  ClipboardCheck,
  FileText,
  ImagePlus,
  Languages,
  ListChecks,
  PackageCheck,
  Play,
  Rows3,
  RefreshCw,
  Save,
  Search,
  Settings,
  ShieldCheck,
  Truck,
  WandSparkles,
  XCircle
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import type { BrowserConnection, DropdownOptionGroup, ListScanResult, PageScanResult } from "./automation/contracts";
import { categoryPresets, imageRules, initialLogs, pricingRules, sampleProduct, workflowSteps } from "./data";
import { suggestBasicInfo } from "./lib/basicInfo";
import { validateProduct } from "./lib/validators";
import type {
  BasicInfoSuggestion,
  CategoryPreset,
  ProductSnapshot,
  ProductTask,
  RunLog,
  StepStatus,
  ValidationIssue,
  WorkflowStep
} from "./types";

const CUSTOM_PRESETS_KEY = "dxm.customCategoryPresets.v1";
const LOCKED_PRESET_KEY = "dxm.lockedCategoryPresetId.v1";
type DropdownFieldKey = DropdownOptionGroup["fieldKey"];

const statusLabel: Record<StepStatus, string> = {
  pending: "待处理",
  ready: "已就绪",
  running: "运行中",
  success: "成功",
  warning: "需确认",
  failed: "失败"
};

const statusIcon: Record<StepStatus, ReactNode> = {
  pending: <Circle size={16} />,
  ready: <ClipboardCheck size={16} />,
  running: <RefreshCw size={16} />,
  success: <CheckCircle2 size={16} />,
  warning: <AlertTriangle size={16} />,
  failed: <XCircle size={16} />
};

const moduleIcons: Record<string, ReactNode> = {
  basicInfo: <Search size={18} />,
  dxmInfo: <FileText size={18} />,
  attributeInfo: <ListChecks size={18} />,
  productInfo: <ImagePlus size={18} />,
  regionalPricing: <Truck size={18} />,
  descriptionInfo: <Languages size={18} />,
  packageInfo: <PackageCheck size={18} />,
  templateInfo: <Settings size={18} />,
  otherInfo: <ShieldCheck size={18} />,
  translationCheck: <Bot size={18} />,
  publish: <Save size={18} />
};

function StatusPill({ status }: { status: StepStatus }) {
  return (
    <span className={`status-pill ${status}`}>
      {statusIcon[status]}
      {statusLabel[status]}
    </span>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "good" | "warn" | "bad" }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StepCard({ step, index }: { step: WorkflowStep; index: number }) {
  return (
    <article className="step-card">
      <div className="step-card-head">
        <div className="step-title">
          <span className="step-index">{String(index + 1).padStart(2, "0")}</span>
          <span className="step-icon">{moduleIcons[step.key]}</span>
          <h3>{step.title}</h3>
        </div>
        <StatusPill status={step.status} />
      </div>
      <p>{step.summary}</p>
      <div className="step-columns">
        <div>
          <span className="subhead">验收检查</span>
          {step.checks.slice(0, 3).map((check) => (
            <div className="tiny-row" key={check}>
              <CheckCircle2 size={14} />
              {check}
            </div>
          ))}
        </div>
        <div>
          <span className="subhead">自动化要点</span>
          {step.automationNotes.slice(0, 2).map((note) => (
            <div className="tiny-row muted" key={note}>
              <ChevronRight size={14} />
              {note}
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function ProductPreview({ product, scanned }: { product: ProductSnapshot; scanned: boolean }) {
  const previewImages = product.mainImages.length ? product.mainImages.slice(0, 6) : sampleProduct.mainImages;

  return (
    <section className="panel product-panel">
      <div className="panel-head">
        <div>
          <h2>当前商品</h2>
          <p>{scanned ? "从店小秘编辑页读取的真实商品快照" : "等待扫描店小秘编辑页"}</p>
        </div>
        <StatusPill status={scanned ? "success" : "warning" } />
      </div>
      <div className="product-grid">
        <div className="gallery">
          {previewImages.map((src, index) => (
            <div className="image-tile" key={src}>
              <img src={src} alt={`main ${index + 1}`} />
              <span>主图 {index + 1}</span>
            </div>
          ))}
        </div>
        <div className="product-copy">
          <label>商品 ID</label>
          <p>{product.productId || "未扫描"}</p>
          <label>原始标题</label>
          <p className="original-title">{product.originalTitle || "未扫描"}</p>
          <label>优化英文标题</label>
          <p className="optimized-title">{product.optimizedTitle || "待生成"}</p>
          <label>当前/推荐类目</label>
          <p>{product.categoryPath || "未扫描"}</p>
          <label>来源 URL</label>
          <p>{product.sourceUrl || "未扫描"}</p>
          <label>SKU 名称</label>
          <div className="sku-list">
            {(product.skuNames.length ? product.skuNames : ["未扫描"]).slice(0, 12).map((name) => (
              <span key={name}>{name}</span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function DropdownWorkflow({
  groups,
  selectedValues,
  onSelect,
  onWrite
}: {
  groups: DropdownOptionGroup[];
  selectedValues: Record<string, string>;
  onSelect: (fieldKey: string, value: string) => void;
  onWrite: (fieldKey: string, value: string) => void;
}) {
  const fieldMeta: Record<string, { title: string; icon: string; dependsOn?: string; module: string; draftField: string }> = {
    category: { title: "产品类目", icon: "📂", module: "基本信息", draftField: "path" },
    attributeTemplate: { title: "引用模板（属性模板）", icon: "📋", dependsOn: "类目选择后显示", module: "属性信息", draftField: "attributeTemplate" },
    freightTemplate: { title: "运费模板", icon: "🚚", module: "模板信息", draftField: "freightTemplate" },
    serviceTemplate: { title: "服务模板", icon: "⚙️", module: "模板信息", draftField: "serviceTemplate" },
    euResponsible: { title: "欧盟责任人", icon: "🇪🇺", module: "其他信息", draftField: "euResponsible" },
    brandManufacturer: { title: "品牌制造商", icon: "🏭", module: "其他信息", draftField: "brandManufacturer" },
    unknown: { title: "其他下拉框", icon: "❓", module: "", draftField: "" }
  };

  // Group by fieldKey
  const grouped = new Map<string, DropdownOptionGroup[]>();
  for (const g of groups) {
    const key = g.fieldKey;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(g);
  }

  // Priority order
  const order = ["category", "attributeTemplate", "freightTemplate", "serviceTemplate", "euResponsible", "brandManufacturer", "unknown"];

  return (
    <div className="dropdown-workflow">
      <strong>已拉取的下拉框选项（点击即可选择）</strong>
      {order.map((key) => {
        const items = grouped.get(key);
        if (!items || !items.length) return null;
        const meta = fieldMeta[key] || fieldMeta.unknown;
        const allOptions = Array.from(new Set(items.flatMap((g) => g.options)));
        const selected = selectedValues[key] || "";

        return (
          <div className={`dw-group dw-${key}`} key={key}>
            <div className="dw-group-head">
              <span className="dw-icon">{meta.icon}</span>
              <div>
                <strong>
                  {meta.title}
                  {selected ? <span className="dw-selected-label"> → 已选：{selected.slice(0, 50)}</span> : null}
                </strong>
                {selected && key !== "category" ? (
                  <button className="mini-button dw-write-btn" onClick={() => onWrite(key, selected)} title="写入页面">
                    写入
                  </button>
                ) : null}
                <small>
                  {meta.module} · {allOptions.length} 个选项
                  {meta.dependsOn ? <span className="dw-depends"> ⚠ 依赖：{meta.dependsOn}</span> : null}
                  {allOptions.length === 1 ? <span className="dw-auto"> ✓ 唯一选项，可自动选择</span> : null}
                </small>
              </div>
            </div>
            <div className="dw-options">
              {allOptions.slice(0, 30).map((opt) => {
                const isActive = selected === opt;
                return (
                  <span
                    className={`dw-option-chip${isActive ? " active" : ""}`}
                    key={opt}
                    title={opt}
                    onClick={() => onSelect(key, opt)}
                  >
                    {isActive ? "✓ " : ""}{opt}
                  </span>
                );
              })}
              {allOptions.length > 30 ? <span className="dw-more">+{allOptions.length - 30} 更多</span> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConfigPanel({
  presets,
  lockedPresetId,
  onLockPreset,
  onSavePreset,
  dropdownGroups,
  onScanDropdowns,
  isScanningDropdowns,
  onWriteDropdown,
  onProcessProduct,
  isProcessingProduct
}: {
  presets: CategoryPreset[];
  lockedPresetId: string;
  onLockPreset: (presetId: string) => void;
  onSavePreset: (preset: CategoryPreset) => void;
  dropdownGroups: DropdownOptionGroup[];
  onScanDropdowns: () => void;
  isScanningDropdowns: boolean;
  onWriteDropdown: (fieldKey: string, value: string) => void;
  onProcessProduct: () => void;
  isProcessingProduct: boolean;
}) {
  const activePreset = presets.find((preset) => preset.id === lockedPresetId) ?? null;
  const [draft, setDraft] = useState<CategoryPreset>(() => ({
    id: `custom-${Date.now()}`,
    name: "",
    path: "",
    attributeTemplate: "",
    freightTemplate: "普货小包-标准",
    serviceTemplate: "默认服务模板",
    customsMode: "manual_review",
    customsDefaults: []
  }));

  useEffect(() => {
    if (activePreset) {
      setDraft(activePreset);
    }
  }, [activePreset]);

  // Separate state for template values that aren't in CategoryPreset
  const [euResp, setEuResp] = useState("");
  const [brandMfr, setBrandMfr] = useState("");

  const updateDraft = (
    field: "name" | "path" | "attributeTemplate" | "freightTemplate" | "serviceTemplate",
    value: string
  ) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };

  const getTemplateValue = (fieldKey: string) => {
    switch (fieldKey) {
      case "category": return draft.path;
      case "attributeTemplate": return draft.attributeTemplate;
      case "freightTemplate": return draft.freightTemplate;
      case "serviceTemplate": return draft.serviceTemplate;
      case "euResponsible": return euResp;
      case "brandManufacturer": return brandMfr;
      default: return "";
    }
  };

  const setTemplateValue = (fieldKey: string, value: string) => {
    localStorage.setItem("dxm." + fieldKey, value);
    switch (fieldKey) {
      case "category": updateDraft("path", value); break;
      case "attributeTemplate": updateDraft("attributeTemplate", value); break;
      case "freightTemplate": updateDraft("freightTemplate", value); break;
      case "serviceTemplate": updateDraft("serviceTemplate", value); break;
      case "euResponsible": setEuResp(value); break;
      case "brandManufacturer": setBrandMfr(value); break;
    }
  };

  const saveDraft = () => {
    const name = draft.name.trim();
    const path = draft.path.trim();
    if (!name || !path) {
      return;
    }
    const id = draft.id.startsWith("custom-") ? draft.id : `custom-${Date.now()}`;
    onSavePreset({
      ...draft,
      id,
      name,
      path,
      attributeTemplate: draft.attributeTemplate.trim(),
      freightTemplate: draft.freightTemplate.trim() || "普货小包-标准",
      serviceTemplate: draft.serviceTemplate.trim() || "默认服务模板"
    });
    onLockPreset(id);
  };

  // Compute available options for each field from dropdownGroups
  const fieldOptions = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const key of ["category","attributeTemplate","freightTemplate","serviceTemplate","euResponsible","brandManufacturer"]) {
      map[key] = Array.from(new Set(
        dropdownGroups.filter(g => g.fieldKey === key).flatMap(g => g.options)
      )).filter(isUsefulDropdownValue).slice(0, 60);
    }
    return map;
  }, [dropdownGroups]);

  const renderTemplateRow = (label: string, fieldKey: string) => {
    const val = getTemplateValue(fieldKey);
    const opts = fieldOptions[fieldKey] || [];
    const canWrite = Boolean(val);
    return (
      <div className="template-row" key={fieldKey}>
        <label>{label}</label>
        <div className="template-row-controls">
          {opts.length ? (
            <select className="option-picker" value={val} onChange={e => setTemplateValue(fieldKey, e.target.value)}>
              <option value="">{val || "选择..."}</option>
              {opts.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <input value={val} onChange={e => setTemplateValue(fieldKey, e.target.value)} placeholder="先拉取下拉框获取选项" />
          )}
          {canWrite && fieldKey !== "category" ? (
            <button className="mini-button" onClick={() => onWriteDropdown(fieldKey, val)} title={"写入 " + label}>写入</button>
          ) : null}
        </div>
      </div>
    );
  };

  return (
    <section className="panel config-panel">
      <div className="panel-head">
        <div><h2>预设配置</h2><p>选择类目和模板后写入页面</p></div>
        <button className="secondary-button" onClick={onScanDropdowns} disabled={isScanningDropdowns} style={{fontSize:12}}>
          <RefreshCw size={14} />{isScanningDropdowns ? "拉取中" : "拉取下拉框"}
        </button>
        <button className="secondary-button" onClick={async () => {
          if (!window.dxmAssistant) return;
          const d = await window.dxmAssistant.diagnoseAttrTemplate();
          console.log("=== 引用模板诊断 ===", JSON.stringify(d, null, 2));
          alert("诊断已输出到 F12 控制台");
        }} style={{fontSize:11}}>🔍诊引用模板</button>
      </div>

      {/* Category */}
      <div className="template-section">
        <div className="template-section-title">📂 产品类目</div>
        <div className="preset-lock-box">
          <select value={lockedPresetId} onChange={(event) => onLockPreset(event.target.value)} style={{marginBottom:6}}>
            <option value="">自动识别</option>
            {presets.map((preset) => <option value={preset.id} key={preset.id}>{preset.name}</option>)}
          </select>
          {renderTemplateRow("类目路径", "category")}
          {activePreset ? <p style={{margin:"6px 0 0",fontSize:12,color:"#657486"}}>已锁定：{activePreset.path}</p> : null}
        </div>
      </div>

      {/* Templates */}
      <div className="template-section">
        <div className="template-section-title">📋 模板配置 <small style={{color:"#d99525",fontSize:11}}>（先写入类目，再拉取下拉框，然后选择和写入）</small></div>
        <div className="template-grid">
          {renderTemplateRow("引用模板", "attributeTemplate")}
          {renderTemplateRow("运费模板", "freightTemplate")}
          {renderTemplateRow("服务模板", "serviceTemplate")}
          {fieldOptions.euResponsible.length ? renderTemplateRow("欧盟责任人", "euResponsible") : null}
          {fieldOptions.brandManufacturer.length ? renderTemplateRow("品牌制造商", "brandManufacturer") : null}
          <div className="template-row">
            <label>区域调价模板</label>
            <div className="template-row-controls">
              <input id="rpTemplate" defaultValue={localStorage.getItem("dxm.rpTemplate")||""} placeholder="模板名" onChange={e => localStorage.setItem("dxm.rpTemplate", e.target.value)} />
            </div>
          </div>
        </div>
      </div>

      {/* Customs Preset */}
      <div className="template-section" style={{marginTop:12}}>
        <div className="template-section-title">🔍 海关监管预设 <small style={{fontSize:11,color:"#6d7885"}}>（扫描后选择路径保存）</small></div>
        <button className="secondary-button" onClick={async () => {
          if (!window.dxmAssistant) return;
          const result = await window.dxmAssistant.scanCustomsLevels();
          console.log("海关扫描:", JSON.stringify(result, null, 2));
          if (result.ok) {
            const paths = JSON.stringify(result.customs);
            localStorage.setItem("dxm.customsScan", paths);
            alert("扫描完成！已在控制台输出，请 F12 查看各级选项，然后填入下方路径");
          } else {
            alert("扫描失败: " + (result.reason || "未知"));
          }
        }} style={{marginBottom:4}}>🔍 扫描海关级联</button>
        <div className="template-row">
          <label>预设路径</label>
          <div className="template-row-controls">
            <input defaultValue={localStorage.getItem("dxm.customsPath")||""} placeholder="例: 普通商品,塑料/TPU" onChange={e => localStorage.setItem("dxm.customsPath", e.target.value)} />
          </div>
        </div>
      </div>

      {/* Save */}
      <button className="secondary-button" onClick={saveDraft} disabled={!draft.name.trim() || !draft.path.trim()} style={{marginTop:12}}>
        <Save size={17} />保存预设
      </button>

      {/* AI Image Config */}
      <div className="template-section" style={{marginTop:12}}>
        <div className="template-section-title">🎨 AI 图片处理</div>
        <div className="template-grid">
          <div className="template-row">
            <label>API 端点</label>
            <input style={{flex:1}} placeholder="https://your-api.com/v1/images" defaultValue={localStorage.getItem("dxm.aiApiUrl") || ""} onChange={e => localStorage.setItem("dxm.aiApiUrl", e.target.value)} />
          </div>
          <div className="template-row">
            <label>API Key</label>
            <input style={{flex:1}} type="password" placeholder="sk-..." defaultValue={localStorage.getItem("dxm.aiApiKey") || ""} onChange={e => localStorage.setItem("dxm.aiApiKey", e.target.value)} />
          </div>
          <div className="template-row">
            <label>尺寸</label>
            <select style={{flex:1}} defaultValue={localStorage.getItem("dxm.aiSize") || "800x800"} onChange={e => localStorage.setItem("dxm.aiSize", e.target.value)}>
              <option value="800x800">800×800 (1:1 主图)</option>
              <option value="1024x1024">1024×1024 (1:1)</option>
              <option value="1536x1024">1536×1024 (3:2)</option>
              <option value="1920x1080">1920×1080 (16:9)</option>
            </select>
          </div>
          <div className="template-row">
            <label>提示词</label>
            <textarea style={{flex:1, minHeight:50}} placeholder={imageRules[0].backgroundPrompt} defaultValue={localStorage.getItem("dxm.aiPrompt") || ""} onChange={e => localStorage.setItem("dxm.aiPrompt", e.target.value)} rows={2} />
          </div>
        </div>
        <p style={{fontSize:11, color:"#6d7885", margin:"6px 0 0"}}>
          下载图片后将按以上配置发送到 AI API 处理。提示词留空则使用默认："{imageRules[0].backgroundPrompt.substring(0, 60)}..."
        </p>
      </div>

      {/* Pricing & SKU Presets */}
      <div className="template-section" style={{marginTop:12}}>
        <div className="template-section-title">💰 SKU 批量预设</div>
        <PricingPresets onProcessProduct={onProcessProduct} isProcessing={isProcessingProduct} />
      </div>
    </section>
  );
}

function PricingPresets({ onProcessProduct, isProcessing }: { onProcessProduct: () => void; isProcessing: boolean }) {
  const [multiplier, setMultiplier] = useState(() => parseFloat(localStorage.getItem("dxm.priceMultiplier") || "5"));
  const [dvMultiplier, setDvMultiplier] = useState(() => parseFloat(localStorage.getItem("dxm.dvMultiplier") || "0.35"));
  const [stock, setStock] = useState(() => parseInt(localStorage.getItem("dxm.stock") || "100"));
  const [weight, setWeight] = useState(() => parseFloat(localStorage.getItem("dxm.weight") || "0.12"));
  const [pkgL, setPkgL] = useState(() => parseInt(localStorage.getItem("dxm.pkgL") || "15"));
  const [pkgW, setPkgW] = useState(() => parseInt(localStorage.getItem("dxm.pkgW") || "12"));
  const [pkgH, setPkgH] = useState(() => parseInt(localStorage.getItem("dxm.pkgH") || "4"));

  const save = (key: string, val: string | number) => localStorage.setItem("dxm." + key, String(val));

  return (
    <div>
      <div className="template-grid">
        <div className="template-row">
          <label>售价倍率</label>
          <input type="number" step="0.1" value={multiplier} onChange={e => { setMultiplier(parseFloat(e.target.value)); save("priceMultiplier", e.target.value); }} />
          <span style={{fontSize:11,color:"#6d7885"}}>采集价 × 倍率 = 零售价</span>
        </div>
        <div className="template-row">
          <label>货值倍率</label>
          <input type="number" step="0.01" value={dvMultiplier} onChange={e => { setDvMultiplier(parseFloat(e.target.value)); save("dvMultiplier", e.target.value); }} />
        </div>
        <div className="template-row">
          <label>库存</label>
          <input type="number" value={stock} onChange={e => { setStock(parseInt(e.target.value)); save("stock", e.target.value); }} />
        </div>
        <div className="template-row">
          <label>重量(kg)</label>
          <input type="number" step="0.01" value={weight} onChange={e => { setWeight(parseFloat(e.target.value)); save("weight", e.target.value); }} />
        </div>
        <div className="template-row">
          <label>尺寸(cm)</label>
          <div style={{display:"flex",gap:4}}>
            <input type="number" value={pkgL} placeholder="长" style={{width:60}} onChange={e => { setPkgL(parseInt(e.target.value)); save("pkgL", e.target.value); }} />
            <input type="number" value={pkgW} placeholder="宽" style={{width:60}} onChange={e => { setPkgW(parseInt(e.target.value)); save("pkgW", e.target.value); }} />
            <input type="number" value={pkgH} placeholder="高" style={{width:60}} onChange={e => { setPkgH(parseInt(e.target.value)); save("pkgH", e.target.value); }} />
          </div>
        </div>
      </div>
      <button className="primary-button" onClick={onProcessProduct} disabled={isProcessing} style={{marginTop:8, width:"100%"}}>
        <Play size={16} />
        {isProcessing ? "处理中" : "执行产品信息填充"}
      </button>
    </div>
  );
}

function isUsefulDropdownValue(value: string) {
  return Boolean(value) && !/^cn\d+[a-z0-9]*$/i.test(value) && value !== "从页面选项填入";
}

function OptionPicker({
  groups,
  fieldKey,
  onPick
}: {
  groups: DropdownOptionGroup[];
  fieldKey: DropdownFieldKey;
  onPick: (value: string) => void;
}) {
  const options = useMemo(() => {
    const values = groups
      .filter((group) => group.fieldKey === fieldKey)
      .flatMap((group) => group.options.length ? group.options : [group.currentValue])
      .filter(isUsefulDropdownValue);
    return Array.from(new Set(values)).slice(0, 80);
  }, [groups, fieldKey]);

  if (!options.length) {
    return null;
  }

  return (
    <select className="option-picker" defaultValue="" onChange={(event) => event.target.value && onPick(event.target.value)}>
      <option value="">从页面选项填入</option>
      {options.map((option) => (
        <option value={option} key={option}>
          {option}
        </option>
      ))}
    </select>
  );
}

function FieldOptionList({
  title,
  groups,
  fieldKey
}: {
  title: string;
  groups: DropdownOptionGroup[];
  fieldKey: DropdownFieldKey;
}) {
  const options = useMemo(() => {
    const values = groups
      .filter((group) => group.fieldKey === fieldKey)
      .flatMap((group) => group.options.length ? group.options : [group.currentValue])
      .filter(isUsefulDropdownValue);
    return Array.from(new Set(values)).slice(0, 30);
  }, [groups, fieldKey]);

  if (!options.length) {
    return null;
  }

  return (
    <div className="field-option-list">
      <span>
        {title}
        {options.length === 1 ? <small>唯一选项，后续可默认自动选择</small> : null}
      </span>
      <div>
        {options.map((option) => (
          <em key={option}>{option}</em>
        ))}
      </div>
    </div>
  );
}

function DropdownOptionsPanel({ groups }: { groups: DropdownOptionGroup[] }) {
  return (
    <div className="dropdown-options-panel">
      <strong>已拉取页面下拉框</strong>
      {groups.slice(0, 16).map((group, index) => (
        <div className="dropdown-option-group" key={`${group.module}-${group.label}-${index}`}>
          <span>
            {group.fieldKey} / {group.module || "未识别模块"} / {group.label || "未识别字段"}
          </span>
          <small>当前：{group.currentValue || "空"}，选项 {group.options.length} 个</small>
          {group.options.length ? (
            <div className="dropdown-option-list">
              {group.options.slice(0, 12).map((option) => (
                <em key={option}>{option}</em>
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function TaskQueuePanel({
  listResult,
  onOpenTask
}: {
  listResult: ListScanResult | null;
  onOpenTask: (task: ProductTask) => void;
}) {
  const tasks = listResult?.tasks ?? [];

  return (
    <section className="panel task-panel">
      <div className="panel-head">
        <div>
          <h2>任务队列</h2>
          <p>{listResult ? `来自：${listResult.title || listResult.url}` : "先扫描采集箱/草稿列表页"}</p>
        </div>
        <StatusPill status={tasks.length ? "success" : "pending"} />
      </div>
      <div className="task-list">
        {tasks.length ? (
          tasks.slice(0, 12).map((task) => (
            <TaskRow task={task} key={`${task.id}-${task.rowIndex}`} onOpenTask={onOpenTask} />
          ))
        ) : (
          <div className="empty-state">暂无任务。打开店小秘采集箱或草稿列表后点击“扫描列表”。</div>
        )}
      </div>
    </section>
  );
}

function TaskRow({ task, onOpenTask }: { task: ProductTask; onOpenTask: (task: ProductTask) => void }) {
  return (
    <div className="task-row">
      <div className="task-thumb">
        {task.imageUrl ? <img src={task.imageUrl} alt="" /> : <Rows3 size={18} />}
      </div>
      <div className="task-copy">
        <strong>{task.title}</strong>
        <span>
          {task.status || "未知状态"} {task.source ? ` / ${task.source}` : ""} {task.editText ? ` / ${task.editText}` : ""}
        </span>
      </div>
      <button className="mini-button" onClick={() => onOpenTask(task)}>
        打开编辑
      </button>
    </div>
  );
}

function BasicInfoPanel({
  product,
  suggestion,
  onGenerate,
  onApply,
  onWrite,
  onWriteCategory,
  isWriting
}: {
  product: ProductSnapshot;
  suggestion: BasicInfoSuggestion | null;
  onGenerate: () => void;
  onApply: () => void;
  onWrite: () => void;
  onWriteCategory: () => void;
  isWriting: boolean;
}) {
  const hasProduct = Boolean(product.originalTitle || product.skuNames.length);
  const skuIssueCount = suggestion?.skuSuggestions.reduce((count, sku) => count + sku.issues.length, 0) ?? 0;
  const status: StepStatus = !suggestion ? "pending" : suggestion.categoryMismatch || suggestion.titleIssues.length || skuIssueCount ? "warning" : "success";

  return (
    <section className="panel basic-info-panel">
      <div className="panel-head">
        <div>
          <h2>基本信息建议</h2>
          <p>先生成类目、英文标题和 SKU 名称建议，确认后再进入页面写入</p>
        </div>
        <StatusPill status={status} />
      </div>

      <div className="basic-actions">
        <button className="primary-button" onClick={onGenerate} disabled={!hasProduct}>
          <WandSparkles size={17} />
          生成建议
        </button>
        <button className="secondary-button" onClick={onApply} disabled={!suggestion}>
          <CheckCircle2 size={17} />
          应用到预览
        </button>
        <button className="secondary-button" onClick={onWrite} disabled={!suggestion || isWriting}>
          <Save size={17} />
          {isWriting ? "写入中" : "写入店小秘测试"}
        </button>
        <button className="secondary-button" onClick={onWriteCategory} disabled={!suggestion || isWriting || !suggestion.categoryPreset}>
          <Search size={17} />
          写入类目测试
        </button>
      </div>

      {suggestion ? (
        <>
          <div className="recommend-block">
            <label>推荐类目</label>
            <strong>{suggestion.categoryPreset?.name ?? "未识别"}</strong>
            <p>{suggestion.categoryPreset?.path ?? "需要人工选择类目"}</p>
            <div className="confidence-row">
              <span>置信度 {suggestion.categoryConfidence}%</span>
              <span className={suggestion.categoryMismatch ? "tag warn" : "tag good"}>
                {suggestion.categoryMismatch ? "当前类目疑似冲突" : "类目无明显冲突"}
              </span>
            </div>
            <small>{suggestion.categoryReason}</small>
          </div>

          <div className="recommend-block">
            <label>优化英文标题</label>
            <p className="optimized-title">{suggestion.optimizedTitle}</p>
            {suggestion.riskyTerms.length ? (
              <div className="risk-line">
                <AlertTriangle size={14} />
                已识别适配搜索词，标题需使用 Compatible with/for 表达：{suggestion.riskyTerms.join(", ")}
              </div>
            ) : null}
            {suggestion.titleIssues.map((issue) => (
              <div className="risk-line" key={`${issue.field}-${issue.message}`}>
                <AlertTriangle size={14} />
                {issue.message}
              </div>
            ))}
          </div>

          <div className="sku-suggestion-table">
            <div className="sku-suggestion-row header">
              <span>原 SKU</span>
              <span>建议英文名</span>
            </div>
            {suggestion.skuSuggestions.slice(0, 10).map((sku) => (
              <div className="sku-suggestion-row" key={`${sku.original}-${sku.suggested}`}>
                <span>{sku.original}</span>
                <span className={sku.issues.length ? "bad-text" : ""}>{sku.suggested}</span>
              </div>
            ))}
          </div>

          <div className="note-list">
            {suggestion.notes.map((note) => (
              <div className="tiny-row muted" key={note}>
                <ChevronRight size={14} />
                {note}
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state">扫描编辑页后点击“生成建议”，这里会显示类目判断、标题和 SKU 英文化结果。</div>
      )}
    </section>
  );
}

function ValidationPanel({
  product,
  scanResult,
  logs,
  onValidate
}: {
  product: ProductSnapshot;
  scanResult: PageScanResult | null;
  logs: RunLog[];
  onValidate: () => void;
}) {
  const grouped = useMemo(() => validateProduct(product), [product]);
  const blockingCount = grouped.filter((issue) => issue.severity === "P0" || issue.severity === "P1").length;

  return (
    <section className="panel validation-panel">
      <div className="panel-head">
        <div>
          <h2>校验与错误日志</h2>
          <p>发布前必须没有 P0/P1 阻断错误</p>
        </div>
        <button className="primary-button" onClick={onValidate}>
          <Play size={17} />
          运行校验
        </button>
      </div>
      <div className="metrics-grid">
        <Metric label="模块数" value={String(scanResult?.modules.length ?? 0)} tone={scanResult ? "good" : undefined} />
        <Metric label="主图数" value={String(product.mainImages.length)} tone={product.mainImages.length ? "good" : "warn"} />
        <Metric label="SKU 数" value={String(product.skuNames.length)} />
        <Metric label="P0/P1" value={String(blockingCount)} tone={blockingCount ? "bad" : "good"} />
      </div>
      <div className="issue-list">
        {grouped.map((issue) => (
          <IssueRow issue={issue} key={`${issue.field}-${issue.message}`} />
        ))}
      </div>
      <div className="log-list">
        {logs.map((log) => (
          <div className="log-row" key={log.id}>
            <span>{log.time}</span>
            <strong>{log.module}</strong>
            <StatusPill status={log.status} />
            <p>{log.message}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function IssueRow({ issue }: { issue: ValidationIssue }) {
  return (
    <div className={`issue-row ${issue.severity}`}>
      <strong>{issue.severity}</strong>
      <span>{issue.field}</span>
      <p>{issue.message}</p>
    </div>
  );
}

function loadCustomPresets() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CUSTOM_PRESETS_KEY) || "[]");
    return Array.isArray(parsed) ? (parsed as CategoryPreset[]) : [];
  } catch {
    return [];
  }
}

function mergePresets(base: CategoryPreset[], custom: CategoryPreset[]) {
  const map = new Map<string, CategoryPreset>();
  for (const preset of base) {
    map.set(preset.id, preset);
  }
  for (const preset of custom) {
    map.set(preset.id, preset);
  }
  return Array.from(map.values());
}

function App() {
  const [connection, setConnection] = useState<(BrowserConnection & { browser?: string; error?: string }) | null>(null);
  const [scanResult, setScanResult] = useState<PageScanResult | null>(null);
  const [listResult, setListResult] = useState<ListScanResult | null>(null);
  const [product, setProduct] = useState<ProductSnapshot>(sampleProduct);
  const [basicSuggestion, setBasicSuggestion] = useState<BasicInfoSuggestion | null>(null);
  const [customPresets, setCustomPresets] = useState<CategoryPreset[]>(loadCustomPresets);
  const [lockedPresetId, setLockedPresetId] = useState(() => localStorage.getItem(LOCKED_PRESET_KEY) || "");
  const [dropdownGroups, setDropdownGroups] = useState<DropdownOptionGroup[]>([]);
  const [logs, setLogs] = useState<RunLog[]>(initialLogs);
  const [isScanning, setIsScanning] = useState(false);
  const [isScanningList, setIsScanningList] = useState(false);
  const [isLaunchingChrome, setIsLaunchingChrome] = useState(false);
  const [isWritingBasic, setIsWritingBasic] = useState(false);
  const [isScanningDropdowns, setIsScanningDropdowns] = useState(false);
  const allCategoryPresets = useMemo(() => mergePresets(categoryPresets, customPresets), [customPresets]);

  const addLog = (module: string, status: StepStatus, message: string, severity?: RunLog["severity"]) => {
    const now = new Date();
    setLogs((current) => [
      {
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        time: now.toLocaleTimeString("zh-CN", { hour12: false }),
        module,
        status,
        message,
        severity
      },
      ...current
    ].slice(0, 30));
  };

  const refreshChromeStatus = async () => {
    if (!window.dxmAssistant) {
      setConnection({ port: 0, status: "blocked", error: "当前不是桌面应用环境" });
      return;
    }
    const status = await window.dxmAssistant.getChromeStatus();
    setConnection(status);
  };

  const scanCurrentPage = async () => {
    setIsScanning(true);
    try {
      await refreshChromeStatus();
      if (!window.dxmAssistant) {
        throw new Error("当前不是桌面应用环境");
      }
      const result = await window.dxmAssistant.scanEditPage();
      const scannedProduct = {
        ...result.product,
        optimizedTitle: result.product.optimizedTitle || result.product.originalTitle || sampleProduct.optimizedTitle
      };
      setScanResult(result);
      setProduct(scannedProduct);
      setBasicSuggestion(suggestBasicInfo(scannedProduct, allCategoryPresets, lockedPresetId));
      addLog(
        "页面扫描",
        "success",
        `读取到 ${result.modules.length} 个模块、${result.product.mainImages.length} 张主图、${result.product.skuNames.length} 个 SKU（${result.scanDebug?.scannerVersion ?? window.dxmAssistant.version}，候选图 ${result.scanDebug?.productImageCandidates ?? "-"}，候选SKU ${result.scanDebug?.skuCandidates ?? "-"}）`
      );
    } catch (error) {
      addLog("页面扫描", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally {
      setIsScanning(false);
    }
  };

  const scanProductList = async () => {
    setIsScanningList(true);
    try {
      await refreshChromeStatus();
      if (!window.dxmAssistant) {
        throw new Error("当前不是桌面应用环境");
      }
      const result = await window.dxmAssistant.scanProductList();
      setListResult(result);
      addLog("列表扫描", "success", `识别到 ${result.tasks.length} 个候选任务，原始行数 ${result.totalRows}`);
    } catch (error) {
      addLog("列表扫描", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally {
      setIsScanningList(false);
    }
  };

  const openTaskEditor = async (task: ProductTask) => {
    try {
      if (!window.dxmAssistant) {
        throw new Error("当前不是桌面应用环境");
      }
      const result = await window.dxmAssistant.openTaskEditor(task.rowIndex);
      addLog(
        "打开编辑",
        result.editPageReady ? "success" : "warning",
        result.editPageReady
          ? `编辑页内容已加载，开始扫描：${task.title.slice(0, 40)}`
          : `已点击编辑，但 20 秒内未检测到编辑页：${task.title.slice(0, 40)}`
      );
      if (result.editPageReady) {
        await scanCurrentPage();
      }
    } catch (error) {
      addLog("打开编辑", "failed", error instanceof Error ? error.message : String(error), "P1");
    }
  };

  const launchChrome = async () => {
    setIsLaunchingChrome(true);
    try {
      if (!window.dxmAssistant) {
        throw new Error("当前不是桌面应用环境");
      }
      const status = await window.dxmAssistant.launchDebugChrome();
      setConnection(status);
      addLog(
        "Chrome",
        status.status === "connected" ? "success" : "warning",
        status.status === "connected"
          ? `已启动调试 Chrome，端口 ${status.port}`
          : `Chrome 已启动但端口未连接：${status.error || "未知原因"}`
      );
    } catch (error) {
      addLog("Chrome", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally {
      setIsLaunchingChrome(false);
    }
  };

  const validateCurrentProduct = () => {
    const issues = validateProduct(product);
    addLog("校验", issues.some((issue) => issue.severity === "P0" || issue.severity === "P1") ? "warning" : "success", `发现 ${issues.length} 个校验问题`);
  };

  const generateBasicSuggestion = () => {
    const suggestion = suggestBasicInfo(product, allCategoryPresets, lockedPresetId);
    setBasicSuggestion(suggestion);
    addLog(
      "基本信息",
      suggestion.categoryMismatch || suggestion.titleIssues.length ? "warning" : "success",
      `已生成建议：${suggestion.categoryPreset?.name ?? "未识别类目"}，SKU ${suggestion.skuSuggestions.length} 个`
    );
  };

  const saveCategoryPreset = (preset: CategoryPreset) => {
    setCustomPresets((current) => {
      const next = current.filter((item) => item.id !== preset.id);
      return [...next, preset];
    });
    addLog("预设配置", "success", `已保存并锁定类目预设：${preset.name}`);
  };

  const applyBasicSuggestion = () => {
    if (!basicSuggestion) {
      return;
    }

    const previewIssues: ValidationIssue[] = [];
    if (basicSuggestion.categoryMismatch) {
      previewIssues.push({
        severity: "P1",
        field: "category",
        message: `页面当前类目与识别结果不一致：当前为 ${basicSuggestion.currentCategoryPath || "空"}，建议为 ${basicSuggestion.categoryPreset?.path ?? "未识别"}`
      });
    }
    if (basicSuggestion.riskyTerms.length) {
      previewIssues.push({
        severity: "P2",
        field: "title",
        message: `标题包含适配品牌/车型搜索词，请避免 Original/Genuine/Official 等授权暗示：${basicSuggestion.riskyTerms.join(", ")}`
      });
    }

    setProduct((current) => ({
      ...current,
      optimizedTitle: basicSuggestion.optimizedTitle,
      categoryPath: basicSuggestion.categoryPreset?.path ?? current.categoryPath,
      skuNames: basicSuggestion.skuSuggestions.map((sku) => sku.suggested),
      validationErrors: previewIssues
    }));
    addLog("基本信息", "success", "已把标题、类目和 SKU 建议应用到应用内预览，尚未写入店小秘页面");
  };

  const writeBasicInfoToDxm = async () => {
    if (!basicSuggestion) {
      return;
    }

    setIsWritingBasic(true);
    try {
      if (!window.dxmAssistant) {
        throw new Error("当前不是桌面应用环境");
      }
      const result = await window.dxmAssistant.writeBasicInfo({
        optimizedTitle: basicSuggestion.optimizedTitle,
        categoryPath: basicSuggestion.categoryPreset?.path ?? "",
        skuNames: basicSuggestion.skuSuggestions.map((sku) => ({
          original: sku.original,
          suggested: sku.suggested
        }))
      });
      addLog(
        "基本信息写入",
        result.ok ? (result.warnings.length ? "warning" : "success") : "failed",
        `标题${result.titleWritten ? "已写入" : "未写入"}，SKU ${result.skuWritten}/${result.skuTotal}。${[...result.skipped, ...result.warnings].join("；") || "请在店小秘页面确认字段变化"}`,
        result.ok ? undefined : "P1"
      );
      await scanCurrentPage();
    } catch (error) {
      addLog("基本信息写入", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally {
      setIsWritingBasic(false);
    }
  };

  const writeCategoryToDxm = async () => {
    if (!basicSuggestion?.categoryPreset) {
      return;
    }

    setIsWritingBasic(true);
    try {
      if (!window.dxmAssistant) {
        throw new Error("当前不是桌面应用环境");
      }
      const result = await window.dxmAssistant.writeCategory({
        categoryPath: basicSuggestion.categoryPreset.path
      });
      const attemptedPath = Array.isArray(result.attemptedPath) ? result.attemptedPath : [];
      const selectedPath = Array.isArray(result.selectedPath) ? result.selectedPath : [];
      const warnMsgs = Array.isArray(result.warnings) ? result.warnings : [];
      const rawDump = JSON.stringify(result).slice(0, 300);
      addLog(
        "类目写入",
        result.ok ? "success" : "warning",
        `尝试 ${attemptedPath.join(" > ") || "(空)"}；已选择 ${selectedPath.length}/${attemptedPath.length} 级。${warnMsgs.join("；") || "请在店小秘页面确认类目是否已变化"} [RAW: ${rawDump}]`,
        result.ok ? undefined : "P2"
      );
      if (result.ok) {
        // Merge auto-scanned attribute template options into dropdownGroups
        if (result.attributeTemplateOptions && result.attributeTemplateOptions.length) {
          setDropdownGroups((prev) => {
            const others = prev.filter((g) => g.fieldKey !== "attributeTemplate");
            return [
              ...others,
              {
                fieldKey: "attributeTemplate" as const,
                module: "属性信息",
                label: "引用模板（类目联动刷新）",
                currentValue: selectedPath[selectedPath.length - 1] || "",
                options: result.attributeTemplateOptions || []
              }
            ];
          });
          addLog("下拉框扫描", "success", `类目写入成功，已自动拉取 ${result.attributeTemplateOptions.length} 个属性模板选项`);
        } else {
          setDropdownGroups([]);
          addLog("下拉框扫描", "warning", "类目已变更，但未自动拉取到属性模板选项，请手动点击拉取页面下拉框");
        }
      }
      await scanCurrentPage();
    } catch (error) {
      addLog("类目写入", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally {
      setIsWritingBasic(false);
    }
  };

  const scanDropdownOptions = async () => {
    setIsScanningDropdowns(true);
    try {
      if (!window.dxmAssistant) {
        throw new Error("当前不是桌面应用环境");
      }
      const result = await window.dxmAssistant.scanDropdownOptions();
      setDropdownGroups(result.groups);
      // Show debug: what was found and skipped
      const debug = result._debug;
      const debugMsg = debug
        ? ` [调试: 共${debug.totalControls}个控件, 已扫描${debug.scanned}个, 跳过${debug.skipped?.length || 0}个: ${(debug.skipped || []).map((d) => d.label + '→' + d.fieldKey + '(' + d.module + ')').join(' | ')}]`
        : "";
      addLog(
        "下拉框扫描",
        "success",
        `已拉取 ${result.groups.length} 个下拉框，包含 ${result.groups.reduce((count, group) => count + group.options.length, 0)} 个选项${debugMsg}`
      );
    } catch (error) {
      addLog("下拉框扫描", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally {
      setIsScanningDropdowns(false);
    }
  };

  const writeDropdownOption = async (fieldKey: string, value: string) => {
    try {
      if (!window.dxmAssistant) throw new Error("当前不是桌面应用环境");
      const result = await window.dxmAssistant.writeDropdownOption(fieldKey, value);
      const extra = result.visibleOptions?.length ? ` 可见选项: ${result.visibleOptions.join(" | ")}` : "";
      addLog(
        "模板写入",
        result.ok ? "success" : "warning",
        `${fieldKey}: ${result.ok ? "已写入 " + (result.selectedValue || value) : "失败 - " + (result.reason || "未知")}${extra}`
      );
    } catch (error) {
      addLog("模板写入", "failed", `${fieldKey}: ${error instanceof Error ? error.message : String(error)}`, "P2");
    }
  };

  const [isDownloading, setIsDownloading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const downloadImages = async () => {
    setIsDownloading(true);
    try {
      if (!window.dxmAssistant) throw new Error("当前不是桌面应用环境");
      const result = await window.dxmAssistant.downloadImages();
      addLog("图片下载", result.ok ? "success" : "warning",
        `下载 ${result.images.filter(i=>!i.error).length}/${result.images.length} 张到 ${result.dir}`
      );
    } catch (error) {
      addLog("图片下载", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally { setIsDownloading(false); }
  };

  const uploadTestImage = async () => {
    setIsUploading(true);
    try {
      // First download, then upload the first image back
      if (!window.dxmAssistant) throw new Error("当前不是桌面应用环境");
      const dl = await window.dxmAssistant.downloadImages();
      const firstOk = dl.images.find(i => !i.error);
      if (!firstOk) throw new Error("没有成功下载的图片可上传");
      const ul = await window.dxmAssistant.uploadImage(firstOk.file);
      addLog("图片上传", ul.ok ? "success" : "warning", `上传 ${firstOk.file} -> ${ul.ok ? "成功" : "失败"}`);
    } catch (error) {
      addLog("图片上传", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally { setIsUploading(false); }
  };

  const [isProcessing, setIsProcessing] = useState(false);
  const [isProcessingProduct, setIsProcessingProduct] = useState(false);

  const processProduct = async () => {
    setIsProcessingProduct(true);
    try {
      if (!window.dxmAssistant) throw new Error("当前不是桌面应用环境");

      // Step 1: Generate marketing images
      addLog("产品信息", "running", "Step1: 点击一键生成营销图片...");
      const genResult = await window.dxmAssistant.generateMarketingImages();
      addLog("产品信息", genResult.ok ? "success" : "warning", "Step1: 营销图片 " + (genResult.ok ? "已触发" : genResult.reason || "失败"));

      // Step 2: Fill SKU batch values
      const multiplier = parseFloat(localStorage.getItem("dxm.priceMultiplier") || "5");
      const dvMultiplier = parseFloat(localStorage.getItem("dxm.dvMultiplier") || "0.35");
      const stock = parseInt(localStorage.getItem("dxm.stock") || "100");
      const weight = parseFloat(localStorage.getItem("dxm.weight") || "0.12");
      const pkgL = parseInt(localStorage.getItem("dxm.pkgL") || "15");
      const pkgW = parseInt(localStorage.getItem("dxm.pkgW") || "12");
      const pkgH = parseInt(localStorage.getItem("dxm.pkgH") || "4");

      addLog("产品信息", "running", `Step2: 填充SKU (倍率x${multiplier}, 库存${stock}, 重量${weight}kg, ${pkgL}x${pkgW}x${pkgH}cm)...`);
      const skuResult = await window.dxmAssistant.fillSkuBatch({ priceMultiplier: multiplier, declaredValueMultiplier: dvMultiplier, stock, weight, length: pkgL, width: pkgW, height: pkgH });
      addLog("产品信息", skuResult.ok ? "success" : "warning", `Step2: 原价${skuResult.originalPrice}, 批量填充${skuResult.ok ? "完成" : "失败"} ${JSON.stringify(skuResult.filled || {})}`);

      // Step 3: Set 是否原箱 to 是
      addLog("产品信息", "running", "Step3: 设置是否原箱=是...");
      const boxResult = await window.dxmAssistant.setOriginalBox();
      addLog("产品信息", boxResult.ok ? "success" : "warning", `Step3: 是否原箱 已设置${boxResult.setCount}个`);

      // Step 4: Set logistics attribute
      addLog("产品信息", "running", "Step4: 设置物流属性=普货...");
      const logisticsResult = await window.dxmAssistant.setLogisticsAttribute();
      addLog("产品信息", logisticsResult.ok ? "success" : "warning", `Step4: 物流属性 ${logisticsResult.ok ? "已设置" : logisticsResult.reason || "失败"}`);

      // Step 5: Regional pricing template
      const rpTemplate = localStorage.getItem("dxm.rpTemplate") || "";
      if (rpTemplate) {
        addLog("产品信息", "running", `Step5: 区域调价模板=${rpTemplate}...`);
        const rpResult = await window.dxmAssistant.writeRegionalPricing(rpTemplate);
        addLog("产品信息", rpResult.ok ? "success" : "warning", `Step5: 区域调价 ${rpResult.ok ? "已写入" : "失败"}`);
      } else {
        addLog("产品信息", "warning", "Step5: 跳过（未配置区域调价模板）");
      }

      // Step 6: Wireless description
      addLog("产品信息", "running", "Step6: 无线端描述一键生成...");
      const descResult = await window.dxmAssistant.generateWirelessDesc();
      addLog("产品信息", descResult.ok ? "success" : "warning", `Step6: 无线端描述 ${descResult.ok ? "已触发" : "失败"}`);

      // Step 7: Packaging
      const pkgWt = parseFloat(localStorage.getItem("dxm.weight") || "0.12");
      const pkgLen = parseInt(localStorage.getItem("dxm.pkgL") || "15");
      const pkgWid = parseInt(localStorage.getItem("dxm.pkgW") || "12");
      const pkgHei = parseInt(localStorage.getItem("dxm.pkgH") || "4");
      addLog("产品信息", "running", `Step7: 包装信息 ${pkgWt}kg ${pkgLen}x${pkgWid}x${pkgHei}cm...`);
      const pkgResult = await window.dxmAssistant.fillPackaging({ weight: pkgWt, length: pkgLen, width: pkgWid, height: pkgHei });
      addLog("产品信息", pkgResult.ok ? "success" : "warning", `Step7: 包装 ${pkgResult.ok ? "已填充" : "失败"}`);

      // Step 8: Template info (freight + service)
      addLog("产品信息", "running", "Step8: 模板信息(运费/服务)...");
      const freightVal = localStorage.getItem("dxm.freightTemplate") || "普货小包-标准";
      const serviceVal = localStorage.getItem("dxm.serviceTemplate") || "默认服务模板";
      if (freightVal) { const fr = await window.dxmAssistant.writeDropdownOption("freightTemplate", freightVal); addLog("产品信息", fr.ok?"success":"warning","Step8a: 运费模板="+freightVal+(fr.ok?" OK":" fail")); }
      if (serviceVal) { const sr = await window.dxmAssistant.writeDropdownOption("serviceTemplate", serviceVal); addLog("产品信息", sr.ok?"success":"warning","Step8b: 服务模板="+serviceVal+(sr.ok?" OK":" fail")); }

      // Step 9: Customs (if preset exists)
      const customsPath = localStorage.getItem("dxm.customsPath") || "";
      if (customsPath) {
        addLog("产品信息", "running", `Step9: 海关监管 ${customsPath}...`);
        const pathArr = customsPath.split(",").map(s => s.trim()).filter(Boolean);
        const cr = await window.dxmAssistant.writeCustoms(pathArr);
        addLog("产品信息", cr.ok?"success":"warning", `Step9: 海关 ${cr.ok ? "已写入 " + JSON.stringify(cr.results) : "失败"}`);
      } else {
        addLog("产品信息", "warning", "Step9: 跳过（未预设海关路径）");
      }

      addLog("产品信息", "success", "产品信息填充流程完成");
    } catch (error) {
      addLog("产品信息", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally { setIsProcessingProduct(false); }
  };

  const processFirstImage = async () => {
    setIsProcessing(true);
    try {
      if (!window.dxmAssistant) throw new Error("当前不是桌面应用环境");
      const apiUrl = localStorage.getItem("dxm.aiApiUrl") || "";
      const apiKey = localStorage.getItem("dxm.aiApiKey") || "";
      const prompt = localStorage.getItem("dxm.aiPrompt") || "";
      const size = localStorage.getItem("dxm.aiSize") || "800x800";
      if (!apiUrl) throw new Error("请先在预设配置中填入 AI API 端点");
      if (!apiKey) throw new Error("请先在预设配置中填入 AI API Key");

      // Download first, then process first image
      const dl = await window.dxmAssistant.downloadImages();
      const firstOk = dl.images.find(i => !i.error);
      if (!firstOk) throw new Error("没有可处理的图片");

      addLog("AI处理", "running", `正在处理 ${firstOk.file}...`);
      const result = await window.dxmAssistant.processImage({
        imagePath: firstOk.file,
        apiUrl,
        apiKey,
        prompt: prompt || undefined,
        size
      });

      addLog("AI处理", result.ok ? "success" : "failed",
        result.ok
          ? `处理完成 -> ${result.resultPath}${result.revisedPrompt ? " (修订提示词: " + result.revisedPrompt.substring(0, 60) + ")" : ""}`
          : "处理失败"
      );

      // Auto-upload the processed image
      if (result.ok && result.resultPath) {
        const ul = await window.dxmAssistant.uploadImage(result.resultPath);
        addLog("AI上传", ul.ok ? "success" : "warning", `上传处理后图片: ${ul.ok ? "成功" : "失败"}`);
      }
    } catch (error) {
      addLog("AI处理", "failed", error instanceof Error ? error.message : String(error), "P1");
    } finally { setIsProcessing(false); }
  };

  useEffect(() => {
    refreshChromeStatus();
  }, []);

  useEffect(() => {
    localStorage.setItem(CUSTOM_PRESETS_KEY, JSON.stringify(customPresets));
  }, [customPresets]);

  useEffect(() => {
    localStorage.setItem(LOCKED_PRESET_KEY, lockedPresetId);
  }, [lockedPresetId]);

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Bot size={24} />
          </div>
          <div>
            <h1>店小秘自动编辑</h1>
            <p>AliExpress Listing Assistant</p>
          </div>
        </div>
        <nav className="module-nav">
          {workflowSteps.slice(0, 9).map((step, index) => (
            <a href={`#${step.key}`} key={step.key}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              {moduleIcons[step.key]}
              {step.title}
            </a>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className={`connection-dot ${connection?.status === "connected" ? "connected" : ""}`} />
          <span>
            Chrome {connection?.port || 9222}：{connection?.status === "connected" ? "已连接" : "未连接"}
            {window.dxmAssistant?.version ? <small>App {window.dxmAssistant.version}</small> : null}
            {connection?.activeUrl ? <small>{connection.activeUrl}</small> : null}
            {connection?.status !== "connected" && connection?.error ? <small>{connection.error}</small> : null}
          </span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>自动上架流程工作台</h2>
            <p>按店小秘编辑页顺序处理：扫描、配置、填充、校验、发布</p>
          </div>
          <div className="topbar-actions">
            <button className="secondary-button" onClick={launchChrome} disabled={isLaunchingChrome}>
              <Bot size={17} />
              {isLaunchingChrome ? "启动中" : "启动专用调试 Chrome"}
            </button>
            <button className="secondary-button" onClick={scanProductList} disabled={isScanningList}>
              <Rows3 size={17} />
              {isScanningList ? "扫描中" : "扫描列表"}
            </button>
            <button className="secondary-button" onClick={scanCurrentPage} disabled={isScanning}>
              <RefreshCw size={17} />
              {isScanning ? "扫描中" : "扫描页面"}
            </button>
            <button className="secondary-button" onClick={downloadImages} disabled={isDownloading}>
              <Camera size={17} />
              {isDownloading ? "下载中" : "下载图片"}
            </button>
            <button className="secondary-button" onClick={uploadTestImage} disabled={isUploading}>
              <Save size={17} />
              {isUploading ? "上传中" : "测试上传"}
            </button>
            <button className="primary-button" onClick={processFirstImage} disabled={isProcessing} style={{background: isProcessing ? "#6d7885" : "#7b4fbf"}}>
              <WandSparkles size={17} />
              {isProcessing ? "AI处理中" : "AI处理图片"}
            </button>
            <button className="primary-button">
              <Play size={17} />
              开始处理
            </button>
          </div>
        </header>

        <div className="content-grid">
          <section className="workflow-grid">
            {workflowSteps.map((step, index) => (
              <div id={step.key} key={step.key}>
                <StepCard step={step} index={index} />
              </div>
            ))}
          </section>
          <aside className="right-rail">
            <TaskQueuePanel listResult={listResult} onOpenTask={openTaskEditor} />
            <ProductPreview product={product} scanned={Boolean(scanResult)} />
            <BasicInfoPanel
              product={product}
              suggestion={basicSuggestion}
              onGenerate={generateBasicSuggestion}
              onApply={applyBasicSuggestion}
              onWrite={writeBasicInfoToDxm}
              onWriteCategory={writeCategoryToDxm}
              isWriting={isWritingBasic}
            />
            <ConfigPanel
              presets={allCategoryPresets}
              lockedPresetId={lockedPresetId}
              onLockPreset={setLockedPresetId}
              onSavePreset={saveCategoryPreset}
              dropdownGroups={dropdownGroups}
              onScanDropdowns={scanDropdownOptions}
              isScanningDropdowns={isScanningDropdowns}
              onWriteDropdown={writeDropdownOption}
              onProcessProduct={processProduct}
              isProcessingProduct={isProcessingProduct}
            />
            <ValidationPanel product={product} scanResult={scanResult} logs={logs} onValidate={validateCurrentProduct} />
          </aside>
        </div>
      </section>
    </main>
  );
}

export default App;
