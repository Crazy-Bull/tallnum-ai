import React, { createContext, useContext, useEffect, useState } from 'react'
import { LOCALE_KEY, normalizeLocale, translateText, type Locale } from './locale-text'

const LanguageContext = createContext<{ locale: Locale; change: (value: Locale) => void }>({ locale: 'zh-CN', change: () => {} })

export function LocaleProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [locale, setLocale] = useState<Locale>(() => {
    try { return normalizeLocale(localStorage.getItem(LOCALE_KEY)) } catch { return 'zh-CN' }
  })
  useEffect(() => {
    document.documentElement.lang = locale
    document.title = locale === 'en' ? 'Tallnum Calculator' : 'Tallnum 计算器'
    try { localStorage.setItem(LOCALE_KEY, locale) } catch { /* A restricted profile can still switch for this session. */ }
  }, [locale])
  return <LanguageContext.Provider value={{ locale, change: setLocale }}>{children}</LanguageContext.Provider>
}

/** Localize React output, preserving event handlers, keys, values and state.
 * Nested module components use the same boundary when they render.
 * Raw logs, JSON, code, user inputs and explicitly marked content are excluded.
 */
export function translateTree(node: React.ReactNode, locale: Locale): React.ReactNode {
  if (locale === 'zh-CN') return node
  if (typeof node === 'string') return translateText(node, locale)
  if (Array.isArray(node)) return node.map(child => translateTree(child, locale))
  if (!React.isValidElement(node)) return node
  const element = node as React.ReactElement<Record<string, unknown>>
  if (element.props['data-i18n-skip'] || ['pre', 'code', 'textarea', 'script', 'style'].includes(String(element.type))) return node
  const props: Record<string, unknown> = {}
  for (const key of ['title', 'placeholder', 'aria-label', 'alt']) {
    const value = element.props[key]
    if (typeof value === 'string') props[key] = translateText(value, locale)
  }
  if (element.props.children !== undefined) props.children = translateTree(element.props.children as React.ReactNode, locale)
  return React.cloneElement(element, props)
}

export function Localized({ children }: { children: React.ReactNode }): React.JSX.Element {
  const { locale } = useContext(LanguageContext)
  return <>{translateTree(children, locale)}</>
}

export function LanguageSelector(): React.JSX.Element {
  const { locale, change } = useContext(LanguageContext)
  return <label className="language-selector">Language / 语言
    <select aria-label="Interface language / 界面语言" value={locale} onChange={event => change(normalizeLocale(event.target.value))}>
      <option value="zh-CN">简体中文</option><option value="en">English</option>
    </select>
  </label>
}
