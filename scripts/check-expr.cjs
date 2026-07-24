let fs=require('fs');
let m=fs.readFileSync('C:/Users/我是好人/Documents/aliexpress/electron/main.cjs','utf8');
let start=m.indexOf('ipcMain.handle("chrome:setLogisticsAttribute"');
let exprStart=m.indexOf('const expression = ',start);
let exprEnd=m.indexOf('))' + '`;',exprStart);
if(exprEnd<0) exprEnd=m.indexOf('`;',exprStart+100);
console.log('exprStart:',exprStart,'exprEnd:',exprEnd,'len:',exprEnd-exprStart);
// Show the expression content
let expr=m.substring(exprStart,exprEnd+3);
console.log('--- EXPRESSION START ---');
console.log(expr.substring(0,600));
console.log('...');
console.log(expr.substring(expr.length-300));
console.log('--- EXPRESSION END ---');

// Check for syntax issues
// Find if there are unescaped characters that would break it
let btCount=(expr.match(/`/g)||[]).length;
console.log('Backtick count in handler code:',btCount);
