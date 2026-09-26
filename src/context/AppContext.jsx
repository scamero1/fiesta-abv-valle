import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'

const AppContext = createContext(null)
const STORAGE_KEY = 'agv-fiesta-flujo-state-v1'

const DEFAULT_STATE = {
  fotoCapturada: null,
  escenarioSeleccionado: null,
  fotoProcesada: null,
  fotoUrlDescarga: null,
  loadingProcesamiento: false,
}

function readFromStorage() {
  try {
    if (typeof sessionStorage === 'undefined') return DEFAULT_STATE
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_STATE
    const parsed = JSON.parse(raw)
    return { ...DEFAULT_STATE, ...parsed, loadingProcesamiento: false }
  } catch {
    return DEFAULT_STATE
  }
}

function writeToStorage(state) {
  try {
    let fotoUrlDescargaPersist = null
    const fud = state.fotoUrlDescarga
    if (fud) {
      if (typeof fud === 'string') {
        fotoUrlDescargaPersist = fud.startsWith('blob:') ? null : fud
      } else if (typeof fud === 'object') {
        const esBlob = fud.type === 'blob' || (typeof fud.url === 'string' && fud.url.startsWith('blob:'))
        if (!esBlob) {
          fotoUrlDescargaPersist = {
            type: fud.type,
            url: fud.url,
            id: fud.id || null,
          }
        }
      }
    }
    const snapshot = {
      fotoCapturada: state.fotoCapturada,
      escenarioSeleccionado: state.escenarioSeleccionado,
      fotoProcesada: state.fotoProcesada,
      fotoUrlDescarga: fotoUrlDescargaPersist,
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
  } catch {
    // storage full (base64 grande) - silencioso, no es crítico
  }
}

export function AppProvider({ children }) {
  const initial = useRef(readFromStorage())
  const [fotoCapturada, setFotoCapturada] = useState(initial.current.fotoCapturada)
  const [escenarioSeleccionado, setEscenarioSeleccionado] = useState(initial.current.escenarioSeleccionado)
  const [fotoProcesada, setFotoProcesada] = useState(initial.current.fotoProcesada)
  const [fotoUrlDescarga, setFotoUrlDescarga] = useState(initial.current.fotoUrlDescarga)
  const [loadingProcesamiento, setLoadingProcesamiento] = useState(false)

  const latestState = {
    fotoCapturada,
    escenarioSeleccionado,
    fotoProcesada,
    fotoUrlDescarga,
  }

  useEffect(() => {
    writeToStorage(latestState)
  }, [fotoCapturada, escenarioSeleccionado, fotoProcesada, fotoUrlDescarga])

  useEffect(() => {
    const onBeforeUnload = () => writeToStorage(latestState)
    const onVisibility = () => { if (document.visibilityState === 'hidden') writeToStorage(latestState) }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [fotoCapturada, escenarioSeleccionado, fotoProcesada, fotoUrlDescarga])

  const reiniciarFlujo = useCallback(() => {
    setFotoCapturada(null)
    setEscenarioSeleccionado(null)
    setFotoProcesada(null)
    setFotoUrlDescarga(null)
    setLoadingProcesamiento(false)
    try { sessionStorage.removeItem(STORAGE_KEY) } catch {}
  }, [])

  const value = {
    fotoCapturada,
    setFotoCapturada,
    escenarioSeleccionado,
    setEscenarioSeleccionado,
    fotoProcesada,
    setFotoProcesada,
    fotoUrlDescarga,
    setFotoUrlDescarga,
    loadingProcesamiento,
    setLoadingProcesamiento,
    reiniciarFlujo,
    persistido: Boolean(fotoCapturada || fotoProcesada),
  }

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp debe usarse dentro de AppProvider')
  return ctx
}
