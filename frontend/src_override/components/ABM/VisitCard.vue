<template>
  <!-- abm_crm: one site visit -->
  <div
    class="flex flex-col gap-3 rounded-lg border border-outline-gray-1 bg-surface-cards p-3 sm:flex-row sm:p-4"
    :class="linkable ? 'cursor-pointer hover:border-outline-gray-3' : ''"
    @click="linkable && router.push(refRoute(visit))"
  >
    <a
      v-if="visit.photo_url"
      :href="visit.photo_url"
      target="_blank"
      class="block shrink-0 overflow-hidden rounded-md border border-outline-gray-1"
      :title="__('Open photo')"
      @click.stop
    >
      <img :src="visit.photo_url" :alt="__('Visit photo')" loading="lazy" class="h-36 w-full object-cover sm:h-24 sm:w-32" />
    </a>
    <div class="flex min-w-0 flex-1 flex-col gap-2">
      <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span
          class="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium"
          :class="chipClass(visit.status_color)"
        >
          <span class="size-1.5 rounded-full" :class="dotClass(visit.status_color)" />
          {{ __(visit.status) }}
        </span>
        <span class="text-base font-medium text-ink-gray-8">{{ __(visit.visit_type) }}</span>
        <span v-if="visit.project" class="min-w-0 truncate text-base text-ink-gray-7">· {{ visit.project }}</span>
        <span v-if="visit.outcome" class="rounded bg-surface-gray-2 px-1.5 py-0.5 text-xs text-ink-gray-7">
          {{ __(visit.outcome) }}
        </span>
      </div>

      <div v-if="linkable && visit.reference_title" class="flex items-center gap-1.5 text-base">
        <span class="text-ink-gray-5">{{ visit.reference_doctype === 'CRM Deal' ? __('Deal') : __('Lead') }}</span>
        <router-link :to="refRoute(visit)" class="truncate font-medium text-ink-gray-9 hover:underline" @click.stop>
          {{ visit.reference_title }}
        </router-link>
        <span v-if="visit.phone" class="truncate text-ink-gray-5">· {{ visit.phone }}</span>
      </div>

      <div class="flex flex-wrap gap-x-4 gap-y-0.5 text-sm text-ink-gray-6">
        <span v-if="visit.scheduled_on">
          {{ visit.status === 'Postponed' ? __('Postponed to') : __('Scheduled') }}:
          <span class="text-ink-gray-8">{{ fmtDateTime(visit.scheduled_on) }}</span>
        </span>
        <span v-if="visit.visited_at">
          {{ __('Visited') }}: <span class="text-ink-gray-8">{{ fmtDateTime(visit.visited_at) }}</span>
        </span>
      </div>

      <div v-if="team.length" class="flex flex-wrap gap-x-4 gap-y-0.5 text-sm text-ink-gray-6">
        <span v-for="p in team" :key="p.label">
          {{ __(p.label) }}: <span class="text-ink-gray-8">{{ p.name }}</span>
        </span>
      </div>

      <div v-if="visit.status_reason" class="text-sm text-ink-gray-6">
        {{ __('Reason') }}: <span class="text-ink-gray-8">{{ visit.status_reason }}</span>
      </div>
      <div v-if="visit.address" class="flex items-start gap-1.5 text-sm text-ink-gray-7">
        <VisitIcon class="mt-0.5 size-4 shrink-0 text-ink-gray-5" />
        <span>{{ visit.address }}</span>
      </div>
      <div v-if="visit.notes" class="whitespace-pre-wrap text-base text-ink-gray-8">{{ visit.notes }}</div>

      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-gray-5">
        <a v-if="visit.map_url" :href="visit.map_url" target="_blank" class="text-blue-600 hover:underline" @click.stop>
          {{ __('Open in Maps') }}
        </a>
        <span v-if="recorder">{{ __('Recorded by {0}', [recorder]) }}</span>
      </div>

      <div class="mt-1 flex flex-wrap items-center gap-1.5" @click.stop>
        <Button v-if="act.visited" size="sm" variant="subtle" theme="green" :label="__('Mark visited')" @click="$emit('action', visit, 'Visited')" />
        <Button v-if="act.postpone" size="sm" variant="subtle" :label="__('Postpone')" @click="$emit('action', visit, 'Postponed')" />
        <Button v-if="act.cancel" size="sm" variant="subtle" :label="__('Cancel')" @click="$emit('action', visit, 'Cancelled')" />
        <Button v-if="act.noShow" size="sm" variant="subtle" :label="__('No show')" @click="$emit('action', visit, 'No Show')" />
        <Button size="sm" variant="ghost" :label="__('Edit')" @click="$emit('edit', visit)" />
        <Button size="sm" variant="ghost" theme="red" :label="__('Delete')" @click="$emit('delete', visit)" />
      </div>
    </div>
  </div>
</template>

<script setup>
import VisitIcon from '@/components/Icons/VisitIcon.vue'
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { actionsFor, chipClass, dotClass, fmtDateTime, people, refRoute } from './visits.js'

const props = defineProps({
  visit: { type: Object, required: true },
  linkable: { type: Boolean, default: false },
})
defineEmits(['edit', 'action', 'delete'])

const router = useRouter()
const team = computed(() => people(props.visit))
const act = computed(() => actionsFor(props.visit))
const recorder = computed(() => props.visit.visited_by_name || props.visit.owner_name || props.visit.visited_by)
</script>
