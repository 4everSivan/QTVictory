import '@testing-library/jest-dom/vitest'

// jsdom 无布局引擎：为图表组件提供固定视口尺寸（§5.4 测量的兜底值）
Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
  configurable: true,
  value: 800,
})
Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
  configurable: true,
  value: 400,
})
