<script setup>
/**
 * ScheduleView —— 我的课表 / 成绩（两个 tab）
 *  · 课表：周一到周日 × 节次的网格，课程块按 weekday / start_slot-end_slot 定位
 *  · 成绩：总学分 / 加权均分 / GPA 三个数字卡片 + 成绩明细表
 */
import { ref, computed, onMounted } from 'vue'
import { getMySchedule, getMyGrades } from '../api/endpoints.js'
import { WEEKDAYS, weekdayName, scoreGrade } from '../utils/format.js'

const tab = ref('schedule')

const schedule = ref([])
const grades = ref(null)
const loadingS = ref(false)
const loadingG = ref(false)
const errS = ref('')
const errG = ref('')

/* ---------- 课表网格 ---------- */
const PALETTE = [
  { bg: 'rgba(78,161,255,.16)', bd: 'rgba(78,161,255,.55)', fg: '#9cc8ff' },
  { bg: 'rgba(53,201,138,.15)', bd: 'rgba(53,201,138,.5)', fg: '#8ce6bb' },
  { bg: 'rgba(167,139,250,.16)', bd: 'rgba(167,139,250,.5)', fg: '#c3b2ff' },
  { bg: 'rgba(240,162,60,.15)', bd: 'rgba(240,162,60,.5)', fg: '#f6c885' },
  { bg: 'rgba(240,97,109,.14)', bd: 'rgba(240,97,109,.5)', fg: '#ff9aa3' },
  { bg: 'rgba(90,200,220,.15)', bd: 'rgba(90,200,220,.5)', fg: '#96dbe8' },
]

const colorMap = computed(() => {
  const m = {}
  schedule.value.forEach((c, i) => { m[c.code] = PALETTE[i % PALETTE.length] })
  return m
})

const maxSlot = computed(() => {
  let m = 0
  schedule.value.forEach((c) => {
    m = Math.max(m, Number(c.end_slot) || Number(c.start_slot) || 0)
  })
  return Math.max(m, 12)
})
const slots = computed(() => Array.from({ length: maxSlot.value }, (_, i) => i + 1))

/** 课程块在网格中的位置样式 */
function blockStyle(c) {
  const col = (Number(c.weekday) || 1) + 1
  const start = Number(c.start_slot) || 1
  const end = Number(c.end_slot) || start
  const p = colorMap.value[c.code] || PALETTE[0]
  return {
    gridColumn: `${col} / ${col + 1}`,
    gridRow: `${start + 1} / ${end + 2}`,
    background: p.bg,
    borderColor: p.bd,
    color: p.fg,
  }
}

async function loadSchedule() {
  loadingS.value = true
  errS.value = ''
  try {
    schedule.value = await getMySchedule()
  } catch (e) {
    errS.value = e.message || '加载课表失败'
  } finally {
    loadingS.value = false
  }
}

async function loadGrades() {
  loadingG.value = true
  errG.value = ''
  try {
    grades.value = await getMyGrades()
  } catch (e) {
    errG.value = e.message || '加载成绩失败'
  } finally {
    loadingG.value = false
  }
}

function switchTab(t) {
  tab.value = t
  if (t === 'schedule' && !schedule.value.length && !loadingS.value) loadSchedule()
  if (t === 'grades' && !grades.value && !loadingG.value) loadGrades()
}

onMounted(() => {
  loadSchedule()
  loadGrades()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>我的课表 / 成绩</h2>
      <div class="tabs">
        <button class="tab" :class="{ active: tab === 'schedule' }" @click="switchTab('schedule')">课表</button>
        <button class="tab" :class="{ active: tab === 'grades' }" @click="switchTab('grades')">成绩</button>
      </div>
    </div>

    <!-- ============ 课表 tab ============ -->
    <template v-if="tab === 'schedule'">
      <div v-if="loadingS" class="empty"><span class="spinner"></span> 加载中…</div>
      <div v-else-if="errS" class="notice-err notice">{{ errS }}</div>
      <div v-else-if="!schedule.length" class="empty">本学期还没有已选课程</div>

      <div v-else class="card timetable-card">
        <div class="timetable" :style="{ gridTemplateRows: '34px repeat(' + maxSlot + ', 58px)' }">
          <!-- 表头 -->
          <div class="tt-corner"></div>
          <div v-for="(d, i) in WEEKDAYS" :key="'h' + i" class="tt-head">{{ d }}</div>

          <!-- 节次刻度列 -->
          <template v-for="s in slots" :key="'s' + s">
            <div class="tt-slot" :style="{ gridRow: s + 1, gridColumn: 1 }">{{ s }}</div>
          </template>

          <!-- 背景格 -->
          <template v-for="s in slots" :key="'b' + s">
            <div
              v-for="(d, di) in WEEKDAYS"
              :key="'b' + s + di"
              class="tt-cell"
              :style="{ gridRow: s + 1, gridColumn: di + 2 }"
            ></div>
          </template>

          <!-- 课程块 -->
          <div
            v-for="c in schedule"
            :key="c.code"
            class="tt-block"
            :style="blockStyle(c)"
            :title="`${c.name} ${c.teacher_name} ${c.location}`"
          >
            <div class="tb-name">{{ c.name }}</div>
            <div class="tb-loc">{{ c.location }}</div>
            <div class="tb-teacher">{{ c.teacher_name }}</div>
          </div>
        </div>
      </div>

      <!-- 课程清单 -->
      <div v-if="schedule.length" class="card list-card">
        <table class="table">
          <thead>
            <tr>
              <th style="width:88px">代码</th>
              <th>课程</th>
              <th style="width:90px">教师</th>
              <th style="width:56px">学分</th>
              <th style="width:150px">时间</th>
              <th style="width:130px">地点</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in schedule" :key="c.code">
              <td><code class="mono">{{ c.code }}</code></td>
              <td>{{ c.name }}</td>
              <td>{{ c.teacher_name }}</td>
              <td>{{ c.credits }}</td>
              <td class="small muted">
                {{ weekdayName(c.weekday) }}
                {{ c.start_slot === c.end_slot ? c.start_slot : `${c.start_slot}-${c.end_slot}` }} 节
              </td>
              <td class="small muted">{{ c.location }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- ============ 成绩 tab ============ -->
    <template v-else>
      <div v-if="loadingG" class="empty"><span class="spinner"></span> 加载中…</div>
      <div v-else-if="errG" class="notice-err notice">{{ errG }}</div>
      <template v-else-if="grades">
        <div class="stat-row">
          <div class="card stat">
            <div class="stat-value">{{ grades.total_credit }}</div>
            <div class="stat-label">已修总学分</div>
          </div>
          <div class="card stat">
            <div class="stat-value">{{ grades.average }}</div>
            <div class="stat-label">加权平均分</div>
          </div>
          <div class="card stat">
            <div class="stat-value accent">{{ grades.gpa }}</div>
            <div class="stat-label">平均绩点 GPA</div>
          </div>
          <div class="card stat">
            <div class="stat-value">{{ grades.course_count }}</div>
            <div class="stat-label">课程门数</div>
          </div>
        </div>

        <div class="card list-card">
          <table class="table">
            <thead>
              <tr>
                <th style="width:88px">代码</th>
                <th>课程名称</th>
                <th style="width:56px">学分</th>
                <th style="width:120px">学期</th>
                <th style="width:90px">成绩</th>
                <th style="width:80px">绩点</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="g in grades.items" :key="g.course_code">
                <td><code class="mono">{{ g.course_code }}</code></td>
                <td>{{ g.course_name }}</td>
                <td>{{ g.credits }}</td>
                <td class="small muted">{{ g.semester }}</td>
                <td>
                  <span class="tag" :class="'tag-' + (scoreGrade(g.score) === 'mute' ? 'mute' : scoreGrade(g.score))">
                    {{ g.score }}
                  </span>
                </td>
                <td>{{ g.grade_point }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.page { height: 100%; overflow-y: auto; padding: 22px 24px; }
.page-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-head h2 { margin: 0; font-size: 18px; }

.tabs { display: flex; gap: 4px; background: var(--bg-panel-2); padding: 3px; border-radius: var(--radius-sm); border: 1px solid var(--border); }
.tab {
  padding: 6px 18px; border: none; background: transparent; color: var(--text-dim);
  font-family: inherit; font-size: 13px; cursor: pointer; border-radius: 5px; transition: all .15s;
}
.tab.active { background: var(--accent-soft); color: var(--accent); }
.tab:hover:not(.active) { color: var(--text); }

.notice { display: flex; align-items: center; gap: 10px; border-radius: var(--radius-sm); padding: 10px 14px; font-size: 13px; margin-bottom: 14px; }
.notice-err { background: var(--danger-soft); border: 1px solid rgba(240,97,109,.35); color: #ff9aa3; }

/* ---------- 课表 ---------- */
.timetable-card { padding: 14px; overflow: auto; margin-bottom: 18px; }
.timetable {
  display: grid;
  grid-template-columns: 46px repeat(7, minmax(96px, 1fr));
  gap: 2px;
  min-width: 760px;
}
.tt-corner { grid-column: 1; grid-row: 1; }
.tt-head {
  grid-row: 1;
  display: flex; align-items: center; justify-content: center;
  font-size: 12.5px; color: var(--text-dim); font-weight: 600;
  background: var(--bg-panel-2); border-radius: 5px;
}
.tt-slot {
  display: flex; align-items: center; justify-content: center;
  font-size: 11.5px; color: var(--text-mute);
}
.tt-cell {
  background: rgba(255,255,255,.015);
  border: 1px solid var(--border);
  border-radius: 5px;
}
.tt-block {
  border: 1px solid;
  border-radius: 6px;
  padding: 5px 7px;
  font-size: 11.5px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 1px;
  cursor: default;
}
.tb-name { font-weight: 600; font-size: 12px; line-height: 1.25; }
.tb-loc, .tb-teacher { font-size: 10.5px; opacity: .82; }

.list-card { overflow: hidden; }

/* ---------- 成绩 ---------- */
.stat-row { display: flex; gap: 14px; margin-bottom: 18px; flex-wrap: wrap; }
.stat { flex: 1; min-width: 130px; padding: 18px 20px; }
.stat-value { font-size: 30px; font-weight: 700; line-height: 1.1; letter-spacing: -.02em; }
.stat-value.accent { color: var(--accent); }
.stat-label { font-size: 12px; color: var(--text-dim); margin-top: 6px; }
</style>
