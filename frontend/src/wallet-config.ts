import { createConfig, http } from 'wagmi'
import { base, bsc, mainnet } from 'wagmi/chains'
import { coinbaseWallet, injected, metaMask, walletConnect } from 'wagmi/connectors'

const walletConnectProjectId = import.meta.env.VITE_WALLETCONNECT_PROJECT_ID?.trim()

export const walletConfig = createConfig({
  chains: [mainnet, bsc, base],
  connectors: [
    metaMask(),
    coinbaseWallet({ appName: 'ClawIntel' }),
    injected(),
    ...(walletConnectProjectId ? [walletConnect({ projectId: walletConnectProjectId })] : []),
  ],
  transports: {
    [mainnet.id]: http(),
    [bsc.id]: http(),
    [base.id]: http(),
  },
  multiInjectedProviderDiscovery: true,
})

export const hasWalletConnectProjectId = Boolean(walletConnectProjectId)
