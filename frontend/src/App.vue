<template>
  <el-container class="app-container">
    <el-header class="app-header">
      <div class="header-left">
        <h1 class="app-title">Heat 控制系统</h1>
      </div>
      <el-menu mode="horizontal" router :default-active="$route.path" class="header-menu">
        <el-menu-item index="/">实时仪表盘</el-menu-item>
        <el-menu-item index="/control">设备控制</el-menu-item>
        <el-menu-item index="/experiment">实验自动化</el-menu-item>
        <el-menu-item index="/history">实验历史</el-menu-item>
      </el-menu>
    </el-header>
    <el-main class="app-main">
      <router-view v-slot="{ Component }">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </el-main>
  </el-container>
</template>

<style>
body {
  margin: 0;
  padding: 0;
  background: #f5f7fa;
}
.app-container {
  min-height: 100vh;
}
.app-header {
  display: flex;
  align-items: center;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  padding: 0 20px;
  height: 60px !important;
}
.header-left {
  margin-right: 30px;
}
.app-title {
  font-size: 20px;
  color: #303133;
  margin: 0;
  white-space: nowrap;
}
.header-menu {
  border-bottom: none !important;
}
.app-main {
  background: #f5f7fa;
  min-height: calc(100vh - 60px);
}
</style>
