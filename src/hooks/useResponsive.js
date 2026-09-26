import { useEffect, useState, useMemo } from 'react'

const BREAKPOINTS = {
  xs: 0,
  sm: 576,
  md: 768,
  lg: 992,
  xl: 1200,
  xxl: 1600,
}

export function useResponsive() {
  const [size, setSize] = useState(() => ({
    w: typeof window !== 'undefined' ? window.innerWidth : 1024,
    h: typeof window !== 'undefined' ? window.innerHeight : 768,
  }))
  const [orientation, setOrientation] = useState(() => getOrientation())

  useEffect(() => {
    let resizeTimer = null
    const handleResize = () => {
      clearTimeout(resizeTimer)
      resizeTimer = setTimeout(() => {
        const w = window.innerWidth
        const h = window.innerHeight
        setSize({ w, h })
        setOrientation(getOrientation())
      }, 80)
    }
    const handleOrientation = () => {
      clearTimeout(resizeTimer)
      resizeTimer = setTimeout(() => {
        setSize({ w: window.innerWidth, h: window.innerHeight })
        setOrientation(getOrientation())
      }, 60)
    }
    window.addEventListener('resize', handleResize, { passive: true })
    window.addEventListener('orientationchange', handleOrientation, { passive: true })
    window.addEventListener('load', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      window.removeEventListener('orientationchange', handleOrientation)
      clearTimeout(resizeTimer)
    }
  }, [])

  return useMemo(() => {
    const { w, h } = size
    const ratio = w / h
    const isLandscape = w > h
    const isPortrait = h >= w
    const isSquare = Math.abs(1 - ratio) < 0.15
    const isTall = ratio < 0.7
    const isWide = ratio > 1.45

    const bp =
      w >= BREAKPOINTS.xxl ? 'xxl'
      : w >= BREAKPOINTS.xl ? 'xl'
      : w >= BREAKPOINTS.lg ? 'lg'
      : w >= BREAKPOINTS.md ? 'md'
      : w >= BREAKPOINTS.sm ? 'sm'
      : 'xs'

    const tabletSize =
      w < 600 ? 'phone'
      : w < 900 ? 'tablet-sm'
      : w < 1200 ? 'tablet-md'
      : w < 1600 ? 'tablet-lg'
      : 'kiosk'

    const screen = `${tabletSize}-${orientation}`

    const dpr = typeof window !== 'undefined' ? (window.devicePixelRatio || 1) : 1

    const vw = (pct) => (w * pct) / 100
    const vh = (pct) => (h * pct) / 100
    const vmin = (pct) => (Math.min(w, h) * pct) / 100

    return {
      w,
      h,
      orientation,
      isLandscape,
      isPortrait,
      isSquare,
      isTall,
      isWide,
      breakpoint: bp,
      tabletSize,
      screen,
      dpr,
      ratio,
      vw,
      vh,
      vmin,
      clampFont: (min, max, baseAtPx = 1024) => {
        const factor = Math.min(1.4, Math.max(0.65, w / baseAtPx))
        return `clamp(${min}px, ${baseAtPx * 0.012}vw, ${max}px)`
      },
    }
  }, [size, orientation])
}

function getOrientation() {
  if (typeof window === 'undefined') return 'landscape'
  const o = window.screen?.orientation?.type
  if (o) {
    if (o.includes('portrait')) return 'portrait'
    if (o.includes('landscape')) return 'landscape'
  }
  return window.innerWidth >= window.innerHeight ? 'landscape' : 'portrait'
}

export function useBreakpointAtLeast(bp) {
  const { breakpoint } = useResponsive()
  const order = ['xs', 'sm', 'md', 'lg', 'xl', 'xxl']
  return order.indexOf(breakpoint) >= order.indexOf(bp)
}

export default useResponsive
