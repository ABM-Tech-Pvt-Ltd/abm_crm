<template>
  <!-- abm_crm: card list for leads and deals on phones, instead of a sideways-scrolling table -->
  <div class="flex flex-col gap-2 overflow-y-auto px-3 pb-3 pt-1">
    <router-link
      v-for="row in rows"
      :key="row.name"
      :to="routeFor(row)"
      class="flex items-center gap-3 rounded-xl border border-outline-gray-1 bg-surface-white p-3 shadow-sm active:bg-surface-gray-1"
    >
      <Avatar
        size="xl"
        class="shrink-0"
        :label="title(row)"
        :image="image(row)"
      />
      <div class="flex min-w-0 flex-1 flex-col gap-1">
        <div class="flex items-center gap-2">
          <span
            class="truncate text-base"
            :class="
              isVisited(row._seen)
                ? 'text-ink-gray-7'
                : 'font-semibold text-ink-gray-9'
            "
          >
            {{ title(row) }}
          </span>
        </div>
        <div
          v-if="subtitle(row)"
          class="truncate text-p-sm text-ink-gray-6"
        >
          {{ subtitle(row) }}
        </div>
        <div class="flex items-center gap-2 text-p-xs text-ink-gray-5">
          <span
            v-if="row.status?.label"
            class="inline-flex items-center gap-1 rounded-full bg-surface-gray-2 px-2 py-0.5 text-ink-gray-7"
          >
            <IndicatorIcon :class="row.status.color" class="size-2.5" />
            {{ __(row.status.label) }}
          </span>
          <span v-if="row.modified?.timeAgo" class="truncate">
            {{ row.modified.timeAgo }}
          </span>
        </div>
        <!-- abm_crm: tags (builder first) -->
        <div
          v-if="rowTags(row).length"
          class="flex flex-wrap items-center gap-1"
          data-testid="abm-card-tags"
        >
          <span
            v-for="tag in rowTags(row).slice(0, 3)"
            :key="tag.name"
            class="inline-flex h-5 max-w-[9rem] items-center gap-1 rounded-full border px-1.5 text-xs"
            :class="[
              tagChipClass(tag.color),
              tag.category == 'Builder' ? 'font-semibold' : '',
            ]"
          >
            <span class="size-1.5 shrink-0 rounded-full" :class="tagDotClass(tag.color)" />
            <span class="truncate">{{ tag.name }}</span>
          </span>
          <span v-if="rowTags(row).length > 3" class="text-xs text-ink-gray-5">
            +{{ rowTags(row).length - 3 }}
          </span>
        </div>
      </div>
      <div v-if="phone(row)" class="flex shrink-0 gap-1.5" @click.stop>
        <a
          :href="`tel:+${toWhatsappDigits(phone(row))}`"
          :aria-label="__('Call')"
          class="flex size-9 items-center justify-center rounded-full bg-surface-gray-2 text-ink-gray-8 active:scale-95"
          @click.stop
        >
          <PhoneIcon class="size-4" />
        </a>
        <a
          :href="`https://wa.me/${toWhatsappDigits(phone(row))}`"
          target="_blank"
          rel="noopener"
          :aria-label="__('WhatsApp')"
          class="flex size-9 items-center justify-center rounded-full bg-[#25D366] text-white active:scale-95"
          @click.stop
        >
          <WhatsAppIcon class="size-4" />
        </a>
      </div>
    </router-link>
  </div>
</template>

<script setup>
import IndicatorIcon from '@/components/Icons/IndicatorIcon.vue'
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import WhatsAppIcon from '@/components/Icons/WhatsAppIcon.vue'
import { toWhatsappDigits } from '@/composables/whatsapp'
import { useVisitedRecords } from '@/composables/useVisitedRecords'
import { Avatar, createResource } from 'frappe-ui'
import { useRoute } from 'vue-router'
import { computed, watch } from 'vue'
import { parseUserTags, tagChipClass, tagDotClass, useTags } from './tags'

const props = defineProps({
  doctype: { type: String, required: true },
  rows: { type: Array, required: true },
})

const route = useRoute()
const { isVisited } = useVisitedRecords(props.doctype)
const isLead = props.doctype === 'CRM Lead'

const text = (value) =>
  value && typeof value === 'object' ? value.label || '' : value || ''

function routeFor(row) {
  return {
    name: isLead ? 'Lead' : 'Deal',
    params: isLead ? { leadId: row.name } : { dealId: row.name },
    query: { view: route.query.view, viewType: route.params.viewType },
  }
}

function title(row) {
  if (isLead) return text(row.lead_name) || text(row.organization) || row.name
  return text(row.organization) || text(row.lead_name) || row.name
}

function subtitle(row) {
  if (isLead) {
    return [text(row.organization), text(row.lead_owner)].filter(Boolean).join(' · ')
  }
  return [text(row.annual_revenue) || text(row.deal_value), text(row.deal_owner)]
    .filter(Boolean)
    .join(' · ')
}

function image(row) {
  return row.lead_name?.image || row.organization?.logo || ''
}

// `_user_tags` is only in the rows when the Tags column is on, so fetch it for the visible rows
const { tagMeta } = useTags()
const names = computed(() => props.rows.map((r) => r.name).filter(Boolean))
const userTags = createResource({
  url: 'frappe.client.get_list',
  makeParams: () => ({
    doctype: props.doctype,
    fields: ['name', '_user_tags'],
    filters: { name: ['in', names.value] },
    limit_page_length: names.value.length,
  }),
})
watch(
  () => names.value.join(','),
  (key) => key && userTags.fetch(),
  { immediate: true },
)
const tagsByName = computed(() => {
  const map = {}
  for (const r of userTags.data || []) map[r.name] = parseUserTags(r._user_tags)
  return map
})
const categoryRank = (t) => (t.category == 'Builder' ? 0 : 1)

function rowTags(row) {
  const list = tagsByName.value[row.name] ?? parseUserTags(row._user_tags)
  return list.map(tagMeta).sort((a, b) => categoryRank(a) - categoryRank(b))
}

function phone(row) {
  return text(row.mobile_no) || text(row.phone)
}
</script>
