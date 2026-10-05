<script setup lang="ts">
import type { MapNode } from './types'
defineProps<{ nodes: MapNode[] }>()
const emit = defineEmits<{ locate: [id: string] }>()
</script>

<template>
  <ul class="map-tree">
    <li v-for="node in nodes" :key="node.id">
      <details v-if="node.children.length" :open="node.id === 'root'">
        <summary>{{ node.text }}</summary>
        <button v-if="node.cue_ids[0]" class="learning-reference" type="button" @click="emit('locate', node.cue_ids[0])">查看原文</button>
        <MindMapTree :nodes="node.children" @locate="emit('locate', $event)" />
      </details>
      <template v-else>
        <p>{{ node.text }}</p>
        <button v-if="node.cue_ids[0]" class="learning-reference" type="button" @click="emit('locate', node.cue_ids[0])">查看原文</button>
      </template>
    </li>
  </ul>
</template>
