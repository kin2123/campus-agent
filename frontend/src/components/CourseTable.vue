<script setup>
/**
 * CourseTable —— 课程表格
 * 展示课程代码 / 名称 / 教师 / 学分 / 类别 / 时间地点 / 余量，并提供选课（或退课）按钮。
 */
import { courseTimeText } from '../utils/format.js'

defineProps({
  courses: { type: Array, default: () => [] },
  /** 'enroll' | 'drop' | '' 控制操作列 */
  action: { type: String, default: 'enroll' },
  /** 正在处理中的课程代码集合，用于禁用按钮 */
  busyCodes: { type: Array, default: () => [] },
  emptyText: { type: String, default: '暂无课程' },
})
const emit = defineEmits(['enroll', 'drop'])
</script>

<template>
  <div class="ct-wrap">
    <table v-if="courses.length" class="table">
      <thead>
        <tr>
          <th style="width:88px">课程代码</th>
          <th>课程名称</th>
          <th style="width:90px">教师</th>
          <th style="width:56px">学分</th>
          <th style="width:92px">类别</th>
          <th>时间 / 地点</th>
          <th style="width:78px">余量</th>
          <th v-if="action" style="width:80px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in courses" :key="c.code">
          <td><code class="mono">{{ c.code }}</code></td>
          <td>
            <div class="c-name">{{ c.name }}</div>
            <div v-if="c.exam_type" class="c-sub">考核：{{ c.exam_type }}</div>
          </td>
          <td>{{ c.teacher_name || '—' }}</td>
          <td>{{ c.credits }}</td>
          <td><span class="tag tag-mute">{{ c.category || '—' }}</span></td>
          <td class="small muted">{{ courseTimeText(c) }}</td>
          <td>
            <span
              class="tag"
              :class="c.remaining > 0 ? 'tag-ok' : 'tag-danger'"
            >
              {{ c.remaining > 0 ? `${c.remaining}/${c.capacity}` : '已满' }}
            </span>
          </td>
          <td v-if="action">
            <button
              v-if="action === 'enroll'"
              class="btn btn-sm btn-primary"
              :disabled="c.remaining <= 0 || busyCodes.includes(c.code)"
              @click="emit('enroll', c)"
            >
              {{ busyCodes.includes(c.code) ? '…' : '选课' }}
            </button>
            <button
              v-else
              class="btn btn-sm btn-danger"
              :disabled="busyCodes.includes(c.code)"
              @click="emit('drop', c)"
            >
              {{ busyCodes.includes(c.code) ? '…' : '退课' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else class="empty">{{ emptyText }}</div>
  </div>
</template>

<style scoped>
.ct-wrap { overflow: auto; }
.c-name { font-weight: 500; }
.c-sub { font-size: 11.5px; color: var(--text-mute); margin-top: 1px; }
</style>
