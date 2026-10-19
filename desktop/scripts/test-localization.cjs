const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    let source = fs.readFileSync(filename, 'utf8')
    if (filename.endsWith(path.join('renderer', 'src', 'main.tsx')))
      source = source.replace(/^createRoot\(document[^\n]+$/m, '')
    module._compile(ts.transpileModule(source, { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React, esModuleInterop: true
    } }).outputText, filename)
  }
}
require.extensions['.css'] = () => {}
const base = path.join(__dirname, '../src/renderer/src')
const { english } = require(path.join(base, 'english.ts'))
const { translateText, normalizeLocale, LOCALE_KEY } = require(path.join(base, 'locale-text.ts'))
const { LocaleProvider, Localized, translateTree } = require(path.join(base, 'i18n.tsx'))
let saved = 'en'
global.localStorage = { getItem: key => key === LOCALE_KEY ? saved : null }

assert.equal(normalizeLocale('en'), 'en')
assert.equal(normalizeLocale('unsupported'), 'zh-CN')
assert.equal(translateText('新建计算', 'zh-CN'), '新建计算')
assert.equal(translateText('新建计算', 'en'), 'New calculation')
assert.equal(translateText('核对下界：已计算128个状态', 'en'), 'Checking lower bound: 128 states computed')
assert.equal(translateText('Error: 目标须为 2–65535 的整数', 'en'), 'Error: Target must be an integer from 2 to 65535')
assert.equal(translateText('正在规划…', 'en'), 'Planning…')

// Audit every Chinese UI literal/fragment, including conditional and empty states.
let checked = 0
for (const filename of ['main.tsx', 'Automation.tsx', 'ExitRules.tsx', 'IntegerPlanner.tsx', 'Peak13Planner.tsx']) {
  const source = ts.createSourceFile(filename, fs.readFileSync(path.join(base, filename), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  function visit(node) {
    if ((ts.isStringLiteralLike(node) || ts.isJsxText(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) && /[\u3400-\u9fff]/.test(node.text)) {
      const key = node.text.replace(/\s+/g, ' ').trim()
      assert.ok(Object.hasOwn(english, key), `${filename}: missing translation for ${key}`)
      assert.ok(!/[\u3400-\u9fff]/.test(english[key]), `${filename}: untranslated English value`)
      checked++
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
}
const handler = () => {}
const input = React.createElement('input', { value: '任务', placeholder: '任务名称', onChange: handler })
const localized = translateTree(input, 'en')
assert.equal(localized.props.value, '任务')
assert.equal(localized.props.onChange, handler)
assert.equal(localized.props.placeholder, 'Job name')
for (const tag of ['pre', 'code', 'textarea']) {
  const element = React.createElement(tag, null, '任务')
  assert.equal(translateTree(element, 'en'), element)
}
const raw = React.createElement('strong', { 'data-i18n-skip': true }, '任务')
assert.equal(translateTree(raw, 'en'), raw)
const render = node => renderToStaticMarkup(React.createElement(LocaleProvider, null, node))
const cases = [
  [require(path.join(base, 'main.tsx')).App, {}, 'New calculation'],
  [require(path.join(base, 'Automation.tsx')).Automation, {}, 'Route computation'],
  [require(path.join(base, 'IntegerPlanner.tsx')).IntegerPlanner, {}, 'Structural route planning'],
  [require(path.join(base, 'Peak13Planner.tsx')).Peak13Planner, {}, 'Probability route planner'],
  [require(path.join(base, 'ExitRules.tsx')).ExitRules, { rules: { cells:5,target:48,maxGoalCells:1,bases:[1,3,5,15],successSide:'above' }, update:()=>{} }, 'Template exits and boundaries']
]
for (const [Component, props, label] of cases) assert.ok(render(React.createElement(Component, props)).includes(label), label)
saved = 'zh-CN'
assert.ok(render(React.createElement(Localized, null, '新建计算')).includes('新建计算'))
saved = 'en'
assert.ok(render(React.createElement(Localized, null, '新建计算')).includes('New calculation'))
console.log(`Localization passed: ${checked} UI literals/fragments; five module renders; dynamic messages; stored language; inputs, callbacks and logs preserved.`)
