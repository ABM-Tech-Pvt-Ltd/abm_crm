<template>
  <!-- abm_crm: site visits (check-ins) made from the mobile app, with location and photo -->
  <div class="flex flex-col gap-3 px-3 pb-5 sm:px-10">
    <div v-if="visits.loading && !visits.data" class="py-10 text-center text-ink-gray-5">
      {{ __('Loading...') }}
    </div>
    <div
      v-else-if="!visits.data?.length"
      class="flex flex-col items-center justify-center gap-3 py-16 text-ink-gray-4"
    >
      <VisitIcon class="size-10" />
      <span class="text-lg font-medium">{{ __('No site visits') }}</span>
      <span class="text-base">{{ __('Check-ins made from the mobile app show here.') }}</span>
    </div>
    <div
      v-for="visit in visits.data || []"
      v-else
      :key="visit.name"
      class="flex flex-col gap-3 rounded-lg border border-outline-gray-1 bg-surface-cards p-4 sm:flex-row"
    >
      <a
        v-if="visit.photo_url"
        :href="visit.photo_url"
        target="_blank"
        class="block shrink-0 overflow-hidden rounded-md border border-outline-gray-1"
        :title="__('Open photo')"
      >
        <img
          :src="visit.photo_url"
          :alt="__('Visit photo')"
          loading="lazy"
          class="h-40 w-full object-cover sm:h-28 sm:w-36"
        />
      </a>
      <div class="flex min-w-0 flex-1 flex-col gap-1.5">
        <div class="flex items-center gap-2">
          <UserAvatar :user="visit.visited_by" size="sm" />
          <span class="truncate text-base font-medium text-ink-gray-8">
            {{ visit.visited_by_name }}
          </span>
          <span class="text-base text-ink-gray-5">{{ __('checked in') }}</span>
          <Tooltip :text="formatDate(visit.visited_at)">
            <span class="ml-auto shrink-0 text-sm text-ink-gray-5">
              {{ __(timeAgo(visit.visited_at)) }}
            </span>
          </Tooltip>
        </div>
        <div v-if="visit.address" class="flex items-start gap-1.5 text-base text-ink-gray-7">
          <VisitIcon class="mt-0.5 size-4 shrink-0 text-ink-gray-5" />
          <span>{{ visit.address }}</span>
        </div>
        <div v-if="visit.notes" class="whitespace-pre-wrap text-base text-ink-gray-8">
          {{ visit.notes }}
        </div>
        <div class="mt-1 flex flex-wrap items-center gap-2">
          <a :href="visit.map_url" target="_blank">
            <Button size="sm" variant="subtle" :label="__('Open in Maps')" />
          </a>
          <span class="text-sm text-ink-gray-5">
            {{ Number(visit.latitude).toFixed(5) }}, {{ Number(visit.longitude).toFixed(5) }}
            <template v-if="visit.accuracy">· ±{{ Math.round(visit.accuracy) }} m</template>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import VisitIcon from '@/components/Icons/VisitIcon.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { formatDate, timeAgo } from '@/utils'
import { Button, Tooltip, createResource } from 'frappe-ui'
import { watch } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
})

const visits = createResource({
  url: 'abm_crm.api.visits.get_visits',
  cache: ['abm_field_visits', props.doctype, props.docname],
  makeParams: () => ({ doctype: props.doctype, name: props.docname }),
  auto: true,
})

watch(
  () => props.docname,
  () => visits.reload(),
)

defineExpose({ reload: () => visits.reload() })
</script>
