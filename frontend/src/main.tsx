import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { initTheme } from './theme'
import './styles/tokens.css'
import './styles/base.css'
import './styles/panes.css'
import './styles/charts.css'
import './styles/traders.css'
import './styles/trade.css'
import './styles/plans.css'

initTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
