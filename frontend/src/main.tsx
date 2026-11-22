import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { WagmiProvider } from 'wagmi'
import App from './App'
import { walletConfig } from './wallet-config'
import './styles.css'
import './visual-refresh.css'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5000 } } })

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><WagmiProvider config={walletConfig}><QueryClientProvider client={queryClient}><BrowserRouter><App /></BrowserRouter></QueryClientProvider></WagmiProvider></React.StrictMode>,
)
