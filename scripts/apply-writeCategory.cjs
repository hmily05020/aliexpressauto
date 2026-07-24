let fs = require('fs');
let cp = require('child_process');
let mainPath = 'C:/Users/我是好人/Documents/aliexpress/electron/main.cjs';
let exprPath = 'C:/Users/我是好人/Documents/aliexpress/scripts/writeCategory-expr.txt';
let main = fs.readFileSync(mainPath, 'utf8');
let exprBody = fs.readFileSync(exprPath, 'utf8').trim();

// Escape for insertion into a template literal string
let escaped = exprBody
  .replace(/\\/g, '\\\\')
  .replace(/`/g, '\\`')
  .replace(/\$/g, '\\$');

// Find boundaries in main.cjs
let handlerStart = main.indexOf('ipcMain.handle("chrome:writeCategory"');
let payloadStart = main.indexOf('const payloadBase64', handlerStart);
let exprStart = main.indexOf('const expression = `', payloadStart);
let closeMarker = "))()`" + "`;";
let exprEnd = main.indexOf(closeMarker, exprStart);

// exprEnd already found above, but add fallback
if (exprEnd < 0) {
  let endMarker = "`;";
  exprEnd = main.indexOf(endMarker, exprStart + 5000);
}
if (exprEnd < 0) {
  console.log('Cannot find end of expression');
  process.exit(1);
}
// Include the closing backtick-semicolon
while (exprEnd < main.length && (main[exprEnd] === '`' || main[exprEnd] === ';' || main[exprEnd] === ' ' || main[exprEnd] === '\n' || main[exprEnd] === '\r')) {
  exprEnd++;
}

console.log('payloadStart:', payloadStart);
console.log('exprStart:', exprStart, '->', main.substring(exprStart, exprStart + 30));
console.log('exprEnd:', exprEnd, '->', main.substring(exprEnd - 10, exprEnd + 10));

let exprOpen = "const expression = `";
let exprClose = "`;";
let newExprPart = "const payloadBase64 = Buffer.from(JSON.stringify(payload || {}), \"utf8\").toString(\"base64\");\n    " + exprOpen + escaped + exprClose;

let before = main.substring(0, payloadStart);
let after = main.substring(exprEnd);
let result = before + newExprPart + '\n    ' + after;

fs.writeFileSync(mainPath, result, 'utf8');

// Verify
try {
  cp.execSync('node -c "' + mainPath + '"', { encoding: 'utf8' });
  console.log('DONE - Syntax OK');
} catch (e) {
  console.log('SYNTAX ERROR:', e.stderr ? e.stderr.substring(0, 200) : e.message);
}
