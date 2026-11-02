/** 通用格式化工具（课程时间、星期等） */

export const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

/** weekday: 1-7 → 周一..周日 */
export function weekdayName(w) {
  const n = Number(w)
  if (!n || n < 1 || n > 7) return '—'
  return WEEKDAYS[n - 1]
}

/** 节次区间 → "1-2 节" / "3 节" */
export function slotText(start, end) {
  if (!start && !end) return '—'
  if (!end || start === end) return `${start} 节`
  return `${start}-${end} 节`
}

/** 上课时间地点：周一 1-2 节 · 信息楼 A301 */
export function courseTimeText(c) {
  const w = weekdayName(c.weekday)
  const s = slotText(c.start_slot, c.end_slot)
  const loc = c.location ? ` · ${c.location}` : ''
  if (w === '—') return loc ? loc.slice(3) : '—'
  return `${w} ${s}${loc}`
}

/** 分数 → 颜色档位 */
export function scoreGrade(score) {
  if (score === null || score === undefined) return 'mute'
  if (score >= 90) return 'ok'
  if (score >= 80) return 'accent'
  if (score >= 60) return 'warn'
  return 'danger'
}
