<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import './styles/theme.css'
import logo from './assets/theme/logo.webp'
import character from './assets/theme/character.webp'
import cat from './assets/theme/sleeping-cat.webp'
import star from './assets/theme/star.webp'
import bow from './assets/theme/bow.webp'
import planet from './assets/theme/planet.webp'
import flowers from './assets/theme/flowers.webp'

const route = useRoute()
const menuOpen = ref(false)
const experimentOpen = ref(route.path.startsWith('/experiment'))
const navigation = [
  { path: '/', label: '实时仪表盘', icon: 'dashboard', caption: '运行概览' },
  { path: '/control', label: '设备控制', icon: 'control', caption: '设备工作台' },
  { path: '/experiment', label: '实验自动化', icon: 'experiment', caption: '实验工作台' },
  { path: '/campaigns', label: '智能实验', icon: 'campaign', caption: '探索与记录' },
  { path: '/history', label: '实验历史', icon: 'history', caption: '实验档案' },
]
const currentPage = computed(() => route.path === '/experiment/batch' ? { label: '引导式实验', caption: '实验条件与固定流程' } : route.path === '/experiment/editor' ? { label: '实验编排', caption: '实验编排' } : navigation.find(item => item.path === route.path) || navigation[0]!)
watch(() => route.path, () => { menuOpen.value = false; if (route.path.startsWith('/experiment')) experimentOpen.value = true })
</script>

<template>
  <div class="heat-shell">
    <svg class="icon-definitions" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <symbol id="dashboard" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></symbol>
        <symbol id="control" viewBox="0 0 24 24"><path d="M5 3v7m0 4v7M12 3v12m0 4v2M19 3v2m0 4v12"/><circle cx="5" cy="12" r="2"/><circle cx="12" cy="17" r="2"/><circle cx="19" cy="7" r="2"/></symbol>
        <symbol id="experiment" viewBox="0 0 24 24"><path d="M9 3h6M10 3v7L4 19a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-9V3M7 15h10"/></symbol>
        <symbol id="campaign" viewBox="0 0 24 24"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/></symbol>
        <symbol id="history" viewBox="0 0 24 24"><path d="M5 5h14v16H5zM9 3h6v4H9zM8 12h8M8 16h6"/></symbol>
      </defs>
    </svg>
    <a href="#main-content" class="skip-link">跳至主要内容</a>
    <header class="app-header">
      <RouterLink to="/" class="brand" aria-label="HEAT 实时仪表盘"><img :src="logo" alt="HEAT" /><span>实验控制平台</span></RouterLink>
      <div class="header-page"><span class="header-divider"></span><span>{{ currentPage.label }}</span></div>
      <img :src="character" class="header-character" alt="" />
      <span class="header-caption">让每一次探索，都有迹可循</span>
      <button class="mobile-menu" type="button" aria-controls="main-navigation" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">{{ menuOpen ? '收起导航' : '展开导航' }}</button>
    </header>
    <aside class="app-sidebar" :class="{ 'is-open': menuOpen }">
      <span class="nav-caption">WORKSPACE</span>
      <nav id="main-navigation" aria-label="主导航">
        <template v-for="item in navigation" :key="item.path">
          <template v-if="item.path === '/experiment'">
            <button class="nav-item experiment-toggle" :class="{ active: route.path.startsWith('/experiment') }" type="button" :aria-expanded="experimentOpen" aria-controls="experiment-navigation" @click="experimentOpen = !experimentOpen">
              <svg class="nav-icon" aria-hidden="true"><use href="#experiment" /></svg><span class="experiment-label">实验自动化</span><svg class="nav-chevron" :class="{ expanded: experimentOpen }" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
            </button>
            <div v-if="experimentOpen" id="experiment-navigation" class="experiment-subnav">
              <RouterLink to="/experiment/batch" :class="{active: route.path.startsWith('/experiment/batch')}" :aria-current="route.path.startsWith('/experiment/batch') ? 'page' : undefined">引导式</RouterLink>
              <RouterLink to="/experiment/editor" :class="{active: route.path === '/experiment/editor' || route.path === '/experiment'}" :aria-current="route.path === '/experiment/editor' ? 'page' : undefined">搭建式</RouterLink>
            </div>
          </template>
          <RouterLink v-else :to="item.path" :title="item.label" class="nav-item" :class="{ active: route.path === item.path }">
            <svg class="nav-icon" aria-hidden="true"><use :href="`#${item.icon}`" /></svg><span>{{ item.label }}</span><img v-if="route.path === item.path" :src="star" class="nav-star decoration" alt="" />
          </RouterLink>
        </template>
      </nav>
      <div class="sidebar-garden" aria-hidden="true"><img :src="flowers" class="decoration" alt="" /></div>
      <div class="sidebar-foot"><img :src="planet" class="sidebar-planet decoration" alt="" /><span>HEAT LAB<br /><small>探索 · 控制 · 记录</small></span></div>
    </aside>
    <main id="main-content" class="app-main" tabindex="-1">
      <div class="page-heading"><div class="heading-title"><img :src="bow" class="heading-bow decoration" alt="" /><div><p>{{ currentPage.caption }}</p><h1>{{ currentPage.label }}</h1></div></div><span class="page-heading-note">HEAT / LABORATORY</span></div>
      <router-view />
      <div class="workspace-footer"><span>HEAT · 实验控制平台</span><img :src="cat" alt="" /></div>
    </main>
  </div>
</template>

<style scoped>
.experiment-toggle { box-sizing: border-box; width: 100%; background: transparent; font-family: inherit; font-size: inherit; text-align: left; cursor: pointer; padding-right: 10px; gap: 10px; }
.experiment-label { white-space: nowrap; flex-shrink: 0; }
.nav-chevron { margin-left: auto; width: 12px; height: 12px; flex-shrink: 0; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; transition: transform .15s; }
.nav-chevron.expanded { transform: rotate(180deg); }
.experiment-subnav { display: grid; gap: 4px; padding: 0 12px 12px 44px; }
.experiment-subnav a { padding: 10px 14px; border-radius: 8px; color: #56738f; text-decoration: none; font-size: 14px; }
.experiment-subnav a:hover, .experiment-subnav a.active { color: #147bc4; background: #e6f3ff; }
@media (min-width: 769px) and (max-width: 1199px) { .nav-chevron { display: none; } .experiment-subnav { padding: 0 0 8px; } .experiment-subnav a { padding: 8px 2px; text-align: center; font-size: 12px; } }
</style>
