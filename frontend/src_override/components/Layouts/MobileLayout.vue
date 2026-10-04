<template>
  <!-- abm_crm: bottom navigation instead of a hamburger-only sidebar on phones -->
  <div class="flex h-[100dvh] w-screen">
    <MobileSidebar />
    <div class="flex h-full min-w-0 flex-1 flex-col bg-surface-base">
      <div class="flex min-h-0 flex-1 flex-col overflow-auto">
        <MobileAppHeader />
        <slot />
      </div>
      <MobileBottomNav />
    </div>
    <GlobalModals />
  </div>
</template>
<script setup>
import MobileSidebar from '@/components/Mobile/MobileSidebar.vue'
import MobileAppHeader from '@/components/Mobile/MobileAppHeader.vue'
import MobileBottomNav from '@/components/Mobile/MobileBottomNav.vue'
import GlobalModals from '@/components/Modals/GlobalModals.vue'
</script>
