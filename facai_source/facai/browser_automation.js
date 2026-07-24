/**
 * 店小秘商品编辑自动化脚本
 * 在浏览器开发者工具的 Console 中运行此脚本
 * 使用方式: 复制整个脚本到浏览器控制台 > 按Enter执行
 */

class ShopAutomation {
  constructor() {
    this.config = {
      category: "黑人化纤蕾丝发套",
      template: "假发模板",
      stock: 50000,
      weight: 0.14,
      size: "26*16*6",
      originalBox: "是",
      currencyTemplate: "预设好的不包邮2",
      serviceTemplate: "预设好的",
      customsItem: "蕾丝假发",
      customsMaterial: "高温纤维",
      taxIncluded: "含关税报价",
      europeanResponsible: "预设好的",
      brandManufacturer: "预设好的",
      translationType: "普通翻译",
      languagePair: "中文-英文",
    };
    this.delay = 500; // ms
    this.logs = [];
  }

  log(level, msg) {
    const timestamp = new Date().toLocaleString('zh-CN');
    const logMsg = `[${timestamp}] ${level}: ${msg}`;
    this.logs.push(logMsg);
    console.log(`%c${logMsg}`, level === '✅' ? 'color: green' : level === '❌' ? 'color: red' : 'color: blue');
  }

  async sleep(ms = this.delay) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  // 查找按钮（通过文本内容）
  findButton(text) {
    const buttons = Array.from(document.querySelectorAll('button'));
    return buttons.find(btn => btn.textContent?.includes(text));
  }

  // 查找输入框（通过placeholder或label）
  findInput(label) {
    const inputs = Array.from(document.querySelectorAll('input, textarea'));
    return inputs.find(inp =>
      inp.placeholder?.includes(label) ||
      inp.getAttribute('aria-label')?.includes(label)
    );
  }

  // 查找下拉框选项（通过文本内容）
  findOption(text) {
    const options = Array.from(document.querySelectorAll('[role="option"], .ant-select-item'));
    return options.find(opt => opt.textContent?.includes(text));
  }

  // 点击元素
  async clickElement(element, description) {
    if (!element) {
      this.log('❌', `未找到: ${description}`);
      return false;
    }
    try {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await this.sleep(200);
      element.click();
      this.log('✅', `点击: ${description}`);
      return true;
    } catch (e) {
      this.log('❌', `点击失败 ${description}: ${e.message}`);
      return false;
    }
  }

  // 填充输入框
  async fillInput(input, value, description) {
    if (!input) {
      this.log('❌', `未找到输入框: ${description}`);
      return false;
    }
    try {
      input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await this.sleep(200);
      input.focus();
      input.value = '';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await this.sleep(100);
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      this.log('✅', `填充: ${description} = ${value}`);
      return true;
    } catch (e) {
      this.log('❌', `填充失败 ${description}: ${e.message}`);
      return false;
    }
  }

  // 选择下拉框选项
  async selectOption(dropdownText, optionText, description) {
    try {
      // 查找并点击下拉框
      const dropdown = this.findButton(dropdownText) || Array.from(document.querySelectorAll('[role="combobox"]')).find(d => d.textContent?.includes(dropdownText));
      if (!dropdown) {
        this.log('❌', `未找到下拉框: ${description}`);
        return false;
      }

      dropdown.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await this.sleep(200);
      dropdown.click();
      await this.sleep(300);

      // 查找并点击选项
      const option = this.findOption(optionText);
      if (!option) {
        this.log('❌', `未找到选项: ${optionText}`);
        return false;
      }

      option.click();
      this.log('✅', `选择: ${description} = ${optionText}`);
      await this.sleep(this.delay);
      return true;
    } catch (e) {
      this.log('❌', `选择失败 ${description}: ${e.message}`);
      return false;
    }
  }

  // 一键操作（点击按钮）
  async clickButtonByText(text, description) {
    const button = this.findButton(text);
    return await this.clickElement(button, description || text);
  }

  // 开始自动化流程
  async run() {
    this.log('✅', '开始自动编辑流程...');

    try {
      // 步骤1: 修改类目
      this.log('✅', '【步骤1】修改类目为: ' + this.config.category);
      await this.clickButtonByText('选择分类', '类目选择按钮');
      await this.sleep(500);
      // TODO: 在这里选择类目（需要根据实际页面调整）

      // 步骤2: 选择模板
      this.log('✅', '【步骤2】选择模板: ' + this.config.template);
      await this.clickButtonByText('引用模板', '模板引用按钮');
      await this.sleep(500);
      // TODO: 选择假发模板

      // 步骤3: 处理图片
      this.log('✅', '【步骤3】处理产品图片');
      await this.clickButtonByText('一键生成', '营销图一键生成');
      await this.sleep(800);

      // 步骤4: 填充基本信息
      this.log('✅', '【步骤4】填充基本信息');
      // 库存
      const stockInput = this.findInput('库存');
      await this.fillInput(stockInput, this.config.stock.toString(), '库存');

      // 重量
      const weightInput = this.findInput('重量');
      await this.fillInput(weightInput, this.config.weight.toString(), '重量');

      // 步骤5: 一键翻译
      this.log('✅', '【步骤5】执行一键翻译');
      await this.clickButtonByText('一键翻译', '翻译按钮');
      await this.sleep(800);

      // 步骤6: 发布
      this.log('✅', '【步骤6】发布商品');
      await this.clickButtonByText('立即发布', '发布按钮');
      await this.sleep(1000);

      this.log('✅', '自动编辑流程完成！');
      this.showSummary();

    } catch (e) {
      this.log('❌', `流程出错: ${e.message}`);
      this.showSummary();
    }
  }

  showSummary() {
    console.log('\n' + '='.repeat(50));
    console.log('📋 自动化执行日志:');
    console.log('='.repeat(50));
    this.logs.forEach(log => console.log(log));
    console.log('='.repeat(50));
  }
}

// 执行
const automation = new ShopAutomation();
automation.run();
