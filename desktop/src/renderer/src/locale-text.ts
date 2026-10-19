import { english } from './english'

export type Locale = 'zh-CN' | 'en'
export const LOCALE_KEY = 'tallnum-interface-language'
export const normalizeLocale = (value: unknown): Locale => value === 'en' ? 'en' : 'zh-CN'

const fragments = Object.keys(english).sort((a, b) => b.length - a.length)
const pattern = new RegExp(fragments.map(key => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g')

/** Translate display text; never use this to transform model or IPC data. */
export function translateText(text: string, locale: Locale): string {
  if (locale === 'zh-CN') return text
  const trimmed = text.trim()
  if (Object.prototype.hasOwnProperty.call(english, trimmed))
    return text.slice(0, text.indexOf(trimmed)) + english[trimmed] + text.slice(text.indexOf(trimmed) + trimmed.length)
  return text.replace(pattern, key => english[key])
}
