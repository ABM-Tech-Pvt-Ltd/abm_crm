<template>
  <!-- abm_crm: navigation moved to the bottom bar, so the header only holds the page title -->
  <div class="flex min-h-11 items-center px-1">
    <div id="app-header" class="min-w-0 flex-1" />
  </div>
  <CallUI class="mr-3 mt-2" />
</template>

<script setup>
import CallUI from '@/components/Telephony/CallUI.vue'
</script>
