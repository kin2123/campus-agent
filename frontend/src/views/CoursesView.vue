<script setup>
/**
 * CoursesView —— 课程列表
 * 搜索 / 类别筛选 / 只看有余量；选课直接调 REST（不经 Agent），失败时弹出后端 message。
 */
import { ref, onMounted } from 'vue'
import { listCourses, getCategories, enrollCourse } from '../api/endpoints.js'
import CourseTable from '../components/CourseTable.vue'

const courses = ref([])
const categories = ref([])
const keyword = ref('')
const category = ref('')
const onlyAvailable = ref(false)

const loading = ref(false)
const busyCodes = ref([])
const notice = ref(null) // { type:'ok'|'err', text }

let timer = null
function flash(type, text) {
  notice.value = { type, text }
  clearTimeout(timer)
  timer = setTimeout(() => { notice.value = null }, 4500)
}

async function load() {
  loading.value = true
  try {
    courses.value = await listCourses({
      keyword: keyword.value.trim(),
      category: category.value,
      only_available: onlyAvailable.value ? true : undefined,
    })
  } catch (e) {
    flash('err', e.message || '加载课程失败')
    courses.value = []
  } finally {
    loading.value = false
  }
}

async function handleEnroll(course) {
  if (busyCodes.value.includes(course.code)) return
  busyCodes.value = [...busyCodes.value, course.code]
  try {
    const res = await enrollCourse(course.code)
    flash('ok', res.message || `已选上 ${course.name}`)
    await load()
  } catch (e) {
    // 后端失败会返回 409 + detail.message，client.js 已提取到 e.message
    flash('err', e.message || '选课失败')
  } finally {
    busyCodes.value = busyCodes.value.filter((c) => c !== course.code)
  }
}

let debounce = null
function onKeywordInput() {
  clearTimeout(debounce)
  debounce = setTimeout(load, 300)
}

function resetFilters() {
  keyword.value = ''
  category.value = ''
  onlyAvailable.value = false
  load()
}

onMounted(async () => {
  try {
    categories.value = await getCategories()
  } catch {
    categories.value = []
  }
  await load()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>课程列表</h2>
        <p class="muted small">浏览可选课程，直接点击「选课」提交（走 REST 接口，不经过 Agent）</p>
      </div>
      <div class="row small muted">
        <span v-if="loading" class="row small"><span class="spinner"></span> 加载中…</span>
        <span v-else>共 {{ courses.length }} 门</span>
      </div>
    </div>

    <div class="card filters">
      <input
        v-model="keyword"
        class="input grow"
        placeholder="搜索课程名称 / 代码 / 教师…"
        @input="onKeywordInput"
        @keydown.enter="load"
      />
      <select class="select" style="width:150px" v-model="category" @change="load">
        <option value="">全部类别</option>
        <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
      </select>

      <label class="switch">
        <input type="checkbox" v-model="onlyAvailable" @change="load" />
        <span class="slider"></span>
        <span class="switch-label">只看有余量</span>
      </label>

      <button class="btn btn-ghost" @click="resetFilters">重置</button>
    </div>

    <div v-if="notice" class="notice" :class="notice.type === 'ok' ? 'notice-ok' : 'notice-err'">
      <span>{{ notice.type === 'ok' ? '✓' : '⚠' }} {{ notice.text }}</span>
      <button class="notice-close" @click="notice = null">×</button>
    </div>

    <div class="card table-card">
      <CourseTable
        :courses="courses"
        action="enroll"
        :busy-codes="busyCodes"
        empty-text="没有符合条件的课程"
        @enroll="handleEnroll"
      />
    </div>
  </div>
</template>

<style scoped>
.page { height: 100%; overflow-y: auto; padding: 22px 24px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.page-head h2 { margin: 0 0 2px; font-size: 18px; }
.page-head p { margin: 0; }

.filters { display: flex; align-items: center; gap: 12px; padding: 12px 14px; margin-bottom: 14px; flex-wrap: wrap; }
.filters .grow { flex: 1; min-width: 200px; }

/* 开关 */
.switch { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; }
.switch input { display: none; }
.slider {
  width: 36px; height: 20px; border-radius: 20px;
  background: #2a313d; position: relative; transition: background .15s;
  flex-shrink: 0;
}
.slider::after {
  content: ''; position: absolute; top: 2px; left: 2px;
  width: 16px; height: 16px; border-radius: 50%;
  background: #8a93a3; transition: all .15s;
}
.switch input:checked + .slider { background: var(--accent-dim); }
.switch input:checked + .slider::after { left: 18px; background: #eaf3ff; }
.switch-label { font-size: 13px; color: var(--text-dim); }

.notice {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  border-radius: var(--radius-sm); padding: 10px 14px; margin-bottom: 14px; font-size: 13px;
}
.notice-ok { background: var(--ok-soft); border: 1px solid rgba(53,201,138,.35); color: #7fe6b8; }
.notice-err { background: var(--danger-soft); border: 1px solid rgba(240,97,109,.35); color: #ff9aa3; }
.notice-close { background: none; border: none; color: inherit; font-size: 18px; cursor: pointer; line-height: 1; }

.table-card { overflow: hidden; }
</style>
