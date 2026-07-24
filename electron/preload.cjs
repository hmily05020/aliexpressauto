const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dxmAssistant", {
  platform: process.platform,
  version: "0.1.15-repair-handlers",
  getChromeStatus: () => ipcRenderer.invoke("chrome:getStatus"),
  launchDebugChrome: () => ipcRenderer.invoke("chrome:launchDebug"),
  scanProductList: () => ipcRenderer.invoke("chrome:scanProductList"),
  openTaskEditor: (rowIndex) => ipcRenderer.invoke("chrome:openTaskEditor", rowIndex),
  scanEditPage: () => ipcRenderer.invoke("chrome:scanEditPage"),
  writeBasicInfo: (payload) => ipcRenderer.invoke("chrome:writeBasicInfo", payload),
  writeCategory: (payload) => ipcRenderer.invoke("chrome:writeCategory", payload),
  scanDropdownOptions: () => ipcRenderer.invoke("chrome:scanDropdownOptions"),
  diagnoseCategory: () => ipcRenderer.invoke("chrome:diagnoseCategory"),
  diagnoseAttrTemplate: () => ipcRenderer.invoke("chrome:diagnoseAttrTemplate"),
  writeDropdownOption: (fieldKey, value) => ipcRenderer.invoke("chrome:writeDropdownOption", fieldKey, value),
  downloadImages: () => ipcRenderer.invoke("chrome:downloadImages"),
  uploadImage: (filePath) => ipcRenderer.invoke("chrome:uploadImage", filePath),
  processImage: (params) => ipcRenderer.invoke("chrome:processImage", params),
  generateMarketingImages: () => ipcRenderer.invoke("chrome:generateMarketingImages"),
  fillSkuBatch: (params) => ipcRenderer.invoke("chrome:fillSkuBatch", params),
  setOriginalBox: () => ipcRenderer.invoke("chrome:setOriginalBox"),
  writeRegionalPricing: (value) => ipcRenderer.invoke("chrome:writeRegionalPricing", value),
  fillPackaging: (params) => ipcRenderer.invoke("chrome:fillPackaging", params),
  scanCustomsLevels: () => ipcRenderer.invoke("chrome:scanCustomsLevels"),
  writeCustoms: (pathArr) => ipcRenderer.invoke("chrome:writeCustoms", pathArr),
  generateWirelessDesc: () => ipcRenderer.invoke("chrome:generateWirelessDesc"),
  setLogisticsAttribute: () => ipcRenderer.invoke("chrome:setLogisticsAttribute")
});
