import { useEffect } from 'react'
import { useResponsive } from '../hooks/useResponsive.js'

export default function ResponsiveProviderInjector({ children }) {
  const { orientation, isPortrait, isLandscape, isWide, isTall, breakpoint, tabletSize, w, h } = useResponsive()

  useEffect(() => {
    const root = document.documentElement
    root.setAttribute('data-orientation', orientation)
    root.setAttribute('data-breakpoint', breakpoint)
    root.setAttribute('data-form', tabletSize)
    root.style.setProperty('--window-w', `${w}px`)
    root.style.setProperty('--window-h', `${h}px`)
    root.style.setProperty('--viewport-ratio', (w / h).toFixed(3))
    root.style.setProperty('--scale-vmin', `${Math.min(w, h) / 900}`)
    root.style.setProperty('--orientation', orientation)
    root.classList.toggle('is-portrait', isPortrait)
    root.classList.toggle('is-landscape', isLandscape)
    root.classList.toggle('is-wide', isWide)
    root.classList.toggle('is-tall', isTall)
  }, [orientation, isPortrait, isLandscape, isWide, isTall, breakpoint, tabletSize, w, h])

  return children
}
