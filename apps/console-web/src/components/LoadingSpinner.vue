<script setup lang="ts">
defineProps<{ message?: string; submessage?: string }>()
</script>

<template>
  <div class="loading-wrap">
    <div class="spinner" aria-hidden="true">
      <span class="ring" />
      <span class="ring ring-delay" />
      <span class="dot" />
    </div>
    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="submessage" class="submessage">{{ submessage }}</p>
  </div>
</template>

<style scoped>
.loading-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2.5rem 1rem;
  gap: 0.75rem;
}

.spinner {
  position: relative;
  width: 56px;
  height: 56px;
}

.ring {
  position: absolute;
  inset: 0;
  border: 3px solid var(--primary-light);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}

.ring-delay {
  inset: 8px;
  border-width: 2px;
  border-top-color: var(--primary-dark);
  animation-duration: 1.2s;
  animation-direction: reverse;
}

.dot {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 10px;
  height: 10px;
  margin: -5px 0 0 -5px;
  background: var(--primary);
  border-radius: 50%;
  animation: pulse 1.2s ease-in-out infinite;
}

.message {
  font-size: 1rem;
  font-weight: 600;
  color: var(--primary-dark);
}

.submessage {
  font-size: 0.88rem;
  color: var(--text-muted);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {
  0%,
  100% {
    transform: scale(0.85);
    opacity: 0.7;
  }
  50% {
    transform: scale(1.1);
    opacity: 1;
  }
}
</style>
