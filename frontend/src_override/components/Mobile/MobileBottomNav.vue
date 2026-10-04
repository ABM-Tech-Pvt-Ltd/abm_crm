<template>
  <!-- abm_crm: thumb-friendly navigation for phones. "More" opens the full sidebar. -->
  <nav
    class="grid shrink-0 grid-cols-5 border-t border-outline-gray-1 bg-surface-white pb-[env(safe-area-inset-bottom)]"
  >
    <button
      v-for="item in items"
      :key="item.label"
      class="relative flex h-14 flex-col items-center justify-center gap-1 text-[11px] font-medium transition active:scale-95"
      :class="item.active ? 'text-ink-gray-9' : 'text-ink-gray-5'"
      :aria-current="item.active ? 'page' : undefined"
      @click="item.onClick"
    >
      <span
        class="flex h-7 w-12 items-center justify-center rounded-full transition"
        :class="item.active ? 'bg-surface-gray-3' : ''"
      >
        <component :is="item.icon" class="size-[18px]" />
      </span>
      <span>{{ __(item.label) }}</span>
      <span
        v-if="item.badge"
        class="absolute left-1/2 top-1.5 ml-2 min-w-4 rounded-full bg-surface-red-5 px-1 text-[10px] leading-4 text-white"
      >
        {{ item.badge }}
      </span>
    </button>
  </nav>
</template>

<script setup>
import LeadsIcon from '@/components/Icons/LeadsIcon.vue'
import DealsIcon from '@/components/Icons/DealsIcon.vue'
import TaskIcon from '@/components/Icons/TaskIcon.vue'
import NotificationsIcon from '@/components/Icons/NotificationsIcon.vue'
import LucideMenu from '~icons/lucide/layout-grid'
import { mobileSidebarOpened } from '@/composables/settings'
import { unreadNotificationsCount } from '@/stores/notifications'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const tabs = [
  { label: 'Leads', icon: LeadsIcon, route: 'Leads', match: ['Leads', 'Lead'] },
  { label: 'Deals', icon: DealsIcon, route: 'Deals', match: ['Deals', 'Deal'] },
  { label: 'Tasks', icon: TaskIcon, route: 'Tasks', match: ['Tasks'] },
  {
    label: 'Alerts',
    icon: NotificationsIcon,
    route: 'Notifications',
    match: ['Notifications'],
    badge: () => unreadNotificationsCount.value,
  },
]

const items = computed(() => {
  const inTabs = tabs.some((t) => t.match.includes(route.name))
  return [
    ...tabs
      .filter((t) => router.hasRoute(t.route))
      .map((t) => ({
        label: t.label,
        icon: t.icon,
        badge: t.badge?.(),
        active: t.match.includes(route.name),
        onClick: () => {
          mobileSidebarOpened.value = false
          router.push({ name: t.route })
        },
      })),
    {
      label: 'More',
      icon: LucideMenu,
      active: mobileSidebarOpened.value || !inTabs,
      onClick: () => (mobileSidebarOpened.value = !mobileSidebarOpened.value),
    },
  ]
})
</script>
