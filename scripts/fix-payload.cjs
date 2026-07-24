let fs = require('fs');
let cp = require('child_process');
let path = 'C:/Users/我是好人/Documents/aliexpress/electron/main.cjs';
let content = fs.readFileSync(path, 'utf8');

// Find the escaped string in the writeCategory expression
// We need to find: atob(\"\\${payloadBase64}\")
// and replace with: atob(\"${payloadBase64}\")
// The issue is that $ was escaped to \$

let search = 'atob("\\\\${payloadBase64}")';
let replace = 'atob("${payloadBase64}")';

let count = 0;
while (content.indexOf(search) >= 0) {
  content = content.replace(search, replace);
  count++;
}

// Also try other variants
search = 'atob(\\"\\\\${payloadBase64}\\")';
if (content.indexOf(search) >= 0) {
  content = content.replace(search, 'atob(\\"${payloadBase64}\\")');
  count++;
}

console.log('Replaced', count, 'occurrences');

fs.writeFileSync(path, content, 'utf8');

// Verify syntax
try {
  cp.execSync('node -c "' + path + '"', { encoding: 'utf8' });
  console.log('Syntax OK');
} catch (e) {
  console.log('SYNTAX ERROR:', e.stderr ? e.stderr.substring(0, 300) : e.message);
}
