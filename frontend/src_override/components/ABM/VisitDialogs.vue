<template>
  <!-- abm_crm: the schedule/edit modal and the status-change dialog, shared by the Visits tab and the Site Visits page -->
  <VisitModal v-model:open="showForm" :visit="editing" :doctype="doctype" :docname="docname" @saved="$emit('changed')" />
  <VisitActionDialog v-model:open="showAction" :visit="target" :mode="mode" @saved="$emit('changed')" />
</template>

<script setup>
import { ref } from 'vue'
import VisitActionDialog from './VisitActionDialog.vue'
import VisitModal from './VisitModal.vue'
import { deleteVisit } from './visits.js'

const emit = defineEmits(['changed'])
const showForm = ref(false)
const showAction = ref(false)
const editing = ref(null)
const target = ref(null)
const mode = ref('Visited')
const doctype = ref('')
const docname = ref('')

defineExpose({
  create(dt, dn) {
    editing.value = null
    doctype.value = dt
    docname.value = dn
    showForm.value = true
  },
  edit(v) {
    editing.value = v
    showForm.value = true
  },
  action(v, status) {
    target.value = v
    mode.value = status
    showAction.value = true
  },
  async remove(v) {
    if (await deleteVisit(v)) emit('changed')
  },
})
</script>
