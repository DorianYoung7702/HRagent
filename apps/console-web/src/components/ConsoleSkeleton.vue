<template>
  <div class="console-skeleton">
    <div class="skel-parse card" />
    <div class="skel-status card" />
    <div class="skel-tabs card">
      <div class="skel-tab-bar" />
      <div class="skel-tab-body" />
    </div>
  </div>
</template>

<style scoped>
.console-skeleton {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  flex: 1;
  min-height: calc(100vh - 4.5rem);
  opacity: 0.75;
}

.skel-parse {
  height: 100px;
  flex-shrink: 0;
}

.skel-status {
  height: 52px;
  flex-shrink: 0;
}

.skel-tabs {
  flex: 1;
  min-height: 0;
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.skel-tab-bar {
  height: 42px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(90deg, #e8f4fc 25%, #d6ebf7 50%, #e8f4fc 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s ease infinite;
}

.skel-tab-body {
  flex: 1;
  min-height: 0;
  margin: 0.75rem;
  border-radius: 8px;
  background: linear-gradient(90deg, #f5fafd 25%, #e8f4fc 50%, #f5fafd 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s ease infinite;
}

.skel-parse,
.skel-status {
  background: linear-gradient(90deg, #f5fafd 25%, #e8f4fc 50%, #f5fafd 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s ease infinite;
}

@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>
